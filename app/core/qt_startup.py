"""Qt process-startup helpers with no third-party imports."""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping, Sequence

__all__ = [
    "is_qt_graphics_override",
    "normalized_qt_argv",
    "sanitize_frozen_qt_graphics_environment",
]


_QT_GRAPHICS_OVERRIDE_NAMES = frozenset({
    "qt_angle_platform",
    "qt_no_opengl_buglist",
    "qt_opengl",
    "qt_opengl_buglist",
    "qt_opengl_dll",
    "qt_quick_backend",
    # Unlike ordinary DPI scaling, this enables the QRhi widget renderer.
    "qt_widgets_highdpi_downscale",
    "qt_widgets_rhi",
})
_QT_GRAPHICS_OVERRIDE_PREFIXES = ("qt_widgets_rhi_", "qsg_rhi_")


def is_qt_graphics_override(name: str) -> bool:
    """Identify inherited native renderer selectors without reading values."""
    canonical = name.casefold()
    return (
        canonical in _QT_GRAPHICS_OVERRIDE_NAMES
        or canonical.startswith(_QT_GRAPHICS_OVERRIDE_PREFIXES)
    )


def sanitize_frozen_qt_graphics_environment(
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Pin frozen Windows policy before application QtGui/renderer startup.

    ``QT_OPENGL=software`` alone still lets ``QT_OPENGL_DLL`` select a different
    DLL, while inherited QRhi selectors can replace normal QWidget raster
    presentation. Remove those controls before maintenance or GUI dispatch.
    Preserve source diagnostics, ordinary DPI/accessibility settings, and the
    trusted Qt plugin path installed by the PyInstaller runtime hook. That
    internal hook loads QtCore earlier; this boundary precedes application
    maintenance/QtGui imports and renderer initialization, not that hook.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    target = os.environ if environment is None else environment
    for name in tuple(target):
        if is_qt_graphics_override(name):
            del target[name]
    target["QT_OPENGL"] = "software"


def normalized_qt_argv(
    argv: Sequence[str] | None = None,
    *,
    executable: str | None = None,
) -> list[str]:
    """Return a private, non-empty argv suitable for ``QApplication``.

    Current QtWebEngine builds terminate the process if Qt was initialized
    without a program name. Frozen launchers normally provide one, but this
    defensive boundary prevents a malformed host launcher from reaching the
    native fatal path.
    """

    values = list(sys.argv if argv is None else argv)
    fallback = str(executable or sys.executable or "DupeZ").strip() or "DupeZ"
    fallback = os.path.abspath(fallback)
    if not values:
        return [fallback]
    if not isinstance(values[0], str) or not values[0].strip():
        values[0] = fallback
    return values
