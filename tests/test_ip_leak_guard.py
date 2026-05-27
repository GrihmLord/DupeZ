"""IP-leak guard — no raw IPv4 address may leave the process.

DupeZ handles device IP addresses, and several subsystems send data
outward where an unmasked IP would be a real opsec leak:

  * the session log files (routinely shared for support),
  * the HMAC-chained audit JSONL (bundled into shareable backups),
  * the Discord / generic audit webhook,
  * the OBS overlay HTTP endpoint (literally rendered on-stream).

Every one of those paths must mask IP addresses. This suite asserts
each egress scrubber actually masks — bare addresses AND addresses
embedded in free text — so a regression in any of them fails the
build instead of leaking.
"""

from __future__ import annotations

import logging

_RAW = "192.168.1.50"
_MASKED_PREFIX = "192.168.1."


def _leaks(value: object) -> bool:
    """True if the raw test IP survives anywhere in *value*'s repr."""
    return _RAW in str(value)


class TestLogScrubber:
    """Session-log lines must never carry a raw IP."""

    def test_scrub_log_message_masks_embedded_ip(self) -> None:
        from app.logs.logger import _scrub_log_message
        out = _scrub_log_message(f"ArpSpoofer: target={_RAW} active")
        assert not _leaks(out)
        assert "192.168.1.x" in out

    def test_scrubbing_formatter_covers_exception_path(self) -> None:
        # error()/critical() with an exception bypass _log_with_context;
        # the formatter is the net that still catches those records.
        from app.logs.logger import _ScrubbingFormatter
        rec = logging.LogRecord(
            name="t", level=logging.ERROR, pathname=__file__, lineno=1,
            msg=f"connection to {_RAW} reset", args=(), exc_info=None,
        )
        out = _ScrubbingFormatter("%(message)s").format(rec)
        assert not _leaks(out)


class TestAuditLogScrubber:
    """The on-disk audit JSONL — and therefore shareable backups — is clean."""

    def test_scrub_pii_masks_ip_under_nonstandard_key(self) -> None:
        from app.logs.audit import _scrub_pii
        # 'gateway' is not one of the known ip-key names, so only the
        # value-based masking can catch it.
        assert not _leaks(_scrub_pii({"gateway": _RAW}))

    def test_scrub_pii_masks_ip_embedded_in_string(self) -> None:
        from app.logs.audit import _scrub_pii
        assert not _leaks(_scrub_pii({"detail": f"cut on {_RAW} severed"}))


class TestWebhookScrubber:
    """Nothing posted to a Discord / generic webhook carries a raw IP."""

    def test_scrub_masks_bare_ip_value(self) -> None:
        from app.core.audit_webhook import _scrub
        assert not _leaks(_scrub({"target_ip": _RAW}))

    def test_scrub_masks_embedded_ip(self) -> None:
        from app.core.audit_webhook import _scrub
        assert not _leaks(_scrub({"detail": f"failed reaching {_RAW}"}))

    def test_scrub_masks_ip_in_list(self) -> None:
        from app.core.audit_webhook import _scrub
        assert not _leaks(_scrub({"peers": [_RAW, "ok"]}))


class TestOverlaySnapshot:
    """The OBS overlay /state endpoint is on-stream — it must mask targets."""

    def test_snapshot_masks_target_ip(self) -> None:
        from app.core.overlay_server import build_state_snapshot

        class _Engine:
            _max_cut_state = "severed"
            _packets_processed = 1
            _packets_dropped = 0

        class _Ctrl:
            disrupted_devices = {
                _RAW: {"engine": _Engine(), "methods": ["drop"],
                       "params": {}, "start_time": 0.0},
            }

        snap = build_state_snapshot(_Ctrl())
        assert not _leaks(snap)
        assert snap["active_targets"][0]["target_ip"].startswith(_MASKED_PREFIX)
