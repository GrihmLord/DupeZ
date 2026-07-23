# app/gui/panels/clumsy_advanced_lifetime.py — cycle-free param adapter
"""Keep ClumsyControlView parameter routing safe across Qt teardown.

The first advanced-panel implementation stored a closure on the parent view
that strongly captured the child panel. That formed a Python/Qt ownership cycle
and caused the offscreen dashboard smoke process to fast-fail after printing
its success marker. This adapter keeps only a weak panel reference and restores
the previous collector when Qt destroys the panel.
"""

from __future__ import annotations

import weakref
from typing import Any, Callable

from app.gui.panels.clumsy_advanced_panel import ClumsyAdvancedPanel

__all__ = ["install_clumsy_advanced_lifetime"]


def _view_accessor(view: Any) -> Callable[[], Any]:
    """Return a weak accessor when supported, otherwise a bounded strong one."""

    try:
        reference = weakref.ref(view)
    except TypeError:
        # Lightweight test doubles such as SimpleNamespace are not always
        # weak-referenceable. The fallback is owned only by the panel's Qt
        # destroyed callback and does not create a view->panel strong edge.
        return lambda: view
    return reference


def _install_weak_param_adapter(panel: ClumsyAdvancedPanel) -> None:
    view = panel._clumsy_view
    previous = view._collect_params
    panel_ref = weakref.ref(panel)
    get_view = _view_accessor(view)

    def collect_with_advanced_controls() -> dict[str, Any]:
        active_panel = panel_ref()
        base = previous()
        if active_panel is None:
            return base
        return active_panel.augment_params(base)

    panel_proxy = weakref.proxy(panel)
    view._clumsy_advanced_param_adapter = panel_proxy
    view._collect_params = collect_with_advanced_controls

    def restore_previous_collector(_destroyed: Any = None) -> None:
        active_view = get_view()
        if active_view is None:
            return
        if getattr(active_view, "_collect_params", None) is collect_with_advanced_controls:
            active_view._collect_params = previous
        try:
            adapter = getattr(
                active_view,
                "_clumsy_advanced_param_adapter",
                None,
            )
            # Accessing a dead weak proxy raises ReferenceError. Either case
            # means the adapter attribute is no longer useful.
            if adapter is panel_proxy:
                delattr(active_view, "_clumsy_advanced_param_adapter")
        except ReferenceError:
            try:
                delattr(active_view, "_clumsy_advanced_param_adapter")
            except AttributeError:
                pass

    panel.destroyed.connect(restore_previous_collector)


def install_clumsy_advanced_lifetime() -> None:
    """Install the cycle-free adapter before the first panel is constructed."""

    if getattr(
        ClumsyAdvancedPanel,
        "_cycle_free_param_adapter_installed",
        False,
    ):
        return
    ClumsyAdvancedPanel._install_param_adapter = _install_weak_param_adapter
    ClumsyAdvancedPanel._cycle_free_param_adapter_installed = True
