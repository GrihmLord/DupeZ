"""Qt process-startup helpers with no third-party imports."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

__all__ = ["normalized_qt_argv"]


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
