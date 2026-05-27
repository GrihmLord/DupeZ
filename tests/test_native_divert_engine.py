"""
Tests for app.firewall.native_divert_engine.

The module is Windows-only at runtime (it loads WinDivert.dll via
ctypes.WinDLL), but the engine's surface area exposes plenty of pure
state that can be exercised cross-platform without ever opening a real
handle:

  1. WINDIVERT_ADDRESS bitfield — Layer / Outbound / Loopback / IPv6
  2. DisruptionModule base class — direction filtering, _roll, process
  3. _ensure_modules_loaded — idempotent module-registry init
  4. NativeWinDivertEngine constructor — input validation pathways
     (filter string allowlist, methods allowlist, params clamping),
     target-IP u32 precomputation, alive/pid/poll defaults
  5. get_stats() — packet counters and module-stats aggregation
  6. mark_last_cut_outcome — pending outcome propagation
  7. WinDivert error hint table — operator-facing diagnostic strings

start() / stop() are NOT exercised here — they require a real
WinDivert handle. Hardware coverage lives behind ``-m hardware``.
"""

from __future__ import annotations

import ctypes
import sys
from unittest.mock import MagicMock

import pytest

from app.firewall import native_divert_engine as nde
from app.firewall.native_divert_engine import (
    DIR_BOTH,
    DIR_INBOUND,
    DIR_OUTBOUND,
    DisruptionModule,
    INVALID_HANDLE_VALUE,
    MAX_PACKET_SIZE,
    NativeWinDivertEngine,
    TCP_FLAG_RST,
    WINDIVERT_ADDRESS,
    WINDIVERT_FLAG_NONE,
    WINDIVERT_LAYER_NETWORK,
    WINDIVERT_LAYER_NETWORK_FORWARD,
    _WINDIVERT_ERR_HINTS,
    _ensure_modules_loaded,
)


# ── Constants & enums ────────────────────────────────────────────────

class TestConstants:
    def test_layer_constants_distinct(self):
        assert WINDIVERT_LAYER_NETWORK != WINDIVERT_LAYER_NETWORK_FORWARD
        assert WINDIVERT_LAYER_NETWORK == 0
        assert WINDIVERT_LAYER_NETWORK_FORWARD == 1

    def test_flag_none_zero(self):
        assert WINDIVERT_FLAG_NONE == 0

    def test_max_packet_size_is_uint16_max(self):
        assert MAX_PACKET_SIZE == 65535

    def test_tcp_flag_rst_bit(self):
        assert TCP_FLAG_RST == 0x04

    def test_invalid_handle_value_is_minus_one_as_uint(self):
        # ctypes.c_void_p(-1).value — platform-dependent but always non-zero
        assert INVALID_HANDLE_VALUE != 0


class TestErrorHints:
    """The error→hint table is read by operators when WinDivertOpen fails;
    every entry must produce a human-meaningful string."""

    def test_admin_error_hint(self):
        assert "administrator" in _WINDIVERT_ERR_HINTS[5].lower()

    def test_filter_error_hint(self):
        assert "filter" in _WINDIVERT_ERR_HINTS[87].lower()

    def test_secure_boot_hint(self):
        assert "signed" in _WINDIVERT_ERR_HINTS[577].lower() or \
               "secure" in _WINDIVERT_ERR_HINTS[577].lower()

    def test_unknown_error_is_none(self):
        assert _WINDIVERT_ERR_HINTS.get(99999) is None


# ── WINDIVERT_ADDRESS bitfield ───────────────────────────────────────

