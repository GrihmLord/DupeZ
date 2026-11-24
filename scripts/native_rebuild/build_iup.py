"""Compile an isolated IUP 3.30 Win64 core with one reviewed C pointer fix."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.native_rebuild import common

ROOT, BASE = common.ROOT, common.BASE
sys.path.insert(0, str(ROOT))
from scripts import verify_iup_source_archive as archive_verifier

ARCHIVE = ROOT / "build/source-delivery-20261024/archives/iup-3.30_Sources.zip"
SOURCE = BASE / "iup-patched-source/iup"
PATCH = ROOT / "packaging/native-patches/iup-3.30-win32-dib-pointer.patch"
PATCH_PIN = (501, '498a45796bf6cfb390a718df7a322d0b87670babf6d2696693428bb5ff33a6ae')
PATCH_TARGET = "src/win/iupwin_image.c"
PATCH_BEFORE = (22602, "60f8ca5876dcd106985e2ea0ca8658434352d06f98da8f13a3d606b9f926192e")
PATCH_AFTER = (22661, "3d1ace4340996853c9bdaa4b7210d151ca2efb77ba8f5398ee0820b20eed8717")
LINK_RUNTIME = ["-rtlib=compiler-rt", "-unwindlib=libunwind", "-stdlib=libc++", "-fuse-ld=lld"]
CONFIG_SHA = "635876c04c9cdbcff866fe2d0a80f5a92aaba6b6f79461eb4941aeac08e34cd2"
TECMAKE_SHA = "b2803a4d5f143c460e953e2ec72af4276b290dd9854ea83345ece68820867756"
DEFINES = ["COBJMACROS", "_UNICODE", "USE_NEW_DRAW", "_WIN32_WINNT=0x0601", "_WIN32_IE=0x0900",
           "WINVER=0x0601", "NOTREEVIEW", "UNICODE", "IUP_DLL", "TEC_UNAME=dllw6_64", "TEC_SYSNAME=Win64",
           "TEC_LITTLEENDIAN", "TEC_64", "WIN32", "WIN64", "NDEBUG"]
LIBRARIES = ["kernel32", "user32", "gdi32", "winspool", "comdlg32", "advapi32", "shell32", "uuid",
             "oleaut32", "ole32", "comctl32"]
INCLUDES = ["../include", ".", "win/wdl", "win", "../etc"]


def snapshot_row(path: Path, raw: bytes) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def patched_files(files: dict[str, bytes], patch: bytes) -> dict[str, bytes]:
    """Apply only the approved delta; pin both sides instead of interpreting patch commands."""
    common.require((len(patch), hashlib.sha256(patch).hexdigest()) == PATCH_PIN, "Reviewed IUP patch changed")
    before = files[PATCH_TARGET]
    common.require((len(before), hashlib.sha256(before).hexdigest()) == PATCH_BEFORE, "IUP patch preimage changed")
    after = before.replace(b"    HDC hDC;\n    BITMAPINFOHEADER* bmih", b"    HDC hDC;\n    void* dib_bits = NULL;\n    BITMAPINFOHEADER* bmih")
    after = after.replace(b"DIB_RGB_COLORS, &bits, NULL, 0x0);", b"DIB_RGB_COLORS, &dib_bits, NULL, 0x0);\n    bits = (BYTE*)dib_bits;")
    common.require((len(after), hashlib.sha256(after).hexdigest()) == PATCH_AFTER, "IUP patch postimage differs")
    return {**files, PATCH_TARGET: after}


def prepare_source() -> tuple[dict[str, bytes], list[dict], dict]:
    body = archive_verifier.snapshot(ARCHIVE, dict(zip(("size", "sha256"), archive_verifier.SOURCE_PIN)),
                                     archive_verifier.MAX_REPORT)
    files = archive_verifier.source_files(body)
    common.require(len(files) == 2745, "Unexpected IUP source archive")
    patch = common.ordinary(PATCH).read_bytes()
    patch_row = snapshot_row(PATCH, patch)
    files = patched_files(files, patch)
    common.ordinary(SOURCE, missing=True)
    if not SOURCE.exists():
        SOURCE.mkdir(parents=True)
        for relative, raw in files.items():
            path = SOURCE / relative
            common.ordinary(path, missing=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as target:
                target.write(raw)
    expected = set(files)
    observed = set()
    for path in SOURCE.rglob("*"):
        common.ordinary(path)
        if path.is_file():
            observed.add(path.relative_to(SOURCE).as_posix())
    common.require(observed == expected, "IUP source tree has missing or unexpected files")
    rows = []
    for relative, raw in files.items():
        row = snapshot_row(SOURCE / relative, raw)
        common.require(common.pin(SOURCE / relative) == row, "IUP source differs from reviewed snapshot")
        rows.append(row)
    delta = {"path": PATCH_TARGET, "patch": patch_row,
             "before": dict(zip(("size", "sha256"), PATCH_BEFORE)),
             "after": dict(zip(("size", "sha256"), PATCH_AFTER)),
             "reason": "Typed void pointer bridge for CreateDIBSection output; no warning suppression",
             "other_source_files_changed": 0}
    return files, rows, delta


def source_selection(files: dict[str, bytes]) -> list[str]:
    config = files["src/config.mak"]
    common.require(hashlib.sha256(config).hexdigest() == CONFIG_SHA
                   and hashlib.sha256(files["tecmakewin.mak"]).hexdigest() == TECMAKE_SHA,
                   "Reviewed source recipe changed")
    # This is intentionally not a general Makefile interpreter: the complete
    # reviewed file pin binds the selected Win64/new-draw/DLL branches.
    collapsed = config.decode("ascii").replace("\\\n", " ")
    base = re.search(r"^SRC = (.*)$", collapsed, re.M).group(1).split()
    windows = ["win/iupwin_common.c", *re.search(r"^  SRC \+= win/iupwin_common.c(.*)$", collapsed, re.M).group(1).split()]
    wdl = re.search(r"^    WDL := (.*)$", collapsed, re.M).group(1).split()
    draw = ["win/iupwin_draw_wdl.c", "win/iupwin_draw_gdi.c", "win/iupwin_image_wdl.c"]
    platform = ["win/iupwindows_main.c", "win/iupwindows_help.c", "win/iupwindows_info.c"]
    common.require([len(base), len(windows), len(wdl)] == [101, 36, 18], "Source branch selection differs")
    selected = base + windows + wdl + draw + platform
    common.require(len(selected) == len(set(selected)) == 161 and all("src/" + name in files for name in selected),
                   "Source selection incomplete or duplicated")
    common.require(b"USE_NEW_DRAW := Yes" in config and b"DEF_FILE = iup.def" in config
                   and b"WIN32VER = 0x0601" in config, "Source feature configuration differs")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output = common.ordinary(args.output, missing=True)
    common.require(output.is_relative_to(BASE) and output != BASE and not output.exists(), "Use a fresh private output")
    output.mkdir(parents=True)
    (output / "objects").mkdir()
    (output / "logs").mkdir()
    files, source_rows, source_delta = prepare_source()
    selected = source_selection(files)
    recipes = [common.pin(Path(__file__)), common.pin(Path(common.__file__)),
               common.pin(Path(common.process.__file__)), common.pin(Path(archive_verifier.__file__))]
    source_index = output / "source-inventory.json"
    with source_index.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(source_rows, stream, indent=2)
        stream.write("\n")
    defines = ["-D" + value for value in DEFINES]
    includes = ["-I" + value for value in INCLUDES]
    plan = {"schema": "dupez.iup-native-compilation-plan.v1", "source_archive": common.pin(ARCHIVE),
            "source_inventory": common.pin(source_index), "upstream_logical_target": "dllw6_64",
            "actual_toolchain": "llvm-mingw-20261117-ucrt-x86_64", "source_files": selected,
            "c_source_count": 161, "features": {"win64": True, "new_draw": True, "dll": True},
            "defines": DEFINES, "includes": INCLUDES, "libraries": LIBRARIES,
            "resource": "etc/iup.rc", "export_definition": "src/iup.def", "optimization": "-O2",
            "language_mode": "gnu99", "source_patched": True, "source_delta": source_delta,
            "explicit_link_runtime_configuration": LINK_RUNTIME,
            "compiler_identity_section": "-fno-ident", "file_prefix_mapping": "IUP source root to iup-source",
            "reproducibility_choices": {"SOURCE_DATE_EPOCH": "0", "ZERO_AR_DATE": "1", "pe_timestamp": "--no-insert-timestamp"},
            "recipes": recipes, "toolchain_inventory": common.pin(common.INVENTORY),
            "original_msvc_binary_reproduction_claimed": False, "shipped_binaries_replaced": False,
            "compat_runtime_tested": False, "release_approval": False}
    plan_path = output / "plan.json"
    with plan_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")
    if not args.execute:
        print(json.dumps({"status": "prepared-not-executed", "plan": common.pin(plan_path)}))
        return 0
    environment = common.closed_environment(output / "private")
    archive_row = {"path": ARCHIVE.relative_to(ROOT).as_posix(),
                   "size": archive_verifier.SOURCE_PIN[0], "sha256": archive_verifier.SOURCE_PIN[1]}
    extra = [*recipes, *source_rows, source_delta["patch"], archive_row, common.pin(plan_path), common.pin(source_index)]
    commands = []
    results = []
    with common.held_inputs(extra) as locked, ExitStack() as object_locks:
        commands.append(common.run_tool("x86_64-w64-mingw32-clang.exe", ["--version"],
                        cwd=SOURCE / "src", env=environment, log=output / "logs/compiler-version.log"))
        common.require(commands[-1]["exit_code"] == 0, "Compiler version probe failed")

        def compile_one(item):
            index, name = item
            obj = output / "objects" / (f"{index:03d}-" + Path(name).stem + ".o")
            arguments = ["-std=gnu99", "-O2", "-Wall", "-fno-ident", "-ffile-prefix-map=" + str(SOURCE) + "=iup-source",
                         *defines, *includes, "-c", name, "-o", str(obj)]
            result = common.run_tool("x86_64-w64-mingw32-clang.exe", arguments, cwd=SOURCE / "src",
                                     env=environment, log=output / "logs" / f"compile-{index:03d}.log")
            if result["exit_code"] == 0:
                result["object"] = common.pin(obj)
            return result

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(compile_one, enumerate(selected)))
        commands.extend(results)
        if all(row["exit_code"] == 0 for row in results):
            resource = output / "objects/iup-resource.o"
            commands.append(common.run_tool("x86_64-w64-mingw32-windres.exe",
                ["--codepage=1252", "-O", "coff", *defines, *includes, "../etc/iup.rc", "-o", str(resource)],
                cwd=SOURCE / "src", env=environment, log=output / "logs/resource.log"))
            if commands[-1]["exit_code"] == 0:
                objects = [row["object"] for row in results] + [common.pin(resource)]
                for row in objects:
                    object_locks.enter_context(common.held_file(row))
                response = output / "objects.rsp"
                with response.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write("\n".join('"' + str(ROOT / row["path"]).replace("\\", "/") + '"' for row in objects) + "\n")
                object_locks.enter_context(common.held_file(common.pin(response)))
                commands.append(common.run_tool("x86_64-w64-mingw32-clang.exe",
                    [*LINK_RUNTIME, "-shared", "-o", str(output / "iup.dll"), "-Wl,--out-implib=" + str(output / "libiup.dll.a"),
                     "-Wl,--no-insert-timestamp", "@" + str(response), "iup.def", *["-l" + value for value in LIBRARIES]],
                    cwd=SOURCE / "src", env=environment, log=output / "logs/link.log"))
        succeeded = all(row["exit_code"] == 0 for row in commands) and (output / "iup.dll").is_file()
        artifacts = [common.pin(output / name) for name in ("iup.dll", "libiup.dll.a") if (output / name).is_file()]
        for row in artifacts:
            object_locks.enter_context(common.held_file(row))
        result = {"schema": "dupez.iup-native-compilation-observation.v1", "status": "compiled" if succeeded else "compile-failed",
                  "plan": common.pin(plan_path), "held_input_count": len(locked), "commands": commands,
                  "artifacts": artifacts, "native_guard_dependencies": [row for row in locked if row["path"] in {
                      Path(common.__file__).relative_to(ROOT).as_posix(), Path(common.process.__file__).relative_to(ROOT).as_posix()}],
                  "c_source_count": 161, "native_library_executed": False, "source_patched": True,
                  "source_delta": source_delta,
                  "original_msvc_binary_reproduction_claimed": False, "shipped_binaries_replaced": False,
                  "compat_runtime_tested": False, "release_approval": False}
    with (output / "receipt.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "failed_commands": sum(row["exit_code"] != 0 for row in commands),
                      "artifacts": result["artifacts"]}))
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
