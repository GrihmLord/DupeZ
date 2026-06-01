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


class TestMacScrubber:
    """Defense in depth: MAC addresses scrubbed at the logger formatter."""

    _RAW_MAC = "aa:bb:cc:dd:ee:ff"
    _MASKED_PREFIX = "aa:bb:cc:**"

    def test_scrub_log_message_masks_embedded_mac(self) -> None:
        # v5.7.5: any MAC slipped past a forgotten mask_mac() call must
        # still be masked by the logger formatter.
        from app.logs.logger import _scrub_log_message
        out = _scrub_log_message(f"target MAC = {self._RAW_MAC}")
        assert self._RAW_MAC not in out
        assert self._MASKED_PREFIX in out

    def test_mask_macs_in_text_handles_dashes(self) -> None:
        from app.utils.helpers import mask_macs_in_text
        out = mask_macs_in_text("local MAC = AA-BB-CC-DD-EE-FF")
        assert "DD-EE-FF" not in out
        assert "aa-bb-cc-**-**-**" in out

    def test_mask_macs_in_text_is_idempotent(self) -> None:
        from app.utils.helpers import mask_macs_in_text
        masked_once = mask_macs_in_text(f"already {self._RAW_MAC}")
        masked_twice = mask_macs_in_text(masked_once)
        assert masked_once == masked_twice


class TestTargetProfileNetmask:
    """v5.7.5 (M2): _is_wifi_same_network now reads the real interface netmask."""

    def test_local_network_helper_returns_an_ipv4network(self) -> None:
        from app.firewall.target_profile import _local_network_for_ip
        import ipaddress
        net = _local_network_for_ip("127.0.0.1")
        assert isinstance(net, ipaddress.IPv4Network)

    def test_local_network_falls_back_to_24_for_unknown_ip(self) -> None:
        # An IP that's not on any local interface falls back to /24.
        from app.firewall.target_profile import _local_network_for_ip
        net = _local_network_for_ip("203.0.113.55")
        assert net.prefixlen == 24


class TestArpSpooferValidatesIp:
    """v5.7.5 (L2): malformed IPs are rejected at construction with ValueError."""

    def test_invalid_target_ip_raises(self) -> None:
        from app.network.arp_spoof import ArpSpoofer
        try:
            ArpSpoofer(target_ip="not-an-ip", gateway_ip="192.168.1.1")
        except ValueError as exc:
            assert "target_ip" in str(exc)
        else:
            raise AssertionError("Expected ValueError for malformed target_ip")

    def test_invalid_gateway_ip_raises(self) -> None:
        from app.network.arp_spoof import ArpSpoofer
        try:
            ArpSpoofer(target_ip="192.168.1.5", gateway_ip="lolnope")
        except ValueError as exc:
            assert "gateway_ip" in str(exc)
        else:
            raise AssertionError("Expected ValueError for malformed gateway_ip")