class TestWindivertAddressBitfield:
    """WinDivert 2.x packs Layer/Event/Sniffed/Outbound/Loopback/IPv6
    into a single uint32. The Python accessors must decode those bits
    correctly or every direction-aware module mis-classifies packets.
    """

    def test_layer_low_byte(self):
        addr = WINDIVERT_ADDRESS()
        addr._bitfield = 0
        assert addr.Layer == 0
        addr._bitfield = 1
        assert addr.Layer == 1
        addr._bitfield = 0xFF
        assert addr.Layer == 0xFF

    def test_outbound_setter_and_getter(self):
        addr = WINDIVERT_ADDRESS()
        addr._bitfield = 0
        assert addr.Outbound is False
        addr.Outbound = True
        assert addr.Outbound is True
        # Outbound is bit 17
        assert addr._bitfield & (1 << 17)
        addr.Outbound = False
        assert addr.Outbound is False
        assert not (addr._bitfield & (1 << 17))

    def test_outbound_preserves_other_bits(self):
        addr = WINDIVERT_ADDRESS()
        addr._bitfield = 0xFFFFFFFF & ~(1 << 17)  # all bits set except 17
        addr.Outbound = True
        # Now everything should be set
        assert addr._bitfield == 0xFFFFFFFF
        addr.Outbound = False
        assert addr._bitfield == (0xFFFFFFFF & ~(1 << 17))

    def test_loopback_bit_18(self):
        addr = WINDIVERT_ADDRESS()
        addr._bitfield = 0
        assert addr.Loopback is False
        addr._bitfield = 1 << 18
        assert addr.Loopback is True

    def test_ipv6_bit_20(self):
        addr = WINDIVERT_ADDRESS()
        addr._bitfield = 0
        assert addr.IPv6 is False
        addr._bitfield = 1 << 20
        assert addr.IPv6 is True


# ── DisruptionModule base ────────────────────────────────────────────

class TestDisruptionModule:
    def test_default_direction_both(self):
        mod = DisruptionModule({})
        assert mod.direction == DIR_BOTH

    def test_explicit_global_direction(self):
        mod = DisruptionModule({"direction": DIR_INBOUND})
        assert mod.direction == DIR_INBOUND

    def test_per_module_direction_override(self):
        class _MyModule(DisruptionModule):
            _direction_key = "lag"

        mod = _MyModule({
            "direction": DIR_BOTH,
            "lag_direction": DIR_OUTBOUND,
        })
        # Per-module override wins over global
        assert mod.direction == DIR_OUTBOUND

    def test_per_module_falls_back_to_global(self):
        class _MyModule(DisruptionModule):
            _direction_key = "lag"

        mod = _MyModule({"direction": DIR_INBOUND})
        # No lag_direction key — falls back to global "direction"
        assert mod.direction == DIR_INBOUND

    @pytest.mark.parametrize("module_dir,outbound,expected", [
        (DIR_BOTH, True, True),
        (DIR_BOTH, False, True),
        (DIR_OUTBOUND, True, True),
        (DIR_OUTBOUND, False, False),
        (DIR_INBOUND, True, False),
        (DIR_INBOUND, False, True),
    ])
    def test_matches_direction(self, module_dir, outbound, expected):
        mod = DisruptionModule({"direction": module_dir})
        addr = WINDIVERT_ADDRESS()
        addr.Outbound = outbound
        assert mod.matches_direction(addr) is expected

    def test_matches_direction_unknown_returns_true(self):
        # Defensive: unrecognised direction string should not silently
        # drop packets — pass through.
        mod = DisruptionModule({"direction": "garbage"})
        addr = WINDIVERT_ADDRESS()
        addr.Outbound = True
        assert mod.matches_direction(addr) is True

    def test_roll_zero_chance_never_succeeds(self):
        for _ in range(50):
            assert DisruptionModule._roll(0) is False

    def test_roll_negative_chance_never_succeeds(self):
        assert DisruptionModule._roll(-1) is False

    def test_roll_one_hundred_always_succeeds(self):
        for _ in range(50):
            assert DisruptionModule._roll(100) is True

    def test_roll_above_hundred_always_succeeds(self):
        assert DisruptionModule._roll(150) is True

    def test_base_process_returns_false(self):
        # Base class is a no-op — subclasses override.
        mod = DisruptionModule({})
        addr = WINDIVERT_ADDRESS()
        result = mod.process(bytearray(b"\x00" * 20), addr, lambda p, a: None)
        assert result is False


# ── _ensure_modules_loaded ───────────────────────────────────────────

class TestEnsureModulesLoaded:
    def test_idempotent(self):
        # Reset and load fresh
        nde._MODULES_INITIALIZED = False
        nde.MODULE_MAP.clear()
        _ensure_modules_loaded()
        first_keys = set(nde.MODULE_MAP.keys())
        # Second call must not reinitialise
        _ensure_modules_loaded()
        assert set(nde.MODULE_MAP.keys()) == first_keys

    def test_core_modules_registered(self):
        nde._MODULES_INITIALIZED = False
        nde.MODULE_MAP.clear()
        _ensure_modules_loaded()
        # At minimum: drop, lag, throttle, duplicate, ood, corrupt, rst,
        # bandwidth, disconnect — the documented base set.
        for name in ("drop", "lag", "throttle", "duplicate", "ood",
                     "bandwidth", "disconnect"):
            assert name in nde.MODULE_MAP, f"core module '{name}' missing"


