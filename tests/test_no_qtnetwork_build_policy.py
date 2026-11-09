"""Inert PE and archive regressions for the explicit Qt Network exclusion profile."""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from scripts import release_preflight

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("no_network_policy", ROOT / "packaging/native_runtime_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
PROFILE = policy.NO_QTNETWORK_PROFILE


@pytest.fixture
def pe_parser():
    pytest.importorskip("pefile", reason="PE directory tests require the hash-locked native build dependency")


def inert_pe(*, dependency=None, delayed=False, exported_name=None):
    """An unexecutable PE header with a genuine import/delay/export directory."""
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 132, 0x8664, 1, 0, 0, 0, 240, 0x2022)
    optional = 152
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional + 24, 0x180000000)
    struct.pack_into("<II", data, optional + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, optional + 56, 0x2000, 0x200)
    struct.pack_into("<I", data, optional + 108, 16)
    struct.pack_into("<8sIIIIIIHHI", data, optional + 240,
                     b".rdata\0\0", 0x200, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x40000040)
    name = dependency or exported_name
    if name:
        encoded = name.encode("ascii") + b"\0"
        data[0x240:0x240 + len(encoded)] = encoded
    if dependency:
        directory = 13 if delayed else 1
        struct.pack_into("<II", data, optional + 112 + 8 * directory, 0x1000, 64 if delayed else 40)
        if delayed:
            struct.pack_into("<IIIIIIII", data, 0x200, 1, 0x1040, 0, 0x1080, 0x1080, 0, 0, 0)
        else:
            struct.pack_into("<IIIII", data, 0x200, 0x1080, 0, 0, 0x1040, 0x1080)
        struct.pack_into("<Q", data, 0x280, 0x10A0)
        data[0x2A0:0x2AA] = b"\0\0Function"
    if exported_name:
        struct.pack_into("<II", data, optional + 112, 0x1000, 40)
        struct.pack_into("<IIHHIIIIIII", data, 0x200, 0, 0, 0, 0, 0x1040, 1, 1, 0, 0x1080, 0, 0)
        struct.pack_into("<I", data, 0x280, 0x1100)
    return bytes(data)


@pytest.mark.parametrize("kwargs", [
    {"dependency": "Qt6Network.dll"},
    {"dependency": "QT6NETWORK.DLL", "delayed": True},
    {"exported_name": "Qt6Network.dll"},
])
def test_actual_pe_directories_reject_network_even_when_file_is_renamed(kwargs, pe_parser):
    with pytest.raises(ValueError, match="Qt6Network identity or import"):
        policy.validate_no_qtnetwork_pe(inert_pe(**kwargs))


@pytest.mark.parametrize("kwargs", [{}, {"dependency": "kernel32.dll"}, {"dependency": "Qt6Core.dll", "delayed": True}])
def test_actual_pe_parser_accepts_unrelated_dependencies(kwargs, pe_parser):
    policy.validate_no_qtnetwork_pe(inert_pe(**kwargs))


@pytest.mark.parametrize("data", [b"", b"MZ" + b"\0" * 100])
def test_malformed_pe_fails_closed(data, pe_parser):
    with pytest.raises(ValueError, match="PE"):
        policy.validate_no_qtnetwork_pe(data)


@pytest.mark.parametrize("name", [
    "PyQt6.QtNetwork", "PyQt6/QtNetwork.cp313-win_amd64.pyd", "QtNetwork.pyi",
    "PyQt6/bindings/QtNetwork/qnetwork.sip", "Qt6Network.dll",
    "PyQt6/Qt6/plugins/tls/custombackend.dll", "qschannelbackend.dll",
    "PyQt6/Qt6/plugins/networkinformation/unknown.dll", "qtuiotouchplugin.dll",
])
def test_new_profile_rejects_all_network_payload_kinds_only_when_selected(name):
    with pytest.raises(RuntimeError, match="Excluded Qt Network"):
        policy.validate_frozen_raster_payload([name], qt_profile=PROFILE)
    policy.validate_frozen_raster_payload([name], qt_profile="frozen-raster")


def test_profile_marker_is_validated_without_running_code():
    code = compile("raise RuntimeError('must not run')\n_BUILD_QT_PROFILE = '" + PROFILE + "'", "fixture", "exec")
    embedded = SimpleNamespace(toc={"app.firewall_helper._build_default": ()}, extract=lambda _name: code)
    # The unreachable store is optimized away: absence must fail, not execute.
    with pytest.raises(ValueError):
        policy.validate_compiled_qt_profile(embedded, qt_profile=PROFILE)
    code = compile("_BUILD_QT_PROFILE = '" + PROFILE + "'\nraise RuntimeError('must not run')", "fixture", "exec")
    policy.validate_compiled_qt_profile(embedded, qt_profile=PROFILE)
    for profile in ("legacy", "frozen-raster"):
        with pytest.raises(ValueError, match="differs"):
            policy.validate_compiled_qt_profile(embedded, qt_profile=profile)


@pytest.mark.parametrize("source", ["", "_BUILD_QT_PROFILE = 'legacy'", "_BUILD_QT_PROFILE = str('frozen-raster-no-qtnetwork')",
                                     "_BUILD_QT_PROFILE = 'frozen-raster-no-qtnetwork'\n_BUILD_QT_PROFILE = 'legacy'"])
def test_profile_marker_cannot_be_missing_dynamic_duplicated_or_downgraded(source):
    embedded = SimpleNamespace(toc={"app.firewall_helper._build_default": ()},
                               extract=lambda _name: compile(source, "fixture", "exec"))
    with pytest.raises(ValueError):
        policy.validate_compiled_qt_profile(embedded, qt_profile=PROFILE)


