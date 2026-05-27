"""Security regression tests for the v5.7.3 hardening pass.

Each test corresponds to one finding from the security review of the
modules added between v5.6.9 and v5.7.2 (which post-dated the original
nation-state cert sweep). These lock the fixes so the holes cannot
silently reopen.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest


# ── Finding 1 (CRITICAL): backup restore path allowlist ──────────────


class TestBackupRestorePathAllowlist:
    """A malicious bundle must not be able to overwrite source code."""

    def _make_bundle(self, tmp_path: Path, entry_path: str,
                     payload: bytes) -> Path:
        """Hand-craft a bundle with a single arbitrary-path entry."""
        from app.core.backup import BUNDLE_SCHEMA, _hash_bytes
        bundle = tmp_path / "evil.zip"
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": "2026-05-13T00:00:00Z",
            "app_version": "evil",
            "encrypted": False,
            "entries": [{
                "path": entry_path,
                "size": len(payload),
                "sha256": _hash_bytes(payload),
            }],
        }
        with zipfile.ZipFile(bundle, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr(f"files/{entry_path}", payload)
        return bundle

    def test_refuses_to_restore_source_code(self, tmp_path: Path,
                                            monkeypatch) -> None:
        # Craft a bundle that tries to overwrite app/core/backup.py.
        from app.core import backup as backup_mod
        fake_root = tmp_path / "repo"
        (fake_root / "app" / "core").mkdir(parents=True)
        original = b"# legitimate source code\n"
        (fake_root / "app" / "core" / "backup.py").write_bytes(original)
        monkeypatch.setattr(backup_mod, "_repo_root", lambda: fake_root)

        evil = self._make_bundle(
            tmp_path, "app/core/backup.py", b"# MALICIOUS CODE\n"
        )
        result = backup_mod.restore_backup(evil)

        # The malicious entry must be SKIPPED, not restored.
        assert "app/core/backup.py" in result.skipped
        assert "app/core/backup.py" not in result.restored
        # The real source file must be untouched.
        assert (fake_root / "app" / "core" / "backup.py").read_bytes() == original

    def test_refuses_to_restore_root_entry_point(self, tmp_path: Path,
                                                 monkeypatch) -> None:
        from app.core import backup as backup_mod
        fake_root = tmp_path / "repo"
        fake_root.mkdir(parents=True)
        (fake_root / "dupez.py").write_bytes(b"# real launcher\n")
        monkeypatch.setattr(backup_mod, "_repo_root", lambda: fake_root)

        evil = self._make_bundle(tmp_path, "dupez.py", b"# pwned\n")
        result = backup_mod.restore_backup(evil)
        assert "dupez.py" in result.skipped
        assert (fake_root / "dupez.py").read_bytes() == b"# real launcher\n"

    def test_allows_legitimate_data_path(self, tmp_path: Path,
                                         monkeypatch) -> None:
        # app/data/ entries ARE on the allowlist and should restore.
        from app.core import backup as backup_mod
        fake_root = tmp_path / "repo"
        (fake_root / "app" / "data").mkdir(parents=True)
        monkeypatch.setattr(backup_mod, "_repo_root", lambda: fake_root)

        good = self._make_bundle(
            tmp_path, "app/data/settings.json", b'{"ok": true}'
        )
        result = backup_mod.restore_backup(good)
        assert "app/data/settings.json" in result.restored
        assert (fake_root / "app" / "data" / "settings.json").exists()


# ── Finding 2: overlay server has no wildcard CORS ───────────────────


class TestOverlayNoCORSWildcard:
    """The /state endpoint must not be readable cross-origin."""

    def test_no_wildcard_cors_header(self) -> None:
        import urllib.request
        from app.core.overlay_server import OverlayServer

        class FakeController:
            disrupted_devices: dict = {}

        srv = OverlayServer(FakeController(), host="127.0.0.1", port=0)
        srv.start()
        port = srv._server.server_address[1]  # type: ignore
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/state", timeout=2.0
            )
            # No Access-Control-Allow-Origin header at all.
            assert resp.headers.get("Access-Control-Allow-Origin") is None, (
                "overlay /state must not send a CORS grant — a wildcard "
                "would let any website the operator visits read their "
                "live disruption state"
            )
            # nosniff present (defense vs MIME confusion).
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        finally:
            srv.stop()


# ── Finding 3: webhook URL scheme validation ─────────────────────────


class TestWebhookURLValidation:
    """file:// and other dangerous schemes must be rejected."""

    def test_https_url_accepted(self) -> None:
        from app.core.audit_webhook import GenericWebhookSink
        s = GenericWebhookSink("https://example.com/hook")
        assert s.url == "https://example.com/hook"

    def test_http_localhost_accepted(self) -> None:
        from app.core.audit_webhook import GenericWebhookSink
        # http allowed ONLY for loopback.
        s = GenericWebhookSink("http://127.0.0.1:9999/relay")
        assert "127.0.0.1" in s.url

    def test_http_remote_rejected(self) -> None:
        from app.core.audit_webhook import GenericWebhookSink, WebhookURLError
        with pytest.raises(WebhookURLError, match="scheme"):
            GenericWebhookSink("http://evil.example.com/hook")

    def test_file_scheme_rejected(self) -> None:
        from app.core.audit_webhook import DiscordWebhookSink, WebhookURLError
        with pytest.raises(WebhookURLError, match="file://|scheme"):
            DiscordWebhookSink("file:///C:/Users/Owner/secrets.enc.json")

    def test_ftp_scheme_rejected(self) -> None:
        from app.core.audit_webhook import GenericWebhookSink, WebhookURLError
        with pytest.raises(WebhookURLError):
            GenericWebhookSink("ftp://example.com/exfil")

    def test_empty_url_rejected(self) -> None:
        from app.core.audit_webhook import GenericWebhookSink, WebhookURLError
        with pytest.raises(WebhookURLError, match="empty"):
            GenericWebhookSink("")


