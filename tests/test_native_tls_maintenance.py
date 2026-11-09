"""Exercise launcher TLS maintenance without importing Qt or launching DupeZ."""

import ast
import builtins
import importlib.util
import json
from pathlib import Path
import stat
import ssl
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher():
    source = (ROOT / "dupez.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {"sys": SimpleNamespace(platform="win32", argv=[], exit=sys.exit),
                 "qt_network_enabled": lambda: True}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "dupez-functions", "exec"), namespace)
    return namespace


@pytest.fixture
def qt(monkeypatch):
    state = SimpleNamespace(
        available=["schannel"], backend="schannel", supports=True,
        existing=None, created=[], deleted=[], error=None,
    )

    class CoreApplication:
        def __init__(self, arguments):
            state.created.append(self)
            assert arguments == ["dupez-native-tls-verifier"]

        @staticmethod
        def instance():
            return state.existing

    class SslSocket:
        def __init__(self, *args, **kwargs):
            pytest.fail("The probe must not instantiate a socket")

        @staticmethod
        def availableBackends():
            if state.error is not None:
                raise state.error
            return state.available

        @staticmethod
        def activeBackend():
            return state.backend

        @staticmethod
        def supportsSsl():
            return state.supports

    monkeypatch.setitem(sys.modules, "PyQt6", SimpleNamespace(
        QtCore=SimpleNamespace(QCoreApplication=CoreApplication),
        QtNetwork=SimpleNamespace(QSslSocket=SslSocket),
        sip=SimpleNamespace(delete=state.deleted.append),
    ))
    return state


def test_probe_observes_schannel_without_socket_renderer_or_event_loop(launcher, qt):
    assert launcher["_verify_native_tls"]() == {
        "backend": "schannel", "available_backends": ["schannel"], "supports_ssl": True,
    }
    assert qt.deleted == qt.created
    assert len(qt.created) == 1


def test_probe_does_not_delete_an_existing_core_application(launcher, qt):
    qt.existing = object()
    launcher["_verify_native_tls"]()
    assert qt.created == qt.deleted == []


@pytest.fixture
def without_qt_network(launcher, monkeypatch):
    launcher["qt_network_enabled"] = lambda: False
    discoveries = []

    def absent(name):
        discoveries.append(name)
        assert name == "PyQt6.QtNetwork"
        return None

    monkeypatch.setattr(importlib.util, "find_spec", absent)
    return discoveries


def test_no_network_profile_checks_real_python_tls_defaults_without_qt(launcher, without_qt_network, qt):
    assert launcher["_verify_native_tls"]() == {
        "backend": "python-ssl", "qt_network": "excluded",
        "check_hostname": True, "verify_mode": "CERT_REQUIRED",
    }
    assert without_qt_network == ["PyQt6.QtNetwork"]
    assert qt.created == qt.deleted == []


def test_no_network_profile_rejects_discoverable_qt_network_before_tls(
    launcher, without_qt_network, monkeypatch,
):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(ssl, "create_default_context", lambda: pytest.fail("must reject unexpected binding first"))
    with pytest.raises(RuntimeError, match="QtNetwork is present"):
        launcher["_verify_native_tls"]()


@pytest.mark.parametrize("hostname,verify_mode", [
    (False, ssl.CERT_REQUIRED), (1, ssl.CERT_REQUIRED), (True, ssl.CERT_NONE),
    (True, ssl.CERT_OPTIONAL),
])
def test_no_network_profile_rejects_unverified_python_tls_defaults(
    launcher, without_qt_network, monkeypatch, hostname, verify_mode,
):
    monkeypatch.setattr(ssl, "create_default_context", lambda: SimpleNamespace(
        check_hostname=hostname, verify_mode=verify_mode,
    ))
    with pytest.raises(RuntimeError, match="certificate verification defaults"):
        launcher["_verify_native_tls"]()


@pytest.mark.parametrize("field,value", [
    ("available", []), ("available", ["openssl"]),
    ("available", ["schannel", "openssl"]),
    ("available", ["schannel", "cert-only"]),
    ("available", ["schannel", "schannel"]),
    ("backend", ""), ("backend", "openssl"),
    ("supports", False), ("supports", 1),
])
def test_unreviewed_or_unavailable_backend_fails_and_cleans_up(launcher, qt, field, value):
    setattr(qt, field, value)
    with pytest.raises(RuntimeError, match="Schannel-only"):
        launcher["_verify_native_tls"]()
    assert qt.deleted == qt.created
    assert len(qt.created) == 1


def test_plugin_failure_still_deletes_owned_application(launcher, qt):
    qt.error = ValueError("private diagnostic path")
    with pytest.raises(ValueError):
        launcher["_verify_native_tls"]()
    assert qt.deleted == qt.created


def test_non_windows_probe_rejects_before_qt_import(launcher):
    launcher["sys"].platform = "linux"
    with pytest.raises(RuntimeError, match="requires Windows"):
        launcher["_verify_native_tls"]()


def _capture_dispatch(launcher, tmp_path):
    report = tmp_path / "native-tls.json"
    launcher["os"] = SimpleNamespace(environ={"DUPEZ_VERIFY_REPORT": str(report)})
    messages = []
    launcher["_safe_stdout"] = messages.append
    launcher["_safe_stderr"] = messages.append
    launcher["sys"].argv = ["DupeZ-GPU.exe", "--verify-native-tls"]
    return report, messages


