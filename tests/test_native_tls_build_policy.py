"""Renderer-free provenance checks for the frozen Windows TLS payload."""

from __future__ import annotations

import ctypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("native_runtime_policy", ROOT / "packaging/native_runtime_policy.py")
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)


@pytest.fixture
def payload(tmp_path):
    python_base = tmp_path / "python"
    qt_root = tmp_path / "site-packages/PyQt6/Qt6"
    sources = [
        python_base / "DLLs/libssl-3.dll", python_base / "DLLs/libcrypto-3.dll",
        qt_root / "plugins/tls/qschannelbackend.dll",
    ]
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"fixture-not-a-native-library")
    binaries = [("libssl-3.dll", str(sources[0]), "BINARY"),
                ("libcrypto-3.dll", str(sources[1]), "BINARY"),
                ("PyQt6/Qt6/plugins/tls/qschannelbackend.dll", str(sources[2]), "BINARY")]
    return SimpleNamespace(python_base=python_base, qt_root=qt_root, binaries=binaries)


def _validate(payload, binaries):
    return policy.validate_windows_tls_binaries(binaries, python_base=payload.python_base, qt_root=payload.qt_root)


def test_keeps_canonical_python_tls_and_cryptography_extension(payload):
    extension = ("cryptography/hazmat/bindings/_rust.pyd", "fixture-rust.pyd", "BINARY")
    binaries = [*payload.binaries, extension]
    assert _validate(payload, binaries) == binaries


@pytest.mark.parametrize("name", ["qopensslbackend.dll", "qcertonlybackend.dll"])
def test_removes_unused_qt_tls_plugins_at_expected_layout(payload, name):
    entry = (f"PyQt6/Qt6/plugins/tls/{name}", f"fixture-{name}", "BINARY")
    assert _validate(payload, [*payload.binaries, entry]) == payload.binaries


@pytest.mark.parametrize("destination", [
    "libssl-3-x64.dll", "libcrypto-3-x64.dll", "PyQt6/Qt6/bin/libssl-3.dll",
    "libssl-1_1-x64.dll", "libcrypto-other.dll", "unexpected/qopensslbackend.dll",
    "PyQt6/Qt6/plugins/tls/custombackend.dll",
])
def test_rejects_unreviewed_openssl_and_tls_payloads(payload, destination):
    with pytest.raises(RuntimeError, match="Unreviewed|unreviewed"):
        _validate(payload, [*payload.binaries, (destination, "ambient-library", "BINARY")])


@pytest.mark.parametrize("index", [0, 1, 2])
def test_same_name_from_ambient_directory_is_not_accepted(payload, tmp_path, index):
    binaries = list(payload.binaries)
    destination, _, kind = binaries[index]
    ambient = tmp_path / "ambient" / Path(destination).name
    ambient.parent.mkdir()
    ambient.write_bytes(b"fixture-not-a-native-library")
    binaries[index] = (destination, str(ambient), kind)
    with pytest.raises(RuntimeError, match="outside|Unreviewed"):
        _validate(payload, binaries)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_missing_required_tls_dependency_fails_closed(payload, index):
    binaries = [entry for position, entry in enumerate(payload.binaries) if position != index]
    with pytest.raises(RuntimeError, match="missing"):
        _validate(payload, binaries)


def test_network_hook_filter_preserves_normal_dependencies_and_schannel():
    expected = [("Qt6Network.dll", "PyQt6/Qt6/bin"),
                ("qschannelbackend.dll", "PyQt6/Qt6/plugins/tls")]
    inputs = [*expected,
              ("qopensslbackend.dll", "PyQt6/Qt6/plugins/tls"),
              ("qcertonlybackend.dll", "PyQt6/Qt6/plugins/tls")]
    assert policy.filter_qt_network_hook_binaries(inputs) == expected


def test_network_hook_rejects_unreviewed_backend():
    with pytest.raises(RuntimeError, match="Unreviewed"):
        policy.filter_qt_network_hook_binaries([("custombackend.dll", "PyQt6/Qt6/plugins/tls")])


def test_analysis_path_does_not_inherit_unrelated_native_tool_directories(tmp_path, monkeypatch):
    scripts = tmp_path / "venv/Scripts"
    python_base = tmp_path / "python"
    system32 = tmp_path / "Windows/System32"
    for directory in (scripts, python_base / "DLLs", system32):
        directory.mkdir(parents=True)
    environment = {"PATH": "C:/ambient/poppler;C:/unrelated/openssl", "QT_PLUGIN_PATH": "C:/foreign",
                   "QtWebEngineProcess_Path": "C:/foreign/process.exe", "QML2_IMPORT_PATH": "C:/foreign",
                   "UNCHANGED": "fixture"}

    def get_system_directory(buffer, size):
        buffer.value = str(system32)
        return len(buffer.value)

    function = Mock(side_effect=get_system_directory)
    monkeypatch.setattr(policy, "ctypes", SimpleNamespace(
        create_unicode_buffer=ctypes.create_unicode_buffer, c_wchar_p=ctypes.c_wchar_p,
        c_uint=ctypes.c_uint, WinDLL=lambda *args, **kwargs: SimpleNamespace(GetSystemDirectoryW=function),
    ))
    monkeypatch.setattr(policy, "sys", SimpleNamespace(platform="win32", executable=str(scripts / "python.exe"), base_prefix=str(python_base)))
    monkeypatch.setattr(policy, "os", SimpleNamespace(environ=environment, pathsep=";"))
    policy.configure_windows_analysis_environment()
    assert environment == {"PATH": ";".join(map(str, (scripts, python_base, python_base / "DLLs", system32))), "UNCHANGED": "fixture"}


