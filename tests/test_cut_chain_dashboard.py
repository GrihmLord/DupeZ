"""Dashboard and controller-facing cut-chain wiring contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QDialog, QMessageBox

from app.core.cut_chain import ChainConfig, ChainEvent, Gate, Stage
from app.gui import dashboard as dashboard_module
from app.gui.dashboard import DupeZDashboard


def _config() -> ChainConfig:
    return ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=2.0))],
        global_timeout_s=30.0,
    )


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, text: str, timeout: int) -> None:
        self.messages.append((text, timeout))


class _Signal:
    def __init__(self) -> None:
        self.emitted: list[tuple[int, object]] = []

    def emit(self, generation: int, event: object) -> None:
        self.emitted.append((generation, event))


def test_tray_quit_exits_qt_only_after_dashboard_cleanup_is_accepted(
    monkeypatch,
) -> None:
    events: list[str] = []
    application = SimpleNamespace(quit=lambda: events.append("quit"))
    monkeypatch.setattr(
        dashboard_module,
        "QApplication",
        SimpleNamespace(instance=lambda: application),
    )
    parent = SimpleNamespace(
        _force_quit=False,
        close=lambda: events.append("close") or True,
    )

    DupeZDashboard._tray_quit(parent)

    assert parent._force_quit is True
    assert events == ["close", "quit"]


def test_tray_quit_keeps_event_loop_alive_when_cleanup_is_refused(
    monkeypatch,
) -> None:
    events: list[str] = []
    application = SimpleNamespace(quit=lambda: events.append("quit"))
    monkeypatch.setattr(
        dashboard_module,
        "QApplication",
        SimpleNamespace(instance=lambda: application),
    )
    parent = SimpleNamespace(
        _force_quit=False,
        close=lambda: events.append("close") or False,
    )

    DupeZDashboard._tray_quit(parent)

    assert parent._force_quit is True
    assert events == ["close"]


def test_dashboard_opens_dialog_for_single_selected_target_and_starts(
    monkeypatch,
) -> None:
    from app.gui import cut_chain_dialog

    config = _config()
    opened = {}

    class _Dialog:
        def __init__(self, target, *, safety_policy, parent) -> None:
            opened["target"] = target
            opened["policy"] = safety_policy
            opened["parent"] = parent

        @staticmethod
        def exec():
            return QDialog.DialogCode.Accepted

        @staticmethod
        def selected_config():
            return config

    class _Controller:
        safety_policy = object()
        state = SimpleNamespace(selected_ip=None)

        def start_cut_chain(self, received, *, on_event):
            opened["config"] = received
            opened["callback"] = on_event
            return 7

    monkeypatch.setattr(
        cut_chain_dialog,
        "CutChainConfiguratorDialog",
        _Dialog,
    )
    status = _StatusBar()
    signal = _Signal()
    parent = SimpleNamespace(
        controller=_Controller(),
        clumsy_view=SimpleNamespace(
            selected_ips={"192.168.1.25"},
            selected_ip="192.168.1.25",
        ),
        status_bar=status,
        _cut_chain_ui_generation=0,
        _cut_chain_event_ready=signal,
    )

    DupeZDashboard._open_cut_chain_configurator(parent)

    assert opened["target"] == "192.168.1.25"
    assert opened["policy"] is parent.controller.safety_policy
    assert opened["parent"] is parent
    assert opened["config"] is config
    assert parent._cut_chain_ui_generation == 1
    opened["callback"](ChainEvent("stage_start", 0))
    assert signal.emitted == [(1, ChainEvent("stage_start", 0))]
    assert status.messages[-1] == ("Cut chain started (1 stages)", 5000)


def test_dashboard_refuses_ambiguous_multi_target_selection(
    monkeypatch,
) -> None:
    warnings = []

    class _Controller:
        @staticmethod
        def start_cut_chain(*_args, **_kwargs):
            raise AssertionError("ambiguous selection reached controller")

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, body: warnings.append((title, body)),
    )
    parent = SimpleNamespace(
        controller=_Controller(),
        clumsy_view=SimpleNamespace(
            selected_ips={"192.168.1.25", "192.168.1.26"},
            selected_ip="192.168.1.25",
        ),
    )

    DupeZDashboard._open_cut_chain_configurator(parent)

    assert warnings == [
        (
            "One Target Required",
            "A cut chain runs on exactly one device. Clear the other "
            "selections and try again.",
        )
    ]


def test_dashboard_chain_progress_is_generation_guarded_and_private() -> None:
    status = _StatusBar()
    parent = SimpleNamespace(
        _cut_chain_ui_generation=4,
        status_bar=status,
    )
    secret_detail = "target=192.168.1.25 token=private"

    DupeZDashboard._on_cut_chain_event(
        parent,
        3,
        ChainEvent("error", -1, secret_detail),
    )
    assert status.messages == []

    DupeZDashboard._on_cut_chain_event(
        parent,
        4,
        ChainEvent("error", -1, secret_detail),
    )
    assert status.messages == [
        (
            "Cut chain failed — target released; review the local log",
            8000,
        )
    ]
    assert secret_detail not in status.messages[0][0]


def test_dashboard_never_claims_release_when_chain_cleanup_is_unconfirmed() -> None:
    status = _StatusBar()
    parent = SimpleNamespace(
        _cut_chain_ui_generation=2,
        status_bar=status,
    )

    DupeZDashboard._on_cut_chain_event(
        parent,
        2,
        ChainEvent("error", -1, "stage release could not be confirmed"),
    )

    assert status.messages == [
        (
            "Cut chain failed — release not confirmed; retry Panic Stop",
            8000,
        )
    ]


def test_dashboard_stop_all_reports_unconfirmed_cleanup_truthfully() -> None:
    status = _StatusBar()
    parent = SimpleNamespace(
        controller=SimpleNamespace(stop_all_disruptions=lambda: False),
        status_bar=status,
    )

    DupeZDashboard._stop_all_disruptions(parent)

    assert status.messages == [
        ("Cleanup not confirmed — retry Stop All or Panic Stop", 8000)
    ]
    assert not any("All disruptions stopped" in text for text, _ in status.messages)


def test_dashboard_panic_uses_kill_switch_and_never_claims_failed_release(
    monkeypatch,
) -> None:
    status = _StatusBar()
    reasons = []
    criticals = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, body: criticals.append((title, body)),
    )
    parent = SimpleNamespace(
        controller=SimpleNamespace(
            fire_manual_kill_switch=lambda reason: reasons.append(reason) or False
        ),
        status_bar=status,
    )

    DupeZDashboard._kill_switch_panic(parent)

    assert reasons == ["dashboard panic stop"]
    assert status.messages == [
        ("KILL SWITCH — cleanup not confirmed; retry Panic Stop", 8000)
    ]
    assert len(criticals) == 1
    assert "could not confirm" in criticals[0][1]


def test_tools_menu_preserves_existing_actions_and_adds_chain_shortcut() -> None:
    source = (
        Path(__file__).parents[1] / "app" / "gui" / "dashboard.py"
    ).read_text(encoding="utf-8")
    for callback in (
        "self._show_diagnostics",
        "self._show_audit_webhook_config",
        "self._show_network_health",
        "self._kill_switch_panic",
        "self._toggle_obs_overlay",
        "self._open_cut_chain_configurator",
    ):
        assert callback in source
    assert '"Ctrl+Shift+C"' in source
    assert '"F2"' in source
    assert '"Ctrl+Alt+X"' in source
