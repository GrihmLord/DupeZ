"""Tests for app.core.audit_webhook (v5.7.0 feature #10)."""

from __future__ import annotations

import threading
import time

import pytest

from app.core.audit_webhook import (
    DEFAULT_EVENT_WHITELIST,
    DiscordWebhookSink,
    GenericWebhookSink,
    _TokenBucket,
    _looks_like_ip,
    _scrub,
    clear_sinks,
    emit_to_sinks,
    list_sinks,
    register_sink,
    unregister_sink,
)


@pytest.fixture(autouse=True)
def _isolate_sink_registry() -> None:
    """Clear the module-level sink list before AND after each test.

    The sink registry is process-wide; without isolation, test order
    affects results. Autouse fixture ensures every test starts and
    ends with an empty registry.
    """
    clear_sinks()
    yield
    clear_sinks()


class TestTokenBucket:
    """Rate-limiting bucket — capacity + refill semantics."""

    def test_starts_full(self) -> None:
        # v5.7.1 fix: bucket starts with tokens=capacity so the first
        # subscribed event always lands. Pre-v5.7.1 the bucket started
        # at 0 and the first ~1s of events were silently dropped.
        b = _TokenBucket(capacity=10, refill_per_min=60)
        assert b.take() is True

    def test_drains_to_zero(self) -> None:
        # Calling take() capacity times drains the bucket.
        b = _TokenBucket(capacity=3, refill_per_min=60)
        for _ in range(3):
            assert b.take() is True
        # Fourth take should fail (no refill yet at sub-second precision).
        assert b.take() is False

    def test_refill_after_time_grants_tokens(self) -> None:
        # 60/min = 1/sec; drain the bucket, then sleep 1.1s for 1+ token.
        b = _TokenBucket(capacity=10, refill_per_min=60)
        # Drain
        while b.take():
            pass
        time.sleep(1.1)
        assert b.take() is True

    def test_capacity_cap(self) -> None:
        # Bucket can't accumulate beyond capacity even if idle for hours.
        b = _TokenBucket(capacity=3, refill_per_min=60)
        # Drain initial fill.
        while b.take():
            pass
        # Advance last_refill far back to simulate long idle.
        b.last_refill = time.time() - 3600  # 1h ago — would accrue ~3600 tokens
        successes = 0
        for _ in range(20):
            if b.take():
                successes += 1
        # Should cap at exactly capacity (3).
        assert successes == 3


class TestScrub:
    """Underscore-prefix removal + IP masking defense-in-depth."""

    def test_strips_underscore_keys(self) -> None:
        out = _scrub({"public": 1, "_internal": "secret"})
        assert out == {"public": 1}
        assert "_internal" not in out

    def test_preserves_non_underscore_keys(self) -> None:
        out = _scrub({"event": "cut_end", "duration": 7.5})
        assert out == {"event": "cut_end", "duration": 7.5}

    def test_recurses_into_nested_dicts(self) -> None:
        out = _scrub({"outer": {"_secret": 1, "public": 2}})
        assert out == {"outer": {"public": 2}}

    def test_masks_ip_strings(self) -> None:
        out = _scrub({"target": "192.168.1.50"})
        # Mask details vary by app.utils.helpers.mask_ip impl; just
        # verify the raw IP isn't passed through verbatim.
        assert out["target"] != "192.168.1.50" or "192.168" not in out["target"]

    def test_handles_lists_with_dicts(self) -> None:
        out = _scrub({
            "items": [{"_hidden": "x", "shown": "y"}],
        })
        assert out == {"items": [{"shown": "y"}]}


class TestLooksLikeIp:
    """IPv4 detector used by _scrub."""

    def test_valid_ipv4(self) -> None:
        assert _looks_like_ip("192.168.1.1") is True

    def test_zero_address(self) -> None:
        assert _looks_like_ip("0.0.0.0") is True

    def test_max_address(self) -> None:
        assert _looks_like_ip("255.255.255.255") is True

    def test_octet_out_of_range_rejected(self) -> None:
        assert _looks_like_ip("256.1.1.1") is False

    def test_too_few_octets_rejected(self) -> None:
        assert _looks_like_ip("1.2.3") is False

    def test_too_many_octets_rejected(self) -> None:
        assert _looks_like_ip("1.2.3.4.5") is False

    def test_non_digit_rejected(self) -> None:
        assert _looks_like_ip("a.b.c.d") is False


