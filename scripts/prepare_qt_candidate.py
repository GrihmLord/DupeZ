#!/usr/bin/env python3
"""Prepare the reviewed, isolated Qt candidate; never update production locks.

Downloads are size/hash pinned. Qt archives are inspected before extraction;
their executables/scripts are never run. Only the pinned Riverbank Python
bundler is invoked in a new venv. Runtime installation is an explicit option.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging/qt-candidate-inputs.json"
HOSTS = frozenset({"download.qt.io", "qt.mirror.constant.com", "files.pythonhosted.org"})
ROLES = frozenset({"source", "qt-prefix", "qt-helper", "builder-wheel", "binding-wheel", "runtime-wheel"})
MAX_FILE = 100 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
MODULES = frozenset({
    "QAxContainer", "QtBluetooth", "QtCore", "QtDBus", "QtDesigner", "QtGui", "QtHelp",
    "QtMultimedia", "QtMultimediaWidgets", "QtNetwork", "QtNfc", "QtOpenGL", "QtOpenGLWidgets",
    "QtPdf", "QtPdfWidgets", "QtPositioning", "QtPrintSupport", "QtQml", "QtQuick", "QtQuick3D",
    "QtQuickWidgets", "QtRemoteObjects", "QtSensors", "QtSerialPort", "QtSpatialAudio", "QtSql",
    "QtStateMachine", "QtSvg", "QtSvgWidgets", "QtTest", "QtTextToSpeech", "QtWebChannel",
    "QtWebSockets", "QtWidgets", "QtXml",
})
MANIFEST_FIELDS = frozenset({"schema", "reviewed_on", "qt_version", "binding_version", "scope",
                             "retained_bindings", "excluded_bindings", "inputs"})


def check_url(url: str) -> None:
    if any(ord(char) < 33 for char in url) or "\\" in url or "%" in url:
        raise ValueError("Encoded/control download URL is not allowed")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError("Unreviewed download URL")


class ReviewedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def safe_member(name: str) -> None:
    path = PurePosixPath(name.rstrip("/"))
    if (not name or any(ord(char) < 32 for char in name) or path.is_absolute() or "\\" in name or ":" in name
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
            or any(part.endswith((".", " ")) for part in path.parts)
            or any(re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", part, re.I)
                   for part in path.parts)):
        raise ValueError(f"Unsafe archive member: {name!r}")


def ordinary_path(path: Path, *, missing: bool = False, file: bool = False) -> Path:
    """Check unresolved ancestors so junctions cannot disappear in resolve()."""
    path = Path(os.path.abspath(path))
    for entry in [*reversed(path.parents), path]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise ValueError(f"Required path is absent: {entry}")
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Reparse path is not allowed: {entry}")
        predicate = stat.S_ISREG if entry == path and file else stat.S_ISDIR
        if not predicate(info.st_mode):
            raise ValueError(f"Unexpected path type: {entry}")
    return path


def system_directory(function_name: str = "GetSystemDirectoryW") -> Path:
    function = getattr(ctypes.WinDLL("kernel32", use_last_error=True), function_name)
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(buffer, len(buffer))
    if not 0 < length < len(buffer) or buffer.value.startswith("\\\\"):
        raise ValueError("Trusted Windows directory is unavailable")
    return ordinary_path(Path(buffer.value))


def child_environment(private: Path) -> dict[str, str]:
    system = system_directory()
    windows = system_directory("GetWindowsDirectoryW")
    profile, temp = private / "profile", private / "temp"
    for path in (profile, temp):
        ordinary_path(path, missing=True)
        path.mkdir(parents=True, exist_ok=True)
    return {"SystemRoot": str(windows), "WINDIR": str(windows), "SystemDrive": windows.drive,
            "ComSpec": str(system / "cmd.exe"), "PATH": os.pathsep.join([str(system), str(windows)]),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD", "OS": "Windows_NT",
            "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp),
            "USERPROFILE": str(profile), "HOME": str(profile), "LOCALAPPDATA": str(profile),
            "APPDATA": str(profile), "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull}


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate manifest field: {name}")
        result[name] = value
    return result


def load_manifest_snapshot(path: Path | None = None) -> tuple[dict, str]:
    path = MANIFEST if path is None else path
    ordinary_path(path, file=True)
    with path.open("rb") as source:
        raw = source.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("Oversized candidate manifest")
    manifest = json.loads(raw, object_pairs_hook=_unique_object)
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or manifest.get("schema") != "dupez.qt-candidate-inputs.v1"):
        raise ValueError("Unknown candidate manifest")
    for field in ("qt_version", "binding_version"):
        if not isinstance(manifest[field], str) or not VERSION.fullmatch(manifest[field]):
            raise ValueError(f"Non-canonical candidate version: {field}")
    if (not isinstance(manifest["reviewed_on"], str)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", manifest["reviewed_on"])
            or not isinstance(manifest["scope"], str) or not 1 <= len(manifest["scope"]) <= 1024
            or any(ord(char) < 32 for char in manifest["scope"])):
        raise ValueError("Invalid review metadata")
    for field in ("retained_bindings", "excluded_bindings"):
        names = manifest[field]
        if (not isinstance(names, list) or not names or any(not isinstance(name, str) or name not in MODULES for name in names)
                or len(set(names)) != len(names)):
            raise ValueError(f"Invalid candidate module names: {field}")
    retained, excluded = set(manifest["retained_bindings"]), set(manifest["excluded_bindings"])
    if retained & excluded or retained | excluded != MODULES or "QAxContainer" not in excluded:
        raise ValueError("Candidate module partition is incomplete or unsafe")
    if not isinstance(manifest["inputs"], list) or not 1 <= len(manifest["inputs"]) <= 32:
        raise ValueError("Invalid candidate inputs")
    seen, ids = set(), set()
    for item in manifest["inputs"]:
        if not isinstance(item, dict) or item.get("role") not in ROLES:
            raise ValueError("Invalid candidate input role")
        fields = {"id", "role", "filename", "url", "size", "sha256"}
        if item["role"] in {"qt-prefix", "qt-helper"}:
            fields |= {"members", "member_listing_sha256"}
        if item["role"] in {"builder-wheel", "binding-wheel", "runtime-wheel"}:
            fields |= {"package", "version"}
        if set(item) != fields or any(not isinstance(item[name], str) for name in fields - {"size", "members"}):
            raise ValueError("Invalid candidate input schema")
        if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", item["id"]) or item["id"] in ids:
            raise ValueError("Invalid/duplicate candidate input identity")
        ids.add(item["id"])
        if "package" in item and (not re.fullmatch(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*", item["package"])
                or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,3}", item["version"])):
            raise ValueError("Invalid candidate wheel requirement")
        if "members" in item and (type(item["members"]) is not int or not 1 <= item["members"] <= 20000
                or not re.fullmatch(r"[0-9a-f]{64}", item["member_listing_sha256"])):
            raise ValueError("Invalid candidate archive listing pin")
        safe_member(item["filename"])
        if "/" in item["filename"] or item["filename"].casefold() in seen:
            raise ValueError("Duplicate/non-flat input filename")
        seen.add(item["filename"].casefold())
        check_url(item["url"])
        if (type(item["size"]) is not int or not 0 < item["size"] <= MAX_FILE
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Invalid candidate input pin")
    if sum(item["size"] for item in manifest["inputs"]) > 256 * 1024 * 1024:
        raise ValueError("Candidate exceeds total download budget")
    bindings = [item for item in manifest["inputs"] if item["role"] == "binding-wheel"]
    if len(bindings) != 1 or bindings[0]["package"] != "PyQt6" or bindings[0]["version"] != manifest["binding_version"]:
        raise ValueError("Binding wheel does not match candidate version")
    return manifest, hashlib.sha256(raw).hexdigest()


def load_manifest(path: Path | None = None) -> dict:
    return load_manifest_snapshot(path)[0]


def verified(path: Path, item: dict) -> None:
    ordinary_path(path, file=True)
    if path.stat().st_size != item["size"]:
        raise ValueError(f"Missing/incorrect input size: {path.name}")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != item["sha256"]:
        raise ValueError(f"Input SHA256 mismatch: {path.name}")


def fetch(item: dict, destination: Path, cache: Path | None) -> None:
    cached = cache / item["filename"] if cache else None
    if cached and cached.exists():
        verified(cached, item)
        shutil.copyfile(cached, destination)
    else:
        check_url(item["url"])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ReviewedRedirects())
        with opener.open(item["url"], timeout=60) as response, destination.open("xb") as output:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > item["size"]:
                    raise ValueError("Download exceeds pinned size")
                output.write(block)
    verified(destination, item)


def inspect_7z(path: Path, item: dict, tar: Path, env: dict | None = None) -> dict[str, str]:
    listing = subprocess.run([str(tar), "-tf", str(path)], capture_output=True,
                             check=True, timeout=120, env=env).stdout.decode("utf-8").splitlines()
    digest = hashlib.sha256(("\n".join(listing) + "\n").encode()).hexdigest()
    if len(listing) != item["members"] or digest != item["member_listing_sha256"]:
        raise ValueError("Archive listing differs from reviewed input")
    seen = set()
    for name in listing:
        safe_member(name)
        key = name.rstrip("/").casefold()
        if key in seen:
            raise ValueError("Case-colliding archive member")
        seen.add(key)
    verbose = subprocess.run([str(tar), "-tvf", str(path)], capture_output=True,
                             check=True, timeout=120, env=env).stdout.decode("utf-8").splitlines()
    expanded = 0
    entries = {}
    if len(verbose) != len(listing):
        raise ValueError("Archive listing count mismatch")
    for name, line in zip(listing, verbose):
        fields = line.split(maxsplit=8)
        if len(fields) != 9 or fields[0][0] not in {"-", "d"} or not fields[4].isdigit():
            raise ValueError("Archive link, special entry or unknown listing format")
        expanded += int(fields[4])
        entries[name.rstrip("/").casefold()] = fields[0][0]
    if expanded > MAX_EXPANDED:
        raise ValueError("Archive expansion exceeds candidate bound")
    return entries


def merge_namespace(namespace: dict[str, str], entries: dict[str, str]) -> None:
    staged = dict(namespace)
    for name, kind in sorted(entries.items(), key=lambda pair: (pair[0].count("/"), pair[0])):
        if name in staged and (kind != "d" or staged[name] != "d"):
            raise ValueError(f"Qt archives overlap a non-directory member: {name}")
        parts = PurePosixPath(name).parts
        if any(staged.get("/".join(parts[:n])) == "-" for n in range(1, len(parts))):
            raise ValueError("Archive member descends through an existing file")
        if kind == "-" and any(old.startswith(name + "/") for old in staged):
            raise ValueError("Archive file replaces an existing directory namespace")
        staged[name] = kind
    namespace.update(staged)


def inspect_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if sum(member.file_size for member in archive.infolist()) > MAX_EXPANDED:
            raise ValueError("Wheel expansion exceeds candidate bound")
        seen = set()
        for member in archive.infolist():
            safe_member(member.filename)
            name = member.filename.rstrip("/").casefold()
            if name in seen:
                raise ValueError("Duplicate/case-colliding wheel member")
            seen.add(name)
            kind = (member.external_attr >> 16) & 0o170000
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError("Wheel symlinks and special entries are unsupported")


def run(argv: list[str], cwd: Path, log: Path) -> None:
    env = child_environment(log.parent / "private")
    with log.open("ab") as output:
        subprocess.run(argv, cwd=cwd, env=env, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def prepare(output: Path, cache: Path | None, download_only: bool, install_runtime: bool) -> dict:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13) or struct.calcsize("P") != 8:
        raise ValueError("Use the reviewed Windows x64 CPython 3.13 interpreter")
    output = ordinary_path(output, missing=True)
    cache = ordinary_path(cache) if cache else None
    build_root = ordinary_path(ROOT / "build", missing=True)
    if (not build_root.is_relative_to(ROOT.resolve())
            or not output.is_relative_to(build_root) or output.exists()):
        raise ValueError("Output must be a fresh directory below this checkout's build/")
    manifest, manifest_sha256 = load_manifest_snapshot()
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    for item in manifest["inputs"]:
        fetch(item, inputs / item["filename"], cache)
    receipt = {"schema": "dupez.qt-candidate-preparation.v1", "status": "inputs-verified",
               "production_locks_changed": False, "native_payload_executed": False,
               "manifest_sha256": manifest_sha256,
               "inputs": manifest["inputs"], "scope": manifest["scope"]}
    if not download_only:
        tar = ordinary_path(system_directory() / "tar.exe", file=True)
        env = child_environment(output / "private")
        prefix = output / manifest["qt_version"] / "msvc2022_64"
        prefix.mkdir(parents=True)
        namespace = {}
        for item in manifest["inputs"]:
            path = inputs / item["filename"]
            if item["role"] in {"qt-prefix", "qt-helper"}:
                merge_namespace(namespace, inspect_7z(path, item, tar, env))
                subprocess.run([str(tar), "-xf", str(path), "-C", str(prefix)], check=True, timeout=120, env=env)
            elif item["filename"].endswith(".whl"):
                inspect_wheel(path)
        for name in ("d3dcompiler_47.dll", "opengl32sw.dll"):
            shutil.copyfile(prefix / name, prefix / "bin" / name)
        qconfig = (prefix / "mkspecs/qconfig.pri").read_text(encoding="utf-8")
        qt_version = re.search(r"^QT_VERSION[ \t]*=[ \t]*([^\s]+)[ \t]*$", qconfig, re.M)
        if not qt_version or qt_version.group(1) != manifest["qt_version"]:
            raise ValueError("Installer metadata does not match declared Qt version")
        (prefix / "translations").mkdir(exist_ok=True)
        builder = output / "builder-venv"
        log = output / "prepare.log"
        run([sys.executable, "-I", "-m", "venv", str(builder)], output, log)
        python = builder / "Scripts/python.exe"
        requirements = output / "builder-requirements.txt"
        requirements.write_text("\n".join(f"{item['package']}=={item['version']} --hash=sha256:{item['sha256']}"
                               for item in manifest["inputs"] if item["role"] == "builder-wheel") + "\n")
        run([str(python), "-I", "-m", "pip", "install", "--no-index", "--no-cache-dir", "--no-deps", "--require-hashes",
             "--find-links", str(inputs), "-r", str(requirements)], output, log)
        binding = next(item for item in manifest["inputs"] if item["role"] == "binding-wheel")
        canonical = output / f"PyQt6-{manifest['binding_version']}-cp310-abi3-win_amd64.whl"
        shutil.copyfile(inputs / binding["filename"], canonical)
        wheel_dir = output / "wheel"
        wheel_dir.mkdir()
        args = [str(python), "-I", "-c", "from pyqtbuild.bundle.bundle_main import main; raise SystemExit(main())", "--qt-dir", str(prefix), "--no-msvc-runtime",
                "--no-openssl", "--build-tag-suffix", "dupezcandidate"]
        for name in manifest["excluded_bindings"]:
            args.extend(["--exclude", name])
        args.append(str(canonical))
        run(args, wheel_dir, log)
        wheel = next(wheel_dir.glob("*.whl"))
        inspect_wheel(wheel)
        with zipfile.ZipFile(wheel) as archive:
            metadata = archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))).decode()
            if re.search(r"^Requires-Dist:\s*pyqt6-qt6", metadata, re.I | re.M):
                raise ValueError("Bundler retained external Qt dependency")
        with wheel.open("rb") as source:
            wheel_hash = hashlib.file_digest(source, "sha256").hexdigest()
        receipt.update(status="candidate-wheel-prepared", wheel={"path": str(wheel.relative_to(output)),
                       "sha256": wheel_hash, "size": wheel.stat().st_size}, retained_bindings=manifest["retained_bindings"])
        if install_runtime:
            runtime = output / "runtime-venv"
            run([sys.executable, "-I", "-m", "venv", str(runtime)], output, log)
            sip = next(item for item in manifest["inputs"] if item["role"] == "runtime-wheel")
            requirements = output / "runtime-requirements.txt"
            requirements.write_text(f"{wheel} --hash=sha256:{wheel_hash}\n{inputs / sip['filename']} --hash=sha256:{sip['sha256']}\n")
            python = runtime / "Scripts/python.exe"
            run([str(python), "-I", "-m", "pip", "install", "--no-index", "--no-cache-dir", "--no-deps", "--require-hashes",
                 "-r", str(requirements)], output, log)
            run([str(python), "-I", "-m", "pip", "check"], output, log)
            receipt["runtime_venv"] = str(runtime.relative_to(output))
            receipt["pip_check"] = "passed"
    (output / "preparation-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="Optional verified input cache; read only")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--install-runtime", action="store_true", help="Create a separate candidate venv; do not run Qt")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.cache, args.download_only, args.install_runtime), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