def test_native_tls_flag_records_bounded_safe_fields(launcher, qt, tmp_path):
    report, messages = _capture_dispatch(launcher, tmp_path)
    with pytest.raises(SystemExit) as caught:
        launcher["_maybe_handle_v576_flags"]()
    assert caught.value.code == 0
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "check": "native-tls", "ok": True, "backend": "schannel",
        "available_backends": ["schannel"], "supports_ssl": True,
    }
    assert messages == ["[dupez] native TLS backend verified: schannel\n"]


def test_no_network_tls_flag_records_its_explicit_contract(
    launcher, without_qt_network, qt, tmp_path,
):
    report, messages = _capture_dispatch(launcher, tmp_path)
    with pytest.raises(SystemExit) as caught:
        launcher["_maybe_handle_v576_flags"]()
    assert caught.value.code == 0
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "check": "native-tls", "ok": True, "backend": "python-ssl",
        "qt_network": "excluded", "check_hostname": True, "verify_mode": "CERT_REQUIRED",
    }
    assert messages == ["[dupez] native TLS backend verified: python-ssl\n"]
    assert qt.created == qt.deleted == []


def test_native_tls_flag_failure_logs_only_exception_type(launcher, qt, tmp_path):
    report, messages = _capture_dispatch(launcher, tmp_path)
    qt.error = RuntimeError("C:/private/path?secret=value")
    with pytest.raises(SystemExit) as caught:
        launcher["_maybe_handle_v576_flags"]()
    assert caught.value.code == 5
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "check": "native-tls", "ok": False, "error_type": "RuntimeError",
    }
    assert messages == ["[dupez] --verify-native-tls failed: RuntimeError\n"]


def test_runtime_import_flag_report_is_unchanged(launcher, tmp_path):
    report, _ = _capture_dispatch(launcher, tmp_path)
    launcher["sys"].argv = ["DupeZ-GPU.exe", "--verify-runtime-imports"]
    launcher["_verify_runtime_imports"] = lambda: ("fixture",)
    with pytest.raises(SystemExit) as caught:
        launcher["_maybe_handle_v576_flags"]()
    assert caught.value.code == 0
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "check": "runtime-imports", "ok": True,
    }


@pytest.mark.parametrize("network_enabled", [True, False])
def test_runtime_import_probe_obeys_compiled_network_policy(launcher, monkeypatch, network_enabled):
    launcher["qt_network_enabled"] = lambda: network_enabled
    real_import = builtins.__import__
    requested = []
    pyqt = SimpleNamespace(sip=SimpleNamespace(__name__="PyQt6.sip"))
    for name in ("QtCore", "QtWidgets", "QtNetwork"):
        setattr(pyqt, name, SimpleNamespace(__name__="PyQt6." + name))

    def inert_import(name, globals=None, locals=None, fromlist=(), level=0):
        fromlist = fromlist or ()
        if name.startswith("PyQt6"):
            requested.extend(fromlist)
            if not network_enabled:
                assert "QtNetwork" not in fromlist
            return pyqt
        if name == "dupez_helper":
            return SimpleNamespace(__name__=name)
        if name.startswith("app."):
            return SimpleNamespace(**{
                member: SimpleNamespace(__name__=f"{name}.{member}") for member in fromlist
            })
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", inert_import)
    result = launcher["_verify_runtime_imports"]()
    assert ("PyQt6.QtNetwork" in result) is network_enabled
    assert ("QtNetwork" in requested) is network_enabled
    assert "PyQt6.QtWidgets" in result and "dupez_helper" in result


def test_verify_report_never_overwrites_an_existing_target(launcher, tmp_path):
    report, _ = _capture_dispatch(launcher, tmp_path)
    report.write_bytes(b"existing observation must remain intact")
    launcher["_write_verify_report"]("runtime-imports", ok=True)
    assert report.read_bytes() == b"existing observation must remain intact"


@pytest.mark.parametrize("mode,attributes", [(stat.S_IFLNK, 0), (stat.S_IFDIR, 0x400)])
def test_verify_report_rejects_link_or_reparse_parent(
    launcher, tmp_path, monkeypatch, mode, attributes,
):
    report, _ = _capture_dispatch(launcher, tmp_path)
    original = Path.lstat

    def metadata(path, *args, **kwargs):
        if path == tmp_path:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", metadata)
    launcher["_write_verify_report"]("runtime-imports", ok=True)
    assert not report.exists()


def test_verify_report_rejects_non_directory_parent(launcher, tmp_path):
    non_directory = tmp_path / "file"
    non_directory.write_bytes(b"preserved")
    launcher["os"] = SimpleNamespace(environ={
        "DUPEZ_VERIFY_REPORT": str(non_directory / "report.json"),
    })
    launcher["_write_verify_report"]("runtime-imports", ok=True)
    assert non_directory.read_bytes() == b"preserved"


def test_native_tls_import_failure_does_not_echo_exception_module_name(launcher, qt, tmp_path):
    report, _ = _capture_dispatch(launcher, tmp_path)
    qt.error = ImportError("private diagnostic", name="C:/private/path")
    with pytest.raises(SystemExit) as caught:
        launcher["_maybe_handle_v576_flags"]()
    assert caught.value.code == 5
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "check": "native-tls", "ok": False, "error_type": "ImportError",
    }


def test_flag_dispatch_remains_before_gui_bootstrap_and_python_elevation():
    source = (ROOT / "dupez.py").read_text(encoding="utf-8")
    assert source.index("_maybe_handle_v576_flags()\n") < source.index("# ── ADR-0001 manifest-flip compat shim")
    probe = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_verify_native_tls")
    body = ast.get_source_segment(source, probe)
    assert "QtWebEngine" not in body
    assert ".exec(" not in body
    assert "setActiveBackend" not in body