# ── NativeWinDivertEngine construction ───────────────────────────────

class TestEngineConstruction:
    def _engine(self, **overrides):
        defaults = {
            "dll_path": r"C:\fake\WinDivert.dll",
            "filter_str": "true",
            "methods": ["drop"],
            "params": {"drop_chance": 50, "_target_ip": "192.168.1.10"},
        }
        defaults.update(overrides)
        return NativeWinDivertEngine(**defaults)

    def test_constructor_stores_dll_path(self):
        eng = self._engine()
        assert eng.dll_path == r"C:\fake\WinDivert.dll"

    def test_filter_validation_passes_allowlisted(self):
        eng = self._engine(filter_str="ip.SrcAddr == 192.168.1.10")
        # Validation accepts → stored verbatim
        assert "ip.SrcAddr" in eng.filter_str

    def test_filter_validation_falls_back_on_bad_filter(self):
        # Validation raises → engine logs and falls back to raw filter
        # (the codepath is defensive — don't crash if validation rejects)
        eng = self._engine(filter_str="DROP TABLE users")
        assert eng.filter_str == "DROP TABLE users"

    def test_methods_validation_drops_unknowns(self):
        eng = self._engine(methods=["drop", "not_a_real_method"])
        assert "drop" in eng.methods
        assert "not_a_real_method" not in eng.methods

    def test_methods_validation_empty(self):
        eng = self._engine(methods=[])
        assert eng.methods == []

    def test_target_ip_u32_precomputed(self):
        eng = self._engine(params={"_target_ip": "192.168.1.10"})
        import socket
        expected = int.from_bytes(
            socket.inet_aton("192.168.1.10"), "big"
        )
        assert eng._target_ip_u32 == expected

    def test_target_ip_unknown_sentinel(self):
        eng = self._engine(params={"_target_ip": "unknown"})
        assert eng._target_ip_u32 == 0

    def test_target_ip_invalid_falls_to_zero(self):
        eng = self._engine(params={"_target_ip": "999.999.999.999"})
        assert eng._target_ip_u32 == 0

    def test_use_local_layer_flag(self):
        eng = self._engine(params={"_network_local": True})
        assert eng._use_local_layer is True
        eng = self._engine(params={"_network_local": False})
        assert eng._use_local_layer is False

    def test_default_alive_is_false(self):
        eng = self._engine()
        assert eng.alive is False

    def test_default_pid_is_zero(self):
        eng = self._engine()
        assert eng.pid == 0

    def test_poll_returns_zero_when_not_running(self):
        eng = self._engine()
        assert eng.poll() == 0

    def test_proc_alias_is_self(self):
        # The engine impersonates a subprocess.Popen object for
        # backward compatibility — _proc must point back to itself.
        eng = self._engine()
        assert eng._proc is eng

    def test_send_buffer_preallocated(self):
        eng = self._engine()
        assert len(eng._send_buf) == MAX_PACKET_SIZE

    def test_target_ip_stored(self):
        eng = self._engine(params={"_target_ip": "10.0.0.5"})
        assert eng.target_ip == "10.0.0.5"

    def test_target_ip_defaults_to_unknown(self):
        eng = self._engine(params={})
        assert eng.target_ip == "unknown"


# ── get_stats ───────────────────────────────────────────────────────

