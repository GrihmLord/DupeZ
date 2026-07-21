from __future__ import annotations

from app.core.resource_profile import detect_startup_resource_profile

_GIB = 1024 ** 3


def test_low_resource_profile_caps_threads_and_skips_map_prewarm() -> None:
    profile = detect_startup_resource_profile(
        cpu_count=4,
        total_memory_bytes=8 * _GIB,
        available_memory_bytes=2 * _GIB,
        environ={},
    )

    assert profile.low_resource is True
    assert profile.prewarm_map is False
    assert profile.qt_max_threads == 2
    assert profile.qt_expiry_timeout_ms == 10_000
    assert profile.startup_timeout_ms == 180_000
    assert set(profile.reasons) == {"cpu<=4", "ram<=8GiB", "available_ram<=2GiB"}


def test_normal_profile_keeps_prewarm_with_bounded_threads() -> None:
    profile = detect_startup_resource_profile(
        cpu_count=24,
        total_memory_bytes=32 * _GIB,
        available_memory_bytes=18 * _GIB,
        environ={},
    )

    assert profile.low_resource is False
    assert profile.prewarm_map is True
    assert profile.qt_max_threads == 8
    assert profile.qt_expiry_timeout_ms == 30_000
    assert profile.startup_timeout_ms == 120_000


def test_operator_overrides_are_bounded_and_deterministic() -> None:
    profile = detect_startup_resource_profile(
        cpu_count=2,
        total_memory_bytes=4 * _GIB,
        available_memory_bytes=1 * _GIB,
        environ={
            "DUPEZ_LOW_RESOURCE": "0",
            "DUPEZ_MAP_PREWARM": "0",
            "DUPEZ_QT_MAX_THREADS": "999",
            "DUPEZ_STARTUP_TIMEOUT_MS": "1000",
        },
    )

    assert profile.low_resource is False
    assert profile.prewarm_map is False
    assert profile.qt_max_threads == 16
    assert profile.startup_timeout_ms == 30_000
    assert profile.reasons == ("operator override",)


def test_invalid_overrides_fall_back_to_auto_defaults() -> None:
    profile = detect_startup_resource_profile(
        cpu_count=6,
        total_memory_bytes=16 * _GIB,
        available_memory_bytes=8 * _GIB,
        environ={
            "DUPEZ_LOW_RESOURCE": "maybe",
            "DUPEZ_MAP_PREWARM": "maybe",
            "DUPEZ_QT_MAX_THREADS": "not-an-int",
            "DUPEZ_STARTUP_TIMEOUT_MS": "not-an-int",
        },
    )

    assert profile.low_resource is False
    assert profile.prewarm_map is True
    assert profile.qt_max_threads == 6
    assert profile.startup_timeout_ms == 120_000


def test_summary_contains_only_aggregate_capacity_data() -> None:
    profile = detect_startup_resource_profile(
        cpu_count=4,
        total_memory_bytes=8 * _GIB,
        available_memory_bytes=3 * _GIB,
        environ={},
    )

    summary = profile.summary()
    assert "cpu=4" in summary
    assert "memory=8.0 GiB" in summary
    assert "available=3.0 GiB" in summary
    assert "low_resource=True" in summary