def test_hook_and_shared_factory_apply_policy_before_analysis_and_after_collection():
    hook = (ROOT / "packaging/hooks/hook-PyQt6.QtNetwork.py").read_text(encoding="utf-8")
    source = (ROOT / "packaging/build_common.py").read_text(encoding="utf-8")
    assert "binaries = filter_qt_network_hook_binaries(binaries)" in hook
    assert "binaries += pyqt6_library_info.collect_qtnetwork_files()" not in hook
    assert source.index("configure_windows_analysis_environment()") < source.index("a = Analysis(")
    assert 'hookspath=[os.path.join(HERE, "hooks")]' in source
    assert source.index("a.binaries = validate_windows_tls_binaries(") > source.index("a = Analysis(")
    assert "native_evidence = audit_native_binary_origins(" in source


def test_native_origin_audit_hashes_only_explicit_roots_and_exact_managed_files(tmp_path):
    root = tmp_path / "venv"
    root.mkdir()
    trusted = root / "native.pyd"
    trusted.write_bytes(b"trusted fixture")
    managed = tmp_path / "snapshot/driver.sys"
    managed.parent.mkdir()
    managed.write_bytes(b"managed fixture")
    entries = [("native.pyd", str(trusted), "EXTENSION"), ("app/firewall/driver.sys", str(managed), "BINARY")]
    report = policy.audit_native_binary_origins(entries, approved_roots={"locked-venv": root}, managed_sources=[managed])
    assert {row["origin"] for row in report} == {"locked-venv", "managed-native"}
    assert all(len(row["sha256"]) == 64 for row in report)


@pytest.mark.parametrize("ambient_name", ["poppler/icuuc.dll", "libheif/ucrtbase.dll", "other/normal.pyd", "venv-lookalike/Qt6Core.dll"])
def test_native_origin_audit_rejects_all_ambient_dlls_not_only_openssl(tmp_path, ambient_name):
    root = tmp_path / "venv"
    root.mkdir()
    ambient = tmp_path / ambient_name
    ambient.parent.mkdir()
    ambient.write_bytes(b"ambient fixture")
    with pytest.raises(RuntimeError, match="ambient native dependency"):
        policy.audit_native_binary_origins([(ambient.name, str(ambient), "BINARY")], approved_roots={"locked-venv": root}, managed_sources=[])


def test_neighbor_of_managed_snapshot_is_not_implicitly_approved(tmp_path):
    managed = tmp_path / "snapshot/driver.sys"
    managed.parent.mkdir()
    managed.write_bytes(b"managed fixture")
    neighbor = managed.with_name("unmanaged.dll")
    neighbor.write_bytes(b"unmanaged fixture")
    with pytest.raises(RuntimeError, match="ambient native dependency"):
        policy.audit_native_binary_origins([(neighbor.name, str(neighbor), "BINARY")], approved_roots={}, managed_sources=[managed])


def test_source_preflight_requires_native_collection_guards(monkeypatch):
    from scripts import release_preflight

    assert release_preflight._check_native_collection_policy() == []
    original_read = release_preflight._read
    monkeypatch.setattr(release_preflight, "_read", lambda relative: original_read(relative).replace("native_evidence = audit_native_binary_origins(", "native_evidence = unchecked_origins("))
    assert any("audit_native_binary_origins" in error for error in release_preflight._check_native_collection_policy())


@pytest.mark.parametrize("forbidden", [
    "PyQt6/Qt6/plugins/tls/qopensslbackend.dll",
    "PyQt6/Qt6/plugins/tls/qcertonlybackend.dll", "libssl-3-x64.dll", "libcrypto-3-x64.dll",
])
def test_frozen_archive_preflight_rejects_out_of_policy_tls_payloads(tmp_path, forbidden):
    from scripts import release_preflight

    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"not-an-executable-fixture")

    class FakeArchive:
        toc = {"PYZ.pyz": (), forbidden: ()}

        def __init__(self, path):
            pass

        def open_embedded_archive(self, name):
            return SimpleNamespace(toc={"app.core": ()})

    errors = release_preflight._check_frozen_dependency_policy([artifact], archive_reader_cls=FakeArchive, release_data_names=set(), release_binary_expectations={})
    assert any("forbidden frozen native payload" in error for error in errors)