# ── Finding 4: preset params underscore-key whitelist ────────────────


class TestPresetUnderscoreKeyAllowlist:
    """A shared preset must not be able to inject engine control flags."""

    def test_rogue_underscore_key_rejected(self) -> None:
        from app.core.preset_store import CustomPreset, validate_preset, \
            PresetValidationError
        # _network_local is an engine control flag — a preset must not
        # be able to set it.
        p = CustomPreset(
            name="Malicious", methods=["drop"],
            params={"_network_local": True},
        )
        with pytest.raises(PresetValidationError, match="engine-internal"):
            validate_preset(p)

    def test_force_arp_spoof_injection_rejected(self) -> None:
        from app.core.preset_store import CustomPreset, validate_preset, \
            PresetValidationError
        p = CustomPreset(
            name="Sneaky", methods=["drop"],
            params={"_force_arp_spoof": True},
        )
        with pytest.raises(PresetValidationError, match="engine-internal"):
            validate_preset(p)

    def test_allowed_underscore_keys_pass(self) -> None:
        from app.core.preset_store import CustomPreset, validate_preset
        # _ports and _process_scope ARE legitimate preset features.
        p = CustomPreset(
            name="Legit", methods=["drop"],
            params={"_ports": [2302], "_process_scope": "auto"},
        )
        validate_preset(p)  # must not raise

    def test_plain_params_unaffected(self) -> None:
        from app.core.preset_store import CustomPreset, validate_preset
        # Non-underscore tuning params are never touched by the gate.
        p = CustomPreset(
            name="Tuned", methods=["drop", "lag"],
            params={"drop_chance": 100, "lag_delay": 3000,
                    "direction": "both"},
        )
        validate_preset(p)

    def test_oversized_params_rejected(self) -> None:
        from app.core.preset_store import CustomPreset, validate_preset, \
            PresetValidationError
        # A megabyte of junk in params is corruption or a DoS attempt.
        huge = {f"k{i}": "x" * 100 for i in range(500)}
        huge["direction"] = "both"
        p = CustomPreset(name="Bloated", methods=["drop"], params=huge)
        with pytest.raises(PresetValidationError, match="too large"):
            validate_preset(p)
