"""Tests for GUI-independent GPU capability probing."""

from __future__ import annotations

from app.core import gpu_probe
from app.firewall_helper import feature_flag
from app.gui.map_host import renderer_tier


def test_non_windows_gpu_probe_is_conservative(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe.sys, "platform", "linux")

    assert gpu_probe.probe_gpu_usable() == (False, "non-windows")


def test_feature_flag_gpu_detection_uses_core_probe(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe, "probe_gpu_usable", lambda: (True, "test"))

    assert feature_flag._detect_gpu_available() is True


def test_renderer_tier_uses_core_probe(monkeypatch) -> None:
    monkeypatch.setattr(renderer_tier, "_user_override", lambda: "auto")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: True)
    monkeypatch.setattr(renderer_tier, "_is_admin_token", lambda: False)
    monkeypatch.setattr(gpu_probe, "probe_gpu_usable", lambda: (True, "test"))

    assert renderer_tier.resolve_tier() == "tier1_hw"