def test_build_default_and_hidden_imports_are_profile_bound(tmp_path):
    tree = ast.parse((ROOT / "packaging/build_common.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if (isinstance(node, ast.FunctionDef) and node.name in {"_write_build_default", "_hidden_imports"})
                or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_BUILD_DEFAULT_TEMPLATE" for t in node.targets))]
    output = tmp_path / "_build_default.py"
    namespace = {"os": os, "_BUILD_DEFAULT_MODULE": str(output), "validate_qt_build_profile": policy.validate_qt_build_profile,
                 "FROZEN_BROWSER_EXCLUDES": policy.FROZEN_BROWSER_EXCLUDES, "FROZEN_QTNETWORK_EXCLUDES": policy.FROZEN_QTNETWORK_EXCLUDES,
                 "NO_QTNETWORK_PROFILE": PROFILE, "collect_submodules": lambda _package, filter: [name for name in
                     ["app.gui.map_host.host", "app.gui.map_host.launcher", "app.gui.lazy_dayz_map"] if filter(name)]}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "build-functions", "exec"), namespace)
    namespace["_write_build_default"]("gpu", qt_profile=PROFILE)
    assert f"_BUILD_QT_PROFILE = {PROFILE!r}" in output.read_text()
    original = output.read_bytes()
    with pytest.raises(ValueError):
        namespace["_write_build_default"]("gpu", qt_profile="unknown")
    assert output.read_bytes() == original
    imports = namespace["_hidden_imports"](qt_profile=PROFILE)
    assert "PyQt6.QtNetwork" not in imports
    assert "app.gui.map_host.launcher" in imports
    assert "PyQt6.QtNetwork" in namespace["_hidden_imports"]()


def test_no_network_tls_policy_keeps_canonical_python_pair_and_does_not_need_qt_plugin(tmp_path, pe_parser):
    base, qt = tmp_path / "python", tmp_path / "absent-qt"
    (base / "DLLs").mkdir(parents=True)
    rows = []
    for name in ("libssl-3.dll", "libcrypto-3.dll"):
        source = base / "DLLs" / name
        source.write_bytes(inert_pe())
        rows.append((name, str(source), "BINARY"))
    assert policy.validate_windows_tls_binaries(rows, python_base=base, qt_root=qt, qt_profile=PROFILE) == rows
    with pytest.raises(RuntimeError, match="missing.*pair"):
        policy.validate_windows_tls_binaries(rows[:1], python_base=base, qt_root=qt, qt_profile=PROFILE)
    bad = base / "unexpected.dll"
    bad.write_bytes(inert_pe(dependency="Qt6Network.dll"))
    with pytest.raises(ValueError, match="Qt6Network"):
        policy.validate_windows_tls_binaries([*rows, ("ordinary.dll", str(bad), "BINARY")], python_base=base, qt_root=qt, qt_profile=PROFILE)


@pytest.mark.parametrize("mutation", [None, "missing", "extra", "renamed", "hash", "size"])
def test_system_runtime_exact_pins_reject_inventory_and_byte_drift(tmp_path, mutation):
    names = ("MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll")
    pins = [{"name": name, "size": 5, "sha256": hashlib.sha256(b"bytes").hexdigest()} for name in names]
    manifest = tmp_path / "msvc.json"
    manifest.write_text(json.dumps({"schema": "dupez.msvc-redist-inputs.v1", "binaries": pins}))
    rows = [{"destination": pin["name"], "size": pin["size"], "sha256": pin["sha256"], "origin": "windows-system32"} for pin in pins]
    if mutation == "missing": rows.pop()
    if mutation == "extra": rows.append(dict(rows[0], destination="other.dll"))
    if mutation == "renamed": rows[0]["destination"] = "other.dll"
    if mutation == "hash": rows[0]["sha256"] = "0" * 64
    if mutation == "size": rows[0]["size"] = 6
    if mutation:
        with pytest.raises(ValueError, match="System32"):
            policy.validate_msvc_redist_rows(rows, manifest)
    else:
        assert policy.validate_msvc_redist_rows(rows, manifest) == hashlib.sha256(manifest.read_bytes()).hexdigest()


@pytest.mark.parametrize("requested", ["legacy", "frozen-raster", PROFILE])
def test_final_archive_profile_binding_and_real_native_import_scan(tmp_path, requested, pe_parser):
    data = inert_pe()
    payloads = {name: data for name in ("libssl-3.dll", "libcrypto-3.dll")}
    artifact = tmp_path / "DupeZ.exe"
    artifact.write_bytes(b"inert-archive-fixture")

    class Archive:
        toc = {"PYZ.pyz": (), **{name: (0, len(data), len(data), 0, "b") for name in payloads}}

        def __init__(self, _filename): pass
        def open_embedded_archive(self, _name):
            return SimpleNamespace(toc={"app.firewall_helper._build_default": ()}, extract=lambda _key:
                                   compile(f"_BUILD_QT_PROFILE = {PROFILE!r}", "fixture", "exec"))
        def extract(self, name): return payloads[name]

    options = dict(archive_reader_cls=Archive, release_data_names=set(), release_binary_expectations={}, qt_profile=requested)
    errors = release_preflight._check_frozen_dependency_policy([artifact], **options)
    if requested != PROFILE:
        assert any("differs from requested" in error for error in errors)
    else:
        assert errors == []
        payloads["renamed.pyd"] = inert_pe(dependency="Qt6Network.dll", delayed=True)
        Archive.toc["renamed.pyd"] = (0, 1024, 1024, 0, "b")
        errors = release_preflight._check_frozen_dependency_policy([artifact], **options)
        assert any("Qt6Network identity or import" in error for error in errors)
