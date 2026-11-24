"""Offscreen coverage for the bounded Network Tools port scanner."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.core.safety_policy import SafetyPolicy
from app.gui import network_tools as network_tools_module
from app.gui.network_tools import PortScannerWidget


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _controller(
    *,
    policy: SafetyPolicy | None = None,
    available: bool = True,
    message: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        safety_policy=policy or SafetyPolicy(max_operation_seconds=5),
        network_operations_available=available,
        get_startup_health=lambda: {"message": message},
    )


def _dispose(widget: PortScannerWidget, qapp: QApplication) -> None:
    widget.cleanup()
    widget.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("controller", "target", "message_fragment"),
    [
        (None, "192.168.1.20", "unavailable"),
        (_controller(available=False, message="recovery pending"), "192.168.1.20", "recovery"),
        (
            _controller(policy=SafetyPolicy(dry_run=True)),
            "192.168.1.20",
            "dry-run",
        ),
        (_controller(), "example.test", "invalid IP address"),
        (_controller(), "8.8.8.8", "local/private IPv4"),
    ],
)
def test_start_scan_fails_closed_for_unsafe_state_or_target(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    controller: object,
    target: str,
    message_fragment: str,
) -> None:
    warning = Mock()
    monkeypatch.setattr(network_tools_module.QMessageBox, "warning", warning)
    widget = PortScannerWidget(controller=controller)
    widget.target_input.setText(target)

    widget._start_scan()

    assert widget._scanning is False
    warning.assert_called_once()
    assert message_fragment.lower() in str(warning.call_args.args[2]).lower()
    _dispose(widget, qapp)


def test_policy_normalizes_target_and_caps_port_set_and_deadline(
    qapp: QApplication,
) -> None:
    policy = SafetyPolicy(
        allowed_cidrs=("192.168.50.0/24",),
        max_operation_seconds=7,
    )
    widget = PortScannerWidget(controller=_controller(policy=policy))

    assert widget._validate_scan_request("192.168.50.20") == (
        "192.168.50.20",
        7.0,
    )
    with pytest.raises(ValueError, match="outside the configured safety scope"):
        widget._validate_scan_request("192.168.51.20")

    widget.port_combo.setCurrentText("Extended (1-4096)")
    ports = widget._resolve_port_list()
    assert len(ports) == widget._MAX_SCAN_PORTS == 4096
    assert ports[0] == 1
    assert ports[-1] == 4096
    _dispose(widget, qapp)


def test_executor_caps_concurrency_and_reports_open_ports(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = PortScannerWidget(controller=_controller())
    widget._MAX_SCAN_WORKERS = 3
    active = 0
    peak = 0
    lock = threading.Lock()

    def probe(
        _ip: str,
        port: int,
        _cancel: threading.Event,
        _timeout: float,
    ) -> tuple[bool, None]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.005)
        with lock:
            active -= 1
        return port == 22, None

    monkeypatch.setattr(widget, "_probe_port", probe)
    result = widget._execute_scan(
        "192.168.1.20",
        list(range(1, 41)),
        2.0,
        threading.Event(),
    )

    assert result.outcome == "completed"
    assert result.completed == result.total == 40
    assert result.open_ports == ((22, "SSH"),)
    assert 1 < peak <= 3
    _dispose(widget, qapp)


def test_scan_enforces_total_port_and_wall_clock_caps(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = Mock()
    monkeypatch.setattr(network_tools_module.QMessageBox, "warning", warning)
    widget = PortScannerWidget(controller=_controller())
    widget.target_input.setText("192.168.1.20")
    monkeypatch.setattr(
        widget,
        "_resolve_port_list",
        lambda: list(range(1, widget._MAX_SCAN_PORTS + 2)),
    )

    widget._start_scan()

    assert widget._scanning is False
    assert f"1-{widget._MAX_SCAN_PORTS}" in str(warning.call_args.args[2])

    widget._MAX_SCAN_WORKERS = 1
    monkeypatch.setattr(
        widget,
        "_probe_port",
        lambda *_args: (time.sleep(0.03) or False, None),
    )
    result = widget._execute_scan(
        "192.168.1.20", [80, 443], 0.005, threading.Event()
    )
    assert result.outcome == "timed_out"
    assert result.completed < result.total
    _dispose(widget, qapp)


def test_zero_open_is_success_but_probe_failures_are_errors(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = PortScannerWidget(controller=_controller())
    monkeypatch.setattr(
        widget,
        "_probe_port",
        lambda *_args: (False, None),
    )
    closed = widget._execute_scan(
        "192.168.1.20", [80, 443], 1.0, threading.Event()
    )
    assert closed.outcome == "completed"
    assert closed.open_ports == ()
    widget._on_scan_done(closed)
    assert "no open ports found" in widget.status_label.text().lower()

    monkeypatch.setattr(
        widget,
        "_probe_port",
        lambda *_args: (False, "OSError: socket backend unavailable"),
    )
    failed = widget._execute_scan(
        "192.168.1.20", [80, 443], 1.0, threading.Event()
    )
    assert failed.outcome == "error"
    assert failed.errors == 2
    widget._on_scan_done(failed)
    assert widget.status_label.text().startswith("Scan failed:")
    _dispose(widget, qapp)


def test_scan_button_cancels_active_worker(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = PortScannerWidget(controller=_controller())
    entered = threading.Event()

    def probe(
        _ip: str,
        _port: int,
        cancel: threading.Event,
        _timeout: float,
    ) -> tuple[bool, None]:
        entered.set()
        cancel.wait(1.0)
        return False, None

    monkeypatch.setattr(widget, "_probe_port", probe)
    monkeypatch.setattr(widget, "_resolve_port_list", lambda: list(range(1, 65)))
    widget.target_input.setText("192.168.1.20")
    widget._start_scan()
    assert entered.wait(1.0)
    thread = widget._scan_thread_ref
    assert thread is not None and thread.is_alive()
    assert widget.btn_scan.text() == "CANCEL"

    widget._toggle_scan()

    assert widget._scan_cancel.is_set()
    assert widget.btn_scan.text() == "CANCELLING..."
    thread.join(timeout=1.0)
    deadline = time.monotonic() + 1.0
    while widget._scanning and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert not thread.is_alive()
    assert widget._scanning is False
    assert "cancelled" in widget.status_label.text().lower()
    _dispose(widget, qapp)


def test_cleanup_cancels_and_joins_active_worker(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = PortScannerWidget(controller=_controller())
    entered = threading.Event()

    def probe(
        _ip: str,
        _port: int,
        cancel: threading.Event,
        _timeout: float,
    ) -> tuple[bool, None]:
        entered.set()
        cancel.wait(1.0)
        return False, None

    monkeypatch.setattr(widget, "_probe_port", probe)
    monkeypatch.setattr(widget, "_resolve_port_list", lambda: list(range(1, 65)))
    widget.target_input.setText("192.168.1.20")
    widget._start_scan()
    assert entered.wait(1.0)
    thread = widget._scan_thread_ref
    assert thread is not None and thread.is_alive()

    assert widget.cleanup() is True
    assert widget._scan_cancel.is_set()
    assert not thread.is_alive()
    assert widget._scan_thread_ref is None
    assert widget._scanning is False
    widget.deleteLater()
    qapp.processEvents()
