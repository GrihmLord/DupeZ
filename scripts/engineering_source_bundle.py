#!/usr/bin/env python3
"""Collect an offline, deterministic source-input bundle for the raster profile.

This is engineering source-delivery evidence, not complete corresponding source
or permission to distribute. No downloaded source, payload executable, installer
or build backend is executed. The local PyInstaller reader inspects hash-bound builds.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import corresponding_source as source
from scripts import native_build_evidence as native
from scripts import validate_frozen_runtime as runtime

PROFILE = "frozen-raster-no-qtnetwork"
SCHEMA = "dupez.engineering-source-bundle.v1"
EPOCH = (1980, 1, 1, 0, 0, 0)
RECIPES = (
    "scripts/engineering_source_bundle.py", "scripts/corresponding_source.py",
    "scripts/prepare_qt_candidate.py", "scripts/prepare_qt_adoption.py",
    "scripts/verify_qt_source_correspondence.py", "scripts/verify_qt6121_translation_sources.py",
    "scripts/verify_qt_translation_sources.py", "scripts/validate_frozen_runtime.py",
    "scripts/msvc_runtime_stage.py", "scripts/native_build_evidence.py",
    "scripts/license_payload.py", "scripts/release_preflight.py", "scripts/sbom.py",
    "scripts/verify_requirements_lock.py", "packaging/build_common.py",
    "scripts/native_rebuild/__init__.py", "scripts/native_rebuild/common.py",
    "scripts/native_rebuild/process.py", "scripts/native_rebuild/acquire_toolchain.py",
    "scripts/native_rebuild/build_iup.py", "scripts/native_rebuild/build_clumsy.py",
    "packaging/native-patches/iup-3.30-win32-dib-pointer.patch",
    "docs/legal/ENGINEERING_SOURCE_REBUILD_2026-11-24.md",
    "packaging/native_runtime_policy.py", "packaging/msvc-redist-inputs.json",
    "packaging/qt-raster-no-network-inputs.json", "packaging/requirements-build-locked.txt",
    "packaging/dupez_gpu.spec", "packaging/dupez_compat.spec",
)
EVIDENCE = (
    "qt-6121-input-review-2026-11-24.json", "qt-6121-source-correspondence-2026-11-24.json",
    "qt-6121-translations-2026-11-24.json", "qt-6121-licensing-review-2026-11-24.json",
    "msvc-private-stage-2026-11-24.json",
    "iup-source-review-2026-11-24.json", "iup-source-archive-review-2026-11-24.json",
    "clumsy-native-compilation-2026-11-24.json",
    "iup-native-compilation-2026-11-24.json",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise source.SourceInputError(message)


def fingerprint(path: Path) -> dict:
    path = source.checked_path(path)
    with path.open("rb") as stream:
        return {"size": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def lock(stack: ExitStack, path: Path, expected: dict | None = None) -> dict:
    path = source.checked_path(path)
    pin = expected or fingerprint(path)
    stack.enter_context(runtime._locked_release_executable(
        path, expected_hash=pin["sha256"], expected_size=pin["size"]))
    return {key: pin[key] for key in ("size", "sha256")}


def json_bytes(data: bytes) -> dict:
    require(0 < len(data) <= 8 * 1024 * 1024, "Invalid metadata size")
    value = json.loads(data, object_pairs_hook=source._no_duplicates)
    require(isinstance(value, dict), "Expected metadata object")
    return value


def child(root: Path, name: str) -> Path:
    source._member_path(name)
    return source.checked_path(root / name)


def public_metadata(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            public_metadata(key)
            public_metadata(item)
    elif isinstance(value, list):
        for item in value:
            public_metadata(item)
    elif isinstance(value, str):
        require(not re.match(r"^[A-Za-z]:[\\/]", value)
                and "\\Users\\" not in value and "/Users/" not in value,
                "Absolute private path in publication metadata")


def local_git_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    inherited = dict(os.environ if environment is None else environment)
    count = inherited.get("GIT_CONFIG_COUNT", "0")
    require(count.isdecimal() and 0 <= int(count) <= 128, "Invalid inherited Git config count")
    permitted = {"GIT_CONFIG_COUNT"}
    for index in range(int(count)):
        key_name, value_name = f"GIT_CONFIG_KEY_{index}", f"GIT_CONFIG_VALUE_{index}"
        key = inherited.get(key_name, "")
        require(key.split(".", 1)[0] in {"credential", "http"}, "Non-transport Git override is prohibited")
        permitted.update((key_name, value_name))
    overrides = set(runtime._git_override_environment_names(inherited))
    require(overrides <= permitted, "Unexpected Git provenance override")
    # Return the existing system-only environment. Transport values, including
    # empty injected auth values, are never forwarded or written to receipts.
    return runtime._git_environment()


def git_bytes(arguments: list[str], environment: dict[str, str]) -> bytes:
    executable = runtime._trusted_git_executable()
    return subprocess.run([str(executable), "--no-replace-objects", "-c", "core.fsmonitor=false",
                           "-c", "core.untrackedCache=false", "-C", str(ROOT), *arguments],
                          cwd=executable.parent, env=environment, capture_output=True, check=True, timeout=90).stdout


def verify_checkpoint_files(checkpoint: str, files: dict[str, tuple[Path, dict]], environment: dict[str, str]) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", checkpoint), "Expected immutable source checkpoint")
    for name, (path, expected) in files.items():
        if name.startswith("recipes/"):
            relative = name.removeprefix("recipes/")
            source._member_path(relative)
            committed = git_bytes(["cat-file", "blob", checkpoint + ":" + relative], environment)
            require(len(committed) == expected["size"] and hashlib.sha256(committed).hexdigest() == expected["sha256"]
                    and path.read_bytes() == committed, "Recipe or manifest differs from application checkpoint: " + relative)


def expected_inventory(inventory: dict, build_lock: str, candidate: dict, msvc: dict) -> dict:
    result = json.loads(json.dumps(inventory))
    bootloader = next(row["version"] for row in inventory["additional_components"] if row["id"] == "pyinstaller-bootloader")
    require(re.findall(r"^pyinstaller==([^\s]+)", build_lock, re.M) == [bootloader], "Freezer/source versions differ")
    tools = {"freeze-" + name: version for name, version in re.findall(
        r"^([a-z][a-z0-9-]*)==([^\s]+)", build_lock, re.M) if name != "pyinstaller"}
    require(len(tools) == 6, "Unexpected freezer tool inventory")
    tools.update({"bundle-" + row["id"]: row["version"] for row in candidate["inputs"]
                  if row["role"] == "builder-wheel"})
    require(len(tools) == 10, "Unexpected candidate tool inventory")
    tools.update({"qttools-translation-compiler": candidate["qt_version"],
                  "runtime-msvc": msvc["package"]["version"]})
    result["additional_components"].extend({"id": name, "version": version} for name, version in sorted(tools.items()))
    return result


def native_component(row: dict) -> str:
    name, origin = row["destination"], row["origin"]
    source._member_path(name)
    if origin == "pinned-msvc-redist":
        require(name in {"MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll"}, "Unmapped staged runtime")
        return "runtime-msvc"
    if origin == "verified-base-python":
        return "runtime-msvc" if name.upper().startswith("VCRUNTIME") else "cpython-runtime"
    if origin == "managed-native":
        mapping = {"app/firewall/clumsy.exe": "clumsy", "app/firewall/iup.dll": "iup",
                   "app/firewall/WinDivert.dll": "windivert", "app/firewall/WinDivert64.sys": "windivert"}
        require(name in mapping, "Unmapped managed runtime")
        return mapping[name]
    require(origin == "locked-build-venv", "Unexpected native origin")
    if name.startswith("PyQt6/Qt6/"):
        leaf = name.rsplit("/", 1)[-1]
        if leaf in {"Qt6Svg.dll", "Qt6SvgWidgets.dll", "qsvg.dll", "qsvgicon.dll"}:
            return "qtsvg-native"
        if leaf in {"qicns.dll", "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll"}:
            return "qtimageformats-native"
        require(leaf in {"Qt6Core.dll", "Qt6Gui.dll", "Qt6Test.dll", "Qt6Widgets.dll", "Qt6PrintSupport.dll",
                         "qgif.dll", "qico.dll", "qjpeg.dll", "qminimal.dll", "qoffscreen.dll", "qwindows.dll",
                         "qmodernwindowsstyle.dll"}, "Unmapped Qt native payload")
        return "qtbase-native"
    if name.startswith("PyQt6/"):
        return "pyqt6-sip" if name.startswith("PyQt6/sip.") else "pyqt6"
    prefixes = {"numpy/": "numpy", "numpy.libs/": "numpy", "PIL/": "pillow", "charset_normalizer/": "charset-normalizer",
                "cryptography/": "cryptography", "psutil/": "psutil", "yaml/": "pyyaml", "zeroconf/": "zeroconf",
                "pythonwin/": "pywin32", "win32/": "pywin32", "pywin32_system32/": "pywin32",
                "_sounddevice_data/": "sounddevice", "_cffi_backend.": "cffi"}
    for prefix, component in prefixes.items():
        if name.startswith(prefix):
            return component
    if re.fullmatch(r"[0-9a-f]{20}__mypyc\.cp313-win_amd64\.pyd", name):
        return "charset-normalizer"
    raise source.SourceInputError("Native file has no source component mapping")


def locate_archive(stack: ExitStack, caches: list[Path], artifact: dict) -> Path:
    for directory in caches:
        path = child(directory, artifact["filename"])
        if path.exists() and path.stat().st_size == artifact["size"] and fingerprint(path)["sha256"] == artifact["sha256"]:
            lock(stack, path, artifact)
            return path
    raise source.SourceInputError("Pinned source archive unavailable: " + artifact["filename"])


def zip_info(name: str) -> zipfile.ZipInfo:
    source._member_path(name)
    info = zipfile.ZipInfo(name, EPOCH)
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def write_bundle(path: Path, files: dict[str, tuple[Path, dict]], metadata: dict[str, bytes], receipt: dict) -> None:
    path = source.checked_path(path)
    source.checked_path(path.parent, directory=True)
    require(not path.exists(), "Bundle already exists")
    require(not set(files).intersection(metadata) and "bundle-receipt.json" not in files | metadata,
            "Duplicate output entry")
    names = [*files, *metadata, "bundle-receipt.json"]
    require(len({name.casefold() for name in names}) == len(names), "Case-aliased output entry")
    public_metadata(receipt)
    metadata = {**metadata, "bundle-receipt.json": source.canonical_json(receipt)}
    with tempfile.NamedTemporaryFile(prefix=".engineering-source-", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as bundle:
            for name in sorted(files.keys() | metadata.keys()):
                info = zip_info(name)
                if name in metadata:
                    bundle.writestr(info, metadata[name])
                    continue
                input_path, expected = files[name]
                total, digest = 0, hashlib.sha256()
                with input_path.open("rb") as original, bundle.open(info, "w", force_zip64=True) as output:
                    for block in iter(lambda: original.read(1024 * 1024), b""):
                        total += len(block)
                        require(total <= expected["size"], "Input grew while bundling")
                        digest.update(block)
                        output.write(block)
                require({"size": total, "sha256": digest.hexdigest()} == expected, "Input changed while bundling")
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_bundle(path: Path, expected: dict) -> dict:
    require(expected.get("schema") == SCHEMA, "Unexpected engineering receipt")
    require(all(expected.get(key) is False for key in (
        "complete_corresponding_source", "native_rebuild_proven", "release_approved", "distribution_approved",
        "compat_runtime_tested", "public_delivery_proven")), "Engineering receipt overstates readiness")
    public_metadata(expected)
    rows = expected.get("files")
    require(isinstance(rows, list) and 0 < len(rows) < 512, "Invalid bundle inventory")
    pins = {}
    folded = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"path", "size", "sha256"}, "Invalid file pin")
        name = source._member_path(row["path"])
        require(name.casefold() not in folded and name.casefold() != "bundle-receipt.json" and type(row["size"]) is int
                and 0 <= row["size"] <= source.MAX_ARTIFACT_BYTES
                and source._HASH.fullmatch(row["sha256"]), "Invalid or duplicate bundle pin")
        pins[name] = row
        folded.add(name.casefold())
    path = source.checked_path(path)
    with ExitStack() as stack:
        verified_pin = lock(stack, path)
        source._check_zip_directory(path)
        with zipfile.ZipFile(path) as bundle:
            members = bundle.infolist()
            require(len(members) == len(pins) + 1 and not bundle.comment, "Unexpected bundle entries")
            names = [m.filename for m in members]
            require(len({name.casefold() for name in names}) == len(names) and set(names) == set(pins) | {"bundle-receipt.json"},
                    "Missing or duplicate bundle entry")
            for member in members:
                source._member_path(member.orig_filename)
                require(member.orig_filename == member.filename and not member.flag_bits & 1
                        and member.compress_type == zipfile.ZIP_STORED and member.date_time == EPOCH
                        and stat.S_IFMT(member.external_attr >> 16) == stat.S_IFREG,
                        "Unsafe or nondeterministic bundle envelope")
                if member.filename == "bundle-receipt.json":
                    require(member.file_size <= 8 * 1024 * 1024 and bundle.read(member) == source.canonical_json(expected),
                            "Bundle receipt differs from external expected receipt")
                    continue
                pin = pins[member.filename]
                require(member.file_size == pin["size"], "Bundled file size differs")
                with bundle.open(member) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                require(digest == pin["sha256"], "Bundled file digest differs")
    return {"schema": "dupez.engineering-source-verification.v1", "bundle": verified_pin,
            "receipt_sha256": hashlib.sha256(source.canonical_json(expected)).hexdigest(),
            "file_count": len(pins), "all_file_bytes_verified": True,
            "complete_corresponding_source": False, "release_approved": False}


def assemble(args: argparse.Namespace) -> dict:
    require(sys.platform == "win32", "Held Windows input locks are required")
    git_environment = local_git_environment()
    output = source.checked_path(args.output, directory=True)
    require(not output.exists(), "Use a fresh output directory")
    output.mkdir(parents=True)
    checkout = source.checked_path(args.build_root / "runtime-checkout", directory=True)
    profile = source.checked_path(checkout / "build/qt-profile", directory=True)
    files, metadata = {}, {}
    with ExitStack() as stack:
        def add(name: str, path: Path, expected: dict | None = None) -> bytes | None:
            require(name not in files and name not in metadata, "Duplicate collected path")
            pin = lock(stack, path, expected)
            files[name] = (path, pin)
            data = path.read_bytes() if pin["size"] <= 8 * 1024 * 1024 else None
            if name.endswith(".json") and data is not None:
                public_metadata(json_bytes(data))
            return data

        adoption = json_bytes(add("evidence/adoption.json", args.adoption_evidence))
        require(adoption["build"]["qt_build_profile"] == PROFILE and adoption["exact_git_archive_match"] is True,
                "Adoption record has wrong profile/source scope")
        checkpoint = adoption["checkpoint"]
        require(re.fullmatch(r"[0-9a-f]{40}", checkpoint), "Expected immutable source checkpoint")
        profile_pin = adoption["installed_engineering_profile"]["profile"]
        profile_record = json_bytes(add("context/engineering-profile.json", profile / "engineering-profile.json", profile_pin))
        require(profile_record["profile"] == PROFILE and profile_record["release_approved"] is False
                and profile_record["source_delivery_approved"] is False, "Profile readiness changed")
        inventory_bytes = add("context/third-party-components.json", profile / "packaging/third-party-components.json")
        require(hashlib.sha256(inventory_bytes).hexdigest() == profile_record["effective_inventory_sha256"], "Profile inventory changed")
        inventory = json_bytes(inventory_bytes)
        runtime_lock = add("context/requirements-locked.txt", profile / "requirements-locked.txt")
        require(hashlib.sha256(runtime_lock).hexdigest() == profile_record["effective_runtime_lock_sha256"], "Runtime lock changed")
        for name in RECIPES:
            add("recipes/" + name, child(ROOT, name))
        require(source.checked_path(args.manifest) == source.checked_path(ROOT / "packaging/engineering-source-inputs.json"),
                "Engineering manifest must use its checkpoint-owned path")
        add("recipes/packaging/engineering-source-inputs.json", args.manifest)
        verify_checkpoint_files(checkpoint, files, git_environment)
        for name in EVIDENCE:
            add("evidence/" + name, child(ROOT / "packaging/license-evidence", name))
        candidate = json_bytes((ROOT / "packaging/qt-raster-no-network-inputs.json").read_bytes())
        require(hashlib.sha256((ROOT / "packaging/qt-raster-no-network-inputs.json").read_bytes()).hexdigest()
                == profile_record["candidate_manifest_sha256"], "Candidate manifest changed")
        build_lock = (ROOT / "packaging/requirements-build-locked.txt").read_text(encoding="utf-8")
        require(files["recipes/packaging/requirements-build-locked.txt"][1]["sha256"] == profile_record["base_inputs"]["packaging/requirements-build-locked.txt"],
                "Build lock changed")
        msvc = json_bytes((ROOT / "packaging/msvc-redist-inputs.json").read_bytes())
        effective = expected_inventory(inventory, build_lock, candidate, msvc)
        expected_path = output / "expected-components.json"
        expected_path.write_bytes(source.canonical_json(effective))
        lock(stack, expected_path)
        lock(stack, args.manifest)
        manifest = source.load_manifest(args.manifest, expected_path)
        metadata["source-inputs.json"] = source.canonical_json(manifest)
        metadata["context/expected-components.json"] = source.canonical_json(effective)
        inspections, selected = {}, []
        for component in manifest["components"]:
            if component["artifacts"]:
                selected.append(component)
            for artifact in component["artifacts"]:
                path = locate_archive(stack, args.cache, artifact)
                inspections[artifact["filename"]] = source.verify_artifact(path, artifact)
                files["archives/" + artifact["filename"]] = (path, {k: artifact[k] for k in ("size", "sha256")})
        source_receipt = source.make_receipt(manifest, selected, inspections)
        metadata["source-receipt.json"] = source.canonical_json(source_receipt)
        source_pin = adoption["source_archive"]
        application = args.build_root / Path(source_pin["path"]).name
        add("application/" + application.name, application, source_pin)
        archived = git_bytes(["archive", "--format=zip", "--prefix=DupeZ-v5.8.0/", checkpoint], git_environment)
        require(len(archived) == source_pin["size"] and hashlib.sha256(archived).hexdigest() == source_pin["sha256"],
                "Application archive differs from exact checkpoint")
        mappings = {}
        components = {c["id"]: c for c in manifest["components"]}
        for variant in ("gpu", "compat"):
            observed = adoption["frozen_artifacts"][variant]
            executable = checkout / "build/runtime" / ("DupeZ-" + variant.capitalize() + ".exe" if variant == "compat" else "DupeZ-GPU.exe")
            collection = checkout / ("build/clean-" + variant) / ("dupez_" + variant) / "native-binaries.json"
            lock(stack, executable, observed["artifact"])
            lock(stack, collection, observed["manifest"])
            actual = native.inspect_native_build(artifact=executable, manifest=collection, source_root=checkout,
                                                build_venv=profile / "build-venv", python_base=args.python_base,
                                                qt_profile=PROFILE)
            require(actual == observed["observation"], "Fresh frozen native inspection differs")
            rows = json_bytes(collection.read_bytes())["binaries"]
            require(len({r["destination"] for r in rows}) == len(rows), "Duplicate native mapping")
            normalized = []
            for row in rows:
                component = native_component(row)
                require(component in components, "Mapped native component has no source inventory")
                normalized.append({"path": row["destination"], "sha256": row["sha256"], "origin": row["origin"],
                                   "source_component": component, "source_mapping_complete": False})
            mappings[variant] = {"artifact": actual["artifact"], "native_observation": actual,
                                 "native_files": sorted(normalized, key=lambda r: r["path"]),
                                 "launcher_source_component": "pyinstaller-bootloader", "runtime_executed": False}
        metadata["context/frozen-native-mapping.json"] = source.canonical_json(mappings)
        notice_record = json_bytes(add("notices/license-payload.json", profile / "notices/license-payload.json",
                                      adoption["installed_engineering_profile"]["notice_payload"]))
        require(set(notice_record["outputs"]) == {"LICENSE.txt", "SOURCE_AND_RELINK.txt", "THIRD_PARTY_NOTICES.txt"},
                "Unexpected effective notice outputs")
        for name, expected in notice_record["outputs"].items():
            add("notices/" + name, profile / "notices" / name, expected)
        for content in metadata.values():
            if content.startswith(b"{"):
                public_metadata(json_bytes(content))
        file_pins = [{"path": name, **pin} for name, (_, pin) in files.items()]
        file_pins.extend({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in metadata.items())
        receipt = {"schema": SCHEMA, "profile": PROFILE, "application_checkpoint": checkpoint,
                   "recipe_and_manifest_checkpoint": checkpoint, "all_recipe_files_match_application_checkpoint": True,
                   "supporting_evidence_scope": "Hash-bound observations supplied separately; not asserted to be files from the application checkpoint.",
                   "files": sorted(file_pins, key=lambda r: r["path"]),
                   "source_component_count": len(manifest["components"]), "source_archive_count": len(inspections),
                   "uncollected_components": source_receipt["uncollected_components"],
                   "delivery_gaps": source_receipt["delivery_gaps"],
                   "native_counts": {key: len(value["native_files"]) for key, value in mappings.items()},
                   "complete_corresponding_source": False, "native_rebuild_proven": False, "release_approved": False,
                   "distribution_approved": False, "compat_runtime_tested": False, "public_delivery_proven": False,
                   "limitations": ["Every observed native file is assigned a source component, not an attested source rebuild.",
                                   "Version-matched sources do not prove all static dependencies, patches or compiler inputs.",
                                   "Candidate-only modules and build tools remain separately inventoried; full source archives can contain unused code.",
                                   "Existing recipe and notice files are reproduced as evidence, not licensing or release approval."]}
        bundle = output / "engineering-source-inputs.zip"
        write_bundle(bundle, files, metadata, receipt)
        verification = verify_bundle(bundle, receipt)
        (output / "bundle-receipt.json").write_bytes(source.canonical_json(receipt))
        (output / "bundle-verification.json").write_bytes(source.canonical_json(verification))
        return verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("--manifest", type=Path, default=ROOT / "packaging/engineering-source-inputs.json")
    parser.add_argument("--adoption-evidence", type=Path, default=ROOT / "packaging/license-evidence/qt-6121-adoption-2026-11-24.json")
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--python-base", type=Path)
    parser.add_argument("--cache", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            require(args.bundle is not None and args.receipt is not None, "Verification requires bundle and expected receipt")
            result = verify_bundle(args.bundle, source._read_json(args.receipt))
        else:
            require(args.build_root is not None and args.python_base is not None and args.output is not None and bool(args.cache),
                    "Creation requires exact build root, Python base, caches and fresh output")
            result = assemble(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Engineering source verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
