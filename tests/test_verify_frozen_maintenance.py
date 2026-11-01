from __future__ import annotations

import json
import hashlib

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
