"""Tests for GUI-independent GPU capability probing."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_renderer_probe_failure_falls_back_to_cpu(monkeypatch) -> None:
    monkeypatch.setattr(renderer_tier, "_user_override", lambda: "auto")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: True)
    monkeypatch.setattr(renderer_tier, "_is_admin_token", lambda: False)
    monkeypatch.setattr(
        gpu_probe,
        "probe_gpu_usable",
        lambda: (False, "probe-unavailable"),
    )

    assert renderer_tier.resolve_tier() == "tier3_cpu"


def test_legacy_swiftshader_preference_migrates_to_cpu(monkeypatch) -> None:
    monkeypatch.setenv("DUPEZ_MAP_RENDERER", "swiftshader")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: True)
    monkeypatch.setattr(renderer_tier, "_is_admin_token", lambda: False)

    assert renderer_tier.resolve_tier() == "tier3_cpu"


@pytest.mark.parametrize(
    ("split_mode", "admin_token"),
    ((False, False), (True, True)),
)
def test_gpu_preference_cannot_cross_architecture_or_token_boundary(
    monkeypatch: pytest.MonkeyPatch,
    split_mode: bool,
    admin_token: bool,
) -> None:
    monkeypatch.setenv("DUPEZ_MAP_RENDERER", "gpu")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: split_mode)
    monkeypatch.setattr(renderer_tier, "_is_admin_token", lambda: admin_token)

    assert renderer_tier.resolve_tier() == "tier3_cpu"


def test_renderer_tiers_never_embed_no_sandbox_flag() -> None:
    assert renderer_tier.TIER_FLAGS
    assert all(
        "--no-sandbox" not in flags
        for flags in renderer_tier.TIER_FLAGS.values()
    )
    assert all(
        "swiftshader" not in flags.casefold()
        for flags in renderer_tier.TIER_FLAGS.values()
    )
    assert "--ignore-gpu-blocklist" not in renderer_tier.TIER_FLAGS["tier1_hw"]


def test_child_webengine_environment_drops_parent_renderer_bypasses() -> None:
    environment = renderer_tier.child_webengine_environment({
        "Path": r"C:\Windows\System32",
        "QTWEBENGINE_DISABLE_SANDBOX": "1",
        "qtwebengine_chromium_flags": "--disable-gpu --no-sandbox",
        "QT_OPENGL": "software",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_BACKEND": "software",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "GALLIUM_DRIVER": "llvmpipe",
        "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
        "QTWEBENGINE_REMOTE_DEBUGGING": "9222",
        "QTWEBENGINEPROCESS_PATH": r"C:\untrusted\QtWebEngineProcess.exe",
        "DUPEZ_MAP_RENDERER": "software",
        "DUPEZ_MAP_RENDERER_TIER": "tier3_cpu",
    })

    assert environment["Path"] == r"C:\Windows\System32"
    assert "QTWEBENGINE_DISABLE_SANDBOX" not in environment
    assert "qtwebengine_chromium_flags" not in environment
    assert "QT_OPENGL" not in environment
    assert "QT_QPA_PLATFORM" not in environment
    assert "QT_QUICK_BACKEND" not in environment
    assert "LIBGL_ALWAYS_SOFTWARE" not in environment
    assert "GALLIUM_DRIVER" not in environment
    assert "MESA_LOADER_DRIVER_OVERRIDE" not in environment
    assert "QTWEBENGINE_REMOTE_DEBUGGING" not in environment
    assert "QTWEBENGINEPROCESS_PATH" not in environment
    assert environment["QTWEBENGINE_CHROMIUM_FLAGS"] == (
        renderer_tier.TIER_FLAGS["tier1_hw"]
    )
    assert environment["DUPEZ_MAP_RENDERER"] == "gpu"
    assert environment["DUPEZ_MAP_RENDERER_TIER"] == "tier1_hw"


@pytest.mark.parametrize(
    "unsafe_flag",
    ["--no-sandbox", "--no-sandbox=true", '"--no-sandbox"'],
)
def test_split_sandbox_policy_clears_inherited_bypasses(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_flag: str,
) -> None:
    monkeypatch.setenv("QTWEBENGINE_DISABLE_SANDBOX", "1")
    monkeypatch.setenv(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        f"--use-gl=angle {unsafe_flag} --enable-zero-copy",
    )

    renderer_tier.apply_chromium_sandbox_policy(disable=False)

    assert "QTWEBENGINE_DISABLE_SANDBOX" not in renderer_tier.os.environ
    flags = renderer_tier.os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    assert "--no-sandbox" not in flags
    assert "--use-gl=angle" in flags
    assert "--enable-zero-copy" in flags


def test_inproc_sandbox_policy_uses_only_qt_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QTWEBENGINE_DISABLE_SANDBOX", raising=False)
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)

    renderer_tier.apply_chromium_sandbox_policy(disable=True)

    assert renderer_tier.os.environ["QTWEBENGINE_DISABLE_SANDBOX"] == "1"
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in renderer_tier.os.environ


def test_apply_chromium_flags_enforces_split_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer_tier, "resolve_tier", lambda: "tier1_hw")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: True)
    monkeypatch.setenv("QTWEBENGINE_DISABLE_SANDBOX", "1")
    monkeypatch.setenv(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--no-sandbox --use-gl=angle",
    )

    assert renderer_tier.apply_chromium_flags() == "tier1_hw"
    assert "QTWEBENGINE_DISABLE_SANDBOX" not in renderer_tier.os.environ
    assert "--no-sandbox" not in renderer_tier.os.environ[
        "QTWEBENGINE_CHROMIUM_FLAGS"
    ]


def test_frozen_renderer_overwrites_inherited_legacy_flags(monkeypatch) -> None:
    monkeypatch.setattr(renderer_tier.sys, "frozen", True, raising=False)
    monkeypatch.setattr(renderer_tier, "resolve_tier", lambda: "tier1_hw")
    monkeypatch.setattr(renderer_tier, "_is_split_mode", lambda: True)
    monkeypatch.setenv(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--use-gl=swiftshader --no-sandbox",
    )

    assert renderer_tier.apply_chromium_flags() == "tier1_hw"
    flags = renderer_tier.os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    assert flags == renderer_tier.TIER_FLAGS["tier1_hw"]
    assert "swiftshader" not in flags.casefold()


def test_webengine_diagnostic_preserves_sandbox_and_tls_validation() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "diagnose_webengine.py"
    ).read_text(encoding="utf-8")

    assert "--no-sandbox" not in source
    certificate_handler = source.split(
        "def certificateError(self, error):",
        maxsplit=1,
    )[1].split("\n\n", maxsplit=1)[0]
    assert "return False" in certificate_handler
    assert "return True" not in certificate_handler
