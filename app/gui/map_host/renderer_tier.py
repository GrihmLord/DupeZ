#!/usr/bin/env python
"""QtWebEngine renderer policy applied before any PyQt6 import.

The split GPU build uses Chromium's ANGLE/D3D11 path only after a successful
hardware probe. Elevated, explicitly software, and inconclusive launches use
Chromium's supported ``--disable-gpu`` fallback. Legacy SwiftShader GL flags
are intentionally rejected: current Chromium treats that backend as removed,
and forcing a software-GL JIT for an untrusted remote page weakens the product
boundary as well as crashing current QtWebEngine builds.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Literal, Mapping


log = logging.getLogger(__name__)

Tier = Literal["tier1_hw", "tier3_cpu"]

TIER_FLAGS: dict[Tier, str] = {
    "tier1_hw": (
        "--enable-gpu-rasterization "
        "--enable-zero-copy "
        "--use-gl=angle "
        "--use-angle=d3d11 "
        "--enable-features=CanvasOopRasterization"
    ),
    "tier3_cpu": "--disable-gpu",
}

_NO_SANDBOX_FLAG_RE = re.compile(
    r"(?<!\S)[\"']?--no-sandbox(?:=[^\s\"']*)?[\"']?(?!\S)",
    re.IGNORECASE,
)
_VALID_OVERRIDES = frozenset({"auto", "gpu", "software"})
_CHILD_RENDERER_ENV_KEYS = frozenset({
    "dupez_map_renderer",
    "dupez_map_renderer_tier",
    "gallium_driver",
    "libgl_always_software",
    "mesa_loader_driver_override",
    "qsg_rhi_backend",
    "qt_angle_platform",
    "qt_opengl",
    "qt_qpa_platform",
    "qt_quick_backend",
})


def child_webengine_environment(
    base: Mapping[str, str],
) -> dict[str, str]:
    """Return a sandboxed hardware-renderer environment for the map host.

    The map host may be launched from an elevated CPU-rendered parent.  It
    must not inherit that parent's renderer, sandbox-bypass, or remote-debug
    settings.  Other entries come from the target user's environment block
    (or the current development environment on non-Windows platforms).
    """

    environment = {
        str(key): str(value)
        for key, value in base.items()
        if (
            str(key).casefold() not in _CHILD_RENDERER_ENV_KEYS
            and not str(key).casefold().startswith("qtwebengine")
        )
    }
    environment["QTWEBENGINE_CHROMIUM_FLAGS"] = TIER_FLAGS["tier1_hw"]
    environment["DUPEZ_MAP_RENDERER"] = "gpu"
    environment["DUPEZ_MAP_RENDERER_TIER"] = "tier1_hw"
    return environment


def _is_split_mode() -> bool:
    try:
        from app.firewall_helper.feature_flag import is_split_mode

        return bool(is_split_mode())
    except Exception:
        arch = (os.environ.get("DUPEZ_ARCH") or "").strip().lower()
        return arch == "split"


def apply_chromium_sandbox_policy(*, disable: bool) -> None:
    """Apply the reviewed architecture sandbox policy before Qt imports."""

    if disable:
        os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        return

    os.environ.pop("QTWEBENGINE_DISABLE_SANDBOX", None)
    inherited = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS")
    if inherited is None:
        return
    sanitized = _NO_SANDBOX_FLAG_RE.sub("", inherited).strip()
    if sanitized:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = sanitized
    else:
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)


def _user_override() -> str:
    value = (os.environ.get("DUPEZ_MAP_RENDERER") or "auto").strip().lower()
    if value == "swiftshader":
        log.warning(
            "legacy SwiftShader renderer preference migrated to CPU software"
        )
        return "software"
    if value not in _VALID_OVERRIDES:
        log.warning("invalid map renderer preference ignored")
        return "auto"
    return value


def _is_admin_token() -> bool:
    """Best-effort check for an elevated Windows token."""

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def resolve_tier() -> Tier:
    """Resolve a renderer without promoting probe failure to a risky backend."""

    override = _user_override()
    if override == "software":
        log.info("renderer tier: tier3_cpu (operator preference)")
        return "tier3_cpu"

    # Architecture and token boundaries outrank persisted preferences. A GPU
    # choice saved by the split build must never re-enable Chromium's GPU
    # process when the same profile is later opened by the elevated Compat
    # build.
    if not _is_split_mode():
        if override == "gpu":
            log.warning(
                "renderer tier: GPU preference ignored in-process"
            )
        log.info("renderer tier: tier3_cpu (in-process architecture)")
        return "tier3_cpu"
    if _is_admin_token():
        if override == "gpu":
            log.warning(
                "renderer tier: GPU preference ignored for admin token"
            )
        log.warning("renderer tier: tier3_cpu (split GUI has an admin token)")
        return "tier3_cpu"
    if override == "gpu":
        log.info("renderer tier: tier1_hw (operator preference)")
        return "tier1_hw"

    from app.core.gpu_probe import probe_gpu_usable

    usable, reason = probe_gpu_usable()
    if usable:
        log.info("renderer tier: tier1_hw (%s)", reason)
        return "tier1_hw"

    log.warning("renderer tier: tier3_cpu (hardware probe unavailable: %s)", reason)
    return "tier3_cpu"


def apply_chromium_flags() -> Tier:
    """Set the reviewed Chromium and Qt renderer environment."""

    tier = resolve_tier()
    flags = TIER_FLAGS[tier]

    # A frozen release is a reviewed browser boundary. Do not let inherited
    # process environment replace its Chromium command line. Source launches
    # retain explicit operator flags for diagnostics.
    if (
        getattr(sys, "frozen", False)
        or "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ
    ):
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
        log.info("QTWEBENGINE_CHROMIUM_FLAGS selected for %s", tier)
    else:
        log.info("operator Chromium flags retained for source diagnostics")

    apply_chromium_sandbox_policy(disable=not _is_split_mode())

    if getattr(sys, "frozen", False):
        os.environ["QT_OPENGL"] = "software"
    else:
        os.environ.setdefault("QT_OPENGL", "software")

    os.environ["DUPEZ_MAP_RENDERER_TIER"] = tier
    return tier