class TestSinkRegistry:
    """register / unregister / list / clear lifecycle."""

    def test_register_adds_to_list(self) -> None:
        s = DiscordWebhookSink("https://example.invalid/x", rate_limit_per_min=60)
        register_sink(s)
        assert s in list_sinks()
        assert len(list_sinks()) == 1

    def test_register_idempotent_on_identity(self) -> None:
        s = DiscordWebhookSink("https://example.invalid/x")
        register_sink(s)
        register_sink(s)  # second call should not duplicate
        assert len(list_sinks()) == 1

    def test_unregister_removes(self) -> None:
        s = GenericWebhookSink("https://example.invalid/x")
        register_sink(s)
        unregister_sink(s)
        assert list_sinks() == []

    def test_unregister_unknown_is_safe(self) -> None:
        s = GenericWebhookSink("https://example.invalid/x")
        unregister_sink(s)  # never registered; must not raise

    def test_clear_empties_registry(self) -> None:
        register_sink(DiscordWebhookSink("https://example.invalid/a"))
        register_sink(DiscordWebhookSink("https://example.invalid/b"))
        clear_sinks()
        assert list_sinks() == []

    def test_list_returns_snapshot_not_live_view(self) -> None:
        s = DiscordWebhookSink("https://example.invalid/x")
        register_sink(s)
        snap = list_sinks()
        # Mutate the snapshot — should not affect the registry.
        snap.clear()
        assert s in list_sinks()


class TestEventFiltering:
    """accepts() — sinks only fire on whitelisted events."""

    def test_default_whitelist_used(self) -> None:
        s = DiscordWebhookSink("https://example.invalid/x")
        for ev in DEFAULT_EVENT_WHITELIST:
            assert s.accepts(ev), f"sink should accept {ev}"

    def test_custom_whitelist_overrides_default(self) -> None:
        s = DiscordWebhookSink(
            "https://example.invalid/x",
            events={"only_this"},
        )
        assert s.accepts("only_this") is True
        # Default whitelist names are now rejected.
        assert s.accepts("cut_start") is False

    def test_unknown_event_rejected(self) -> None:
        s = DiscordWebhookSink("https://example.invalid/x")
        assert s.accepts("nonexistent_event") is False


class TestEmitToSinks:
    """Fan-out emit dispatches to all registered sinks asynchronously."""

    def test_emit_does_not_block(self) -> None:
        # Each sink fires on its own daemon thread; emit_to_sinks
        # itself should return quickly even with a slow sink. The
        # async dispatch lives inside AuditSink.emit (the base class),
        # so the SlowSink must inherit from it to exercise that path.
        from app.core.audit_webhook import AuditSink

        class SlowSink(AuditSink):
            def _post(self, _e: str, _p: dict) -> None:
                time.sleep(0.5)  # would block if not async

        register_sink(SlowSink(
            "https://example.invalid/slow",
            rate_limit_per_min=60,
        ))
        start = time.time()
        emit_to_sinks("cut_start", {"x": 1})
        elapsed = time.time() - start
        assert elapsed < 0.2, f"emit_to_sinks blocked {elapsed:.2f}s"

    def test_audit_event_fans_out_to_sinks(self) -> None:
        """v5.7.4 wiring guard: AuditLogger.log() must call emit_to_sinks.

        Pre-v5.7.4 the audit logger never fanned out — a configured
        webhook received nothing because emit_to_sinks had zero
        callers. This test registers a sink, fires a real audit event,
        and asserts the sink saw it. Locks the wiring so a future
        refactor of audit.py cannot silently sever it again.
        """
        from app.core.audit_webhook import AuditSink

        received = []

        class CaptureSink(AuditSink):
            def accepts(self, _e: str) -> bool:
                return True  # capture everything for the test

            def _post(self, event: str, payload: dict) -> None:
                received.append((event, payload))

        register_sink(CaptureSink(
            "https://example.invalid/capture", rate_limit_per_min=120,
        ))
        # Fire through the real audit entry point.
        from app.logs.audit import audit_event
        audit_event("cut_start", {"target_ip": "10.0.0.9"})
        # Sink dispatch is daemon-threaded; give it a moment.
        time.sleep(0.1)
        assert received, (
            "audit_event did not reach the sink — the v5.7.4 "
            "AuditLogger.log → emit_to_sinks wiring is broken"
        )
        assert received[0][0] == "cut_start"

    def test_one_sink_failure_does_not_block_others(self) -> None:
        # A sink whose emit() raises must not prevent other sinks
        # from firing. Use a real AuditSink subclass so the registry's
        # type-checked dispatch path is exercised.
        from app.core.audit_webhook import AuditSink

        delivered = []

        class GoodSink(AuditSink):
            def _post(self, e: str, p: dict) -> None:
                delivered.append((e, p))

        class CrashSink(AuditSink):
            def emit(self, _e: str, _p: dict) -> None:
                raise RuntimeError("simulated sink crash")

        register_sink(CrashSink(
            "https://example.invalid/crash", rate_limit_per_min=60,
        ))
        register_sink(GoodSink(
            "https://example.invalid/good", rate_limit_per_min=60,
        ))
        emit_to_sinks("cut_start", {"key": "value"})
        # GoodSink's _post runs on a daemon thread; give it a moment.
        time.sleep(0.05)
        # Good sink received the SCRUBBED payload (note: _scrub passes
        # this one through unchanged since no underscore keys).
        assert delivered == [("cut_start", {"key": "value"})]
