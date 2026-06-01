"""v5.7.6 security hardening — regression coverage.

Items under test:
    1. Downgrade-replay protection in update_verify / update_state
    2. HMAC sidecars on settings.json (app/config/__init__.py)
    3. Audit log fail-closed tamper response (app/logs/audit.py)
    4. Subprocess hardening (STARTUPINFO + close_fds in safe_subprocess)
    5. Webhook host allowlist (app/core/audit_webhook.py)
    6. Self-verify helper sanity (app/core/self_verify.py)
    8. Cert-pinning helpers (app/core/cert_pinning.py)

Tests use the persistence HMAC key, which is provisioned via
:mod:`app.core.secret_store`. On CI / dev hosts that lack DPAPI the
secret store falls back to a 0o600 file under the user's data
directory — both work. The basetemp pin in conftest keeps test
artifacts inside the repo's ``.pytest-tmp``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Item 1: downgrade-replay protection ─────────────────────────────

class TestDowngradeReplay:
    """app.core.update_state.enforce_monotonic_version + ledger I/O."""

    def test_compare_versions_strict_semver(self) -> None:
        from app.core.update_state import compare_versions
        assert compare_versions("5.7.6", "5.7.5") == 1
        assert compare_versions("5.7.5", "5.7.6") == -1
        assert compare_versions("5.7.5", "5.7.5") == 0
        assert compare_versions("6.0.0", "5.99.99") == 1
        # Malformed inputs collapse to 0.0.0 — never let a junk version
        # win the ordering and trick us into accepting a downgrade.
        assert compare_versions("not-a-version", "0.0.1") == -1
        assert compare_versions("0.0.1", "not-a-version") == 1

    def test_set_then_get_persists(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_set_does_not_lower_floor(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        # An attempt to lower the floor is silently ignored.
        update_state.set_last_seen_version("5.7.0")
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_enforce_raises_on_downgrade(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        with pytest.raises(update_state.DowngradeRefusedError):
            update_state.enforce_monotonic_version("5.7.5")
        # Floor unchanged.
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_enforce_accepts_equal_or_greater(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.5")
        update_state.enforce_monotonic_version("5.7.5")  # equal accepted
        update_state.enforce_monotonic_version("5.7.6")  # greater accepted
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_ledger_hmac_mismatch_resets_floor_to_zero(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """Tampered ledger → default to 0.0.0 (never silently lower)."""
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        # Corrupt the JSON body but keep the HMAC — tag won't verify.
        ledger = update_state.ledger_path()
        ledger.write_bytes(b'{"schema":"dupez.update-state.v1","last_seen_version":"99.0.0"}')
        # The HMAC sidecar still references the previous payload, so
        # verification fails and we fall back to 0.0.0.
        assert update_state.get_last_seen_version() == "0.0.0"
        # Therefore even "5.0.0" is acceptable — but the next set bumps
        # the floor again under a fresh tag.
        update_state.enforce_monotonic_version("5.0.0")
        assert update_state.get_last_seen_version() == "5.0.0"


# ── Item 2: settings.json HMAC sidecar ──────────────────────────────

class TestSettingsHmacSidecar:
    """app.config.load_config / save_config integrity."""

    def test_roundtrip_writes_sidecar(self, tmp_path: Path, monkeypatch) -> None:
        from app import config as cfg
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"k": "v", "kill_switch": True})
        assert os.path.isfile(cfg.CONFIG_PATH)
        assert os.path.isfile(cfg.HMAC_PATH)
        loaded = cfg.load_config()
        assert loaded == {"k": "v", "kill_switch": True}

    def test_tampered_payload_returns_empty_and_quarantines(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app import config as cfg
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"kill_switch": True})
        # Attacker rewrites settings.json directly.
        Path(cfg.CONFIG_PATH).write_bytes(
            json.dumps({"kill_switch": False}, indent=4, sort_keys=True).encode("utf-8")
        )
        loaded = cfg.load_config()
        assert loaded == {}, "tampered settings must be rejected"
        # The tampered file is preserved next to the original path.
        survivors = list(tmp_path.glob("settings.json.tampered.*"))
        assert survivors, "tampered file must be quarantined for forensics"

    def test_first_run_no_sidecar_migrates(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """v5.7.5 settings.json + no sidecar: load + re-sign once."""
        from app import config as cfg
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        Path(cfg.CONFIG_PATH).write_text(json.dumps({"legacy": True}))
        loaded = cfg.load_config()
        assert loaded == {"legacy": True}
        # Sidecar exists now.
        assert os.path.isfile(cfg.HMAC_PATH)
        # Subsequent load with a real sidecar still works.
        assert cfg.load_config() == {"legacy": True}


# ── Item 3: audit log fail-closed tamper response ───────────────────

class TestAuditFailClosed:
    """app.logs.audit.AuditLogger seal / refuse / reset_after_tamper."""

    def test_clean_chain_logs_normally(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("evt_a", {"x": 1})
        logger.log("evt_b", {"x": 2})
        assert not logger.is_sealed()
        valid, count, msg = logger.verify_chain()
        assert valid is True and count == 2, msg

    def test_tampered_terminal_entry_seals_logger(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger, TAMPER_SENTINEL_FILENAME
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("evt_a", {"x": 1})
        # Tamper: rewrite the audit file so the terminal hash is junk.
        path = tmp_path / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        bad = json.loads(lines[-1])
        bad["hash"] = "deadbeef" * 12  # right length, wrong value
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        # Reopen — chain resume must trip the seal.
        logger2 = AuditLogger(audit_dir=str(tmp_path))
        assert logger2.is_sealed(), "tampered terminal entry must seal"
        assert (tmp_path / TAMPER_SENTINEL_FILENAME).exists()

    def test_sealed_logger_drops_subsequent_writes(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger._seal(reason="manual test")
        # Should not raise; should not append.
        logger.log("evt_should_be_dropped", {})
        path = tmp_path / "audit.jsonl"
        # File may not exist yet, but if it does, no new line for the dropped event.
        if path.exists():
            assert "evt_should_be_dropped" not in path.read_text(encoding="utf-8")

    def test_reset_after_tamper_archives_and_unseals(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("pre_seal", {})
        logger._seal(reason="manual test")
        assert logger.is_sealed()
        quarantine = logger.reset_after_tamper()
        assert quarantine.is_dir()
        assert not logger.is_sealed()
        # New events flow again under a fresh chain.
        logger.log("post_reset", {"new": True})
        valid, count, msg = logger.verify_chain()
        assert valid is True, msg


# ── Item 4: subprocess hardening ────────────────────────────────────

class TestSubprocessHardening:
    """Verify the safe_subprocess flags actually reach subprocess.run."""

    def test_run_sets_startupinfo_and_close_fds(self, monkeypatch) -> None:
        from app.core import safe_subprocess
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            class _Done:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Done()

        monkeypatch.setattr(safe_subprocess.subprocess, "run", fake_run)
        # Use a known-good absolute path so _validate_argv passes.
        exe = sys.executable
        safe_subprocess.run(
            [exe, "-c", "pass"],
            trusted_executable=True,
            intent="test_v576",
            timeout=5,
        )
        assert captured.get("close_fds") is True, (
            "v5.7.6: subprocess.run must be called with close_fds=True"
        )
        if os.name == "nt":
            si = captured.get("startupinfo")
            assert si is not None, (
                "v5.7.6: Windows spawns must pass a STARTUPINFO with SW_HIDE"
            )

    def test_spawn_detached_uses_close_fds_true(self, monkeypatch) -> None:
        from app.core import safe_subprocess
        captured: dict = {}

        class _FakeProc:
            pid = 4242

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(safe_subprocess.subprocess, "Popen", fake_popen)
        exe = sys.executable
        pid = safe_subprocess.spawn_detached(
            [exe, "-c", "pass"],
            trusted_executable=True,
            intent="test_v576_detached",
        )
        assert pid == 4242
        assert captured.get("close_fds") is True, (
            "v5.7.6: spawn_detached must set close_fds=True on all platforms"
        )


# ── Item 5: webhook host allowlist ──────────────────────────────────

class TestWebhookHostAllowlist:
    """app.core.audit_webhook host allowlist enforcement."""

    def test_default_discord_host_accepted(self) -> None:
        from app.core.audit_webhook import _validate_webhook_url
        url = "https://discord.com/api/webhooks/123/abc"
        assert _validate_webhook_url(url) == url

    def test_loopback_http_accepted(self) -> None:
        from app.core.audit_webhook import _validate_webhook_url
        # IPv6 literals need bracket form in URIs (RFC 3986 §3.2.2).
        for url in (
            "http://127.0.0.1:8080/hook",
            "http://localhost:8080/hook",
            "http://[::1]:8080/hook",
        ):
            assert _validate_webhook_url(url) == url

    def test_off_allowlist_https_rejected(self, monkeypatch) -> None:
        from app.core import audit_webhook
        # Defeat the test-mode escape hatch for this assertion.
        monkeypatch.delenv("DUPEZ_TEST_WEBHOOK_HOSTS", raising=False)
        with pytest.raises(audit_webhook.WebhookURLError):
            audit_webhook._validate_webhook_url("https://attacker.example.com/x")

    def test_test_env_hosts_accepted(self, monkeypatch) -> None:
        from app.core.audit_webhook import _validate_webhook_url
        monkeypatch.setenv(
            "DUPEZ_TEST_WEBHOOK_HOSTS",
            "extra.example.com,another.example.com",
        )
        assert _validate_webhook_url("https://extra.example.com/x") == (
            "https://extra.example.com/x"
        )

    def test_file_scheme_still_rejected(self) -> None:
        from app.core import audit_webhook
        with pytest.raises(audit_webhook.WebhookURLError):
            audit_webhook._validate_webhook_url(
                "file:///C:/Users/Foo/secrets.enc.json"
            )


# ── Item 6: self_verify behavior on source tree ─────────────────────

class TestSelfVerify:
    """In dev mode (not frozen) verify_self returns ok=True with 'skipped'."""

    def test_dev_mode_skipped(self) -> None:
        from app.core.self_verify import verify_self
        # We're not running from a PyInstaller bundle in tests.
        ok, msg = verify_self()
        assert ok is True
        assert "skipped" in msg.lower()


# ── Item 8: cert_pinning helpers (no network) ───────────────────────

class TestCertPinningHelpers:
    """Pure-function pieces of app.core.cert_pinning."""

    def test_enforce_pin_empty_set_is_audit_only(self) -> None:
        from app.core.cert_pinning import enforce_pin
        # Empty chain → empty observed list → empty PINS map ⇒ audit-only.
        # Don't pass junk DER; that would crash spki_hash().
        enforce_pin("unconfigured.example.com", [])

    def test_enforce_pin_raises_on_mismatch(self, monkeypatch) -> None:
        from app.core import cert_pinning
        # Make a synthetic SPKI hash and put it in PINS for the host.
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"a" * 64}),
        })
        # Stub spki_hash so we don't need real DER.
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["b" * 64],
        )
        with pytest.raises(cert_pinning.PinViolation):
            cert_pinning.enforce_pin("api.github.com", [b"dummy"])

    def test_enforce_pin_accepts_match(self, monkeypatch) -> None:
        from app.core import cert_pinning
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"c" * 64}),
        })
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["c" * 64],
        )
        cert_pinning.enforce_pin("api.github.com", [b"dummy"])  # no raise

    def test_env_disable_bypasses_enforcement(self, monkeypatch) -> None:
        from app.core import cert_pinning
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"d" * 64}),
        })
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["wrong" * 12 + "1234"],
        )
        monkeypatch.setenv("DUPEZ_DISABLE_CERT_PIN", "1")
        cert_pinning.enforce_pin("api.github.com", [b"dummy"])  # no raise
