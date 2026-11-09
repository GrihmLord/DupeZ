from __future__ import annotations

import json
import hashlib
from contextlib import nullcontext

import psutil
import pytest

from scripts import verify_frozen_maintenance as maintenance


@pytest.mark.parametrize("variant,is_admin", [("GPU", True), ("Compat", False)])
def test_wrong_token_cannot_launch(variant, is_admin):
    with pytest.raises(RuntimeError, match="normal UAC"):
        maintenance._check_token(variant, is_admin)


@pytest.mark.parametrize("report", [
    {"check": "runtime-imports", "ok": False},
    {"check": "runtime-imports", "ok": 1},
    {"check": "native-tls", "ok": True, "backend": "openssl",
     "available_backends": ["schannel", "openssl"], "supports_ssl": True},
    {"check": "native-tls", "ok": True, "backend": "schannel",
     "available_backends": ["schannel"], "supports_ssl": False},
    {"check": "native-tls", "ok": True, "backend": "schannel",
     "available_backends": ["schannel"], "supports_ssl": 1},
])
def test_failed_or_ambient_tls_reports_are_rejected(tmp_path, report):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(RuntimeError, match="required successful"):
        maintenance._read_report(path, report["check"])


def test_oversized_report_is_rejected_before_json(tmp_path):
    path = tmp_path / "report.json"
    path.write_bytes(b" " * 4097)
    with pytest.raises(RuntimeError, match="bounded schema"):
        maintenance._read_report(path, "runtime-imports")


def test_report_hash_describes_the_exact_validated_bytes(tmp_path):
    path = tmp_path / "report.json"
    payload = b'{ "check": "runtime-imports", "ok": true }\r\n'
    path.write_bytes(payload)
    report, digest = maintenance._read_report(path, "runtime-imports")
    assert report == {"check": "runtime-imports", "ok": True}
    assert digest == hashlib.sha256(payload).hexdigest()


PYTHON_TLS_REPORT = {
    "check": "native-tls", "ok": True, "backend": "python-ssl",
    "qt_network": "excluded", "check_hostname": True, "verify_mode": "CERT_REQUIRED",
}
SCHANNEL_REPORT = {
    "check": "native-tls", "ok": True, "backend": "schannel",
    "available_backends": ["schannel"], "supports_ssl": True,
}


@pytest.mark.parametrize("profile,report", [
    ("legacy", SCHANNEL_REPORT), ("frozen-raster", SCHANNEL_REPORT),
    ("frozen-raster-no-qtnetwork", PYTHON_TLS_REPORT),
])
def test_explicit_profile_requires_its_own_tls_contract(tmp_path, monkeypatch, profile, report):
    monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", "ignored")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert maintenance._read_report(path, "native-tls", qt_profile=profile)[0] == report


@pytest.mark.parametrize("profile,report", [
    ("legacy", PYTHON_TLS_REPORT), ("frozen-raster", PYTHON_TLS_REPORT),
    ("frozen-raster-no-qtnetwork", SCHANNEL_REPORT),
    ("frozen-raster-no-qtnetwork", {**PYTHON_TLS_REPORT, "check_hostname": False}),
    ("frozen-raster-no-qtnetwork", {**PYTHON_TLS_REPORT, "check_hostname": 1}),
    ("frozen-raster-no-qtnetwork", {**PYTHON_TLS_REPORT, "verify_mode": "CERT_NONE"}),
    ("frozen-raster-no-qtnetwork", {**PYTHON_TLS_REPORT, "qt_network": "present"}),
    ("frozen-raster-no-qtnetwork", {**PYTHON_TLS_REPORT, "available_backends": []}),
])
def test_tls_profiles_cannot_fall_back_or_accept_relaxed_checks(tmp_path, profile, report):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(RuntimeError, match="required successful"):
        maintenance._read_report(path, "native-tls", qt_profile=profile)


def test_default_report_expectation_is_not_changed_by_inherited_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", "frozen-raster-no-qtnetwork")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(PYTHON_TLS_REPORT), encoding="utf-8")
    with pytest.raises(RuntimeError, match="required successful"):
        maintenance._read_report(path, "native-tls")


def test_unknown_profile_fails_before_inspecting_artifacts(tmp_path):
    with pytest.raises(ValueError, match="Unknown frozen Qt profile"):
        maintenance.run(executable=tmp_path / "absent.exe", expected_sha256="0" * 64,
                        variant="GPU", output_directory=tmp_path / "output", qt_profile="unknown")
    assert not (tmp_path / "output").exists()


def test_runner_binds_explicit_profile_to_both_checks_and_receipt(tmp_path, monkeypatch):
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"inert fixture; never executed")
    monkeypatch.setattr(maintenance.sys, "platform", "win32")
    monkeypatch.setattr(maintenance.validator, "_is_admin", lambda: False)
    monkeypatch.setattr(maintenance.validator, "_harden_private_directory", lambda _path: None)
    monkeypatch.setattr(maintenance.validator, "_locked_release_executable", lambda *a, **k: nullcontext())
    calls = []

    def check(_executable, _root, name, _timeout, *, qt_profile):
        calls.append((name, qt_profile))
        return {"check": name}

    monkeypatch.setattr(maintenance, "_run_check", check)
    result = maintenance.run(
        executable=executable, expected_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        variant="GPU", output_directory=tmp_path / "output", qt_profile="frozen-raster-no-qtnetwork",
    )
    assert calls == [(name, "frozen-raster-no-qtnetwork") for name in maintenance.CHECKS]
    assert result["qt_build_profile"] == "frozen-raster-no-qtnetwork"
    assert result["release_approval"] is False and result["network_tested"] is False


def test_reused_pid_is_not_a_cleanup_target(monkeypatch):
    class ReusedProcess:
        def create_time(self):
            return 2.0

        def is_running(self):
            raise AssertionError("must reject PID reuse before further access")

    monkeypatch.setattr(maintenance.psutil, "Process", lambda _pid: ReusedProcess())
    assert maintenance._alive_owned({(42, 1.0)}) == []


def test_unverifiable_pid_does_not_fall_back_to_termination(monkeypatch):
    def inaccessible(_pid):
        raise psutil.AccessDenied(pid=42)

    monkeypatch.setattr(maintenance.psutil, "Process", inaccessible)
    with pytest.raises(psutil.AccessDenied):
        maintenance._alive_owned({(42, 1.0)})
