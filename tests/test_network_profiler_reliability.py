"""Tests for conservative profiler failure handling and metadata."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from app.ai import network_profiler as profiler_module
from app.ai.network_profiler import NetworkProfile, NetworkProfiler


class _FakeSubprocess:
    PING = "ping.exe"

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout

    def run(self, *_args, **_kwargs):
        return SimpleNamespace(stdout=self.stdout)


def test_ping_parser_is_case_insensitive_and_derives_loss_from_samples(
    monkeypatch,
) -> None:
    output = "reply: time=12ms ttl=128\nreply: TIME<1MS TTL=127\n"
    monkeypatch.setattr(profiler_module, "_safe_sp", _FakeSubprocess(output))
    profile = NetworkProfile(target_ip="192.168.1.2")

    NetworkProfiler(ping_count=3)._probe_ping(profile)

    assert profile.packets_received == 2
    assert profile.packet_loss_pct == 100.0 / 3.0
    assert profile.rtt_samples == [12.0, 1.0]


def test_unparseable_ping_output_is_not_reported_as_healthy(monkeypatch) -> None:
    monkeypatch.setattr(
        profiler_module,
        "_safe_sp",
        _FakeSubprocess("localized output without parseable samples"),
    )
    profile = NetworkProfile(target_ip="192.168.1.2")

    NetworkProfiler(ping_count=2)._probe_ping(profile)

    assert profile.packets_received == 0
    assert profile.packet_loss_pct == 100.0


def test_async_profile_failure_still_invokes_callback_with_failed_profile() -> None:
    class _FailingProfiler(NetworkProfiler):
        def profile(self, target_ip: str, device_info: dict = None):
            raise RuntimeError("probe failed")

    done = threading.Event()
    results = []
    profiler = _FailingProfiler(ping_count=4)
    thread = profiler.profile_async(
        "192.168.137.5",
        callback=lambda profile: (results.append(profile), done.set()),
        device_info={"device_type": "PlayStation 5"},
    )

    assert done.wait(1.0)
    thread.join(timeout=1.0)
    assert results[0].packet_loss_pct == 100.0
    assert results[0].quality_score == 0.0
    assert results[0].platform == "ps5"