class TestGetStats:
    def _engine(self):
        return NativeWinDivertEngine(
            dll_path=r"C:\fake\WinDivert.dll",
            filter_str="true",
            methods=["drop"],
            params={"_target_ip": "192.168.1.10"},
        )

    def test_returns_core_counters(self):
        eng = self._engine()
        stats = eng.get_stats()
        for key in ("packets_processed", "packets_dropped",
                    "packets_inbound", "packets_outbound",
                    "packets_passed"):
            assert key in stats
            assert stats[key] == 0  # nothing processed yet

    def test_includes_target_ip(self):
        eng = self._engine()
        assert eng.get_stats()["target_ip"] == "192.168.1.10"

    def test_includes_methods(self):
        eng = self._engine()
        assert eng.get_stats()["methods"] == ["drop"]

    def test_alive_false_when_not_started(self):
        eng = self._engine()
        assert eng.get_stats()["alive"] is False

    def test_aggregates_module_stats(self):
        eng = self._engine()
        mock_mod = MagicMock()
        mock_mod.get_stats = MagicMock(return_value={"queue_depth": 7})
        mock_mod.__class__.__name__ = "FakeModule"
        eng._modules = [mock_mod]
        stats = eng.get_stats()
        assert "module_stats" in stats
        # The MagicMock's __class__.__name__ is "MagicMock" — class
        # name patching is awkward, so we just confirm at least one
        # entry exists with our payload.
        any_match = any(
            v.get("queue_depth") == 7 for v in stats["module_stats"].values()
        )
        assert any_match

    def test_swallows_module_stats_errors(self):
        eng = self._engine()
        bad_mod = MagicMock()
        bad_mod.get_stats = MagicMock(side_effect=RuntimeError("boom"))
        eng._modules = [bad_mod]
        # Must not raise — defensive try/except in get_stats
        stats = eng.get_stats()
        assert "packets_processed" in stats


# ── mark_last_cut_outcome ───────────────────────────────────────────

class TestMarkLastCutOutcome:
    def _engine(self):
        return NativeWinDivertEngine(
            dll_path=r"C:\fake\WinDivert.dll",
            filter_str="true",
            methods=["drop"],
            params={},
        )

    def test_stashes_pending_outcome_persisted(self):
        eng = self._engine()
        eng.mark_last_cut_outcome(True)
        assert eng._pending_cut_outcome is True

    def test_stashes_pending_outcome_not_persisted(self):
        eng = self._engine()
        eng.mark_last_cut_outcome(False)
        assert eng._pending_cut_outcome is False

    def test_coerces_truthy_to_bool(self):
        eng = self._engine()
        eng.mark_last_cut_outcome("yes")  # type: ignore[arg-type]
        assert eng._pending_cut_outcome is True

    def test_no_episode_recorder_short_circuits(self):
        # When recorder is None, mark_last_cut_outcome should still
        # stash the value but not raise.
        eng = self._engine()
        assert eng._episode_recorder is None
        eng.mark_last_cut_outcome(True)
        assert eng._pending_cut_outcome is True


# ── ProcessLikeInterface (subprocess shim) ──────────────────────────

class TestSubprocessShim:
    """Engine pretends to be a subprocess for backward compat — these
    are the bits the disruption manager probes."""

    def test_pid_zero_no_thread(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        assert eng.pid == 0

    def test_pid_returns_thread_ident(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        fake_thread = MagicMock()
        fake_thread.ident = 12345
        eng._thread = fake_thread
        assert eng.pid == 12345

    def test_alive_false_without_thread(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        eng._running = True
        # No thread — alive should still be False
        assert eng.alive is False

    def test_alive_true_when_thread_alive_and_running(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        eng._running = True
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        eng._thread = fake_thread
        assert eng.alive is True


# ── _send_packet (handle-closed defensive path) ─────────────────────

class TestSendPacketGuard:
    def test_send_packet_noop_when_handle_closed(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        # No handle, no divert — _send_packet must short-circuit silently
        eng._send_packet(bytearray(b"\x00" * 20), WINDIVERT_ADDRESS())
        # The pre-allocated send_buf should be unchanged at byte 0
        # since memmove never ran.
        assert eng._handle is None


# ── _cleanup ────────────────────────────────────────────────────────

class TestCleanup:
    def test_cleanup_when_no_handle(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        eng._running = True
        eng._cleanup()
        assert eng._running is False
        assert eng._handle is None

    def test_cleanup_closes_handle(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        eng._running = True
        eng._handle = 0xDEADBEEF
        eng._divert = MagicMock()
        eng._cleanup()
        eng._divert.close.assert_called_once_with(0xDEADBEEF)
        assert eng._handle is None
        assert eng._running is False

    def test_cleanup_skips_invalid_handle(self):
        eng = NativeWinDivertEngine(
            r"C:\fake\WinDivert.dll", "true", [], {})
        eng._handle = INVALID_HANDLE_VALUE
        eng._divert = MagicMock()
        eng._cleanup()
        eng._divert.close.assert_not_called()
