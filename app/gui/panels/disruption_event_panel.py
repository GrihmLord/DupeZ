# app/gui/panels/disruption_event_panel.py — direct engine and event controls
"""User-facing routing controls and toggleable disruption event queue."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.disruption_events import (
    ENGINE_AUTO,
    ENGINE_CLUMSY,
    ENGINE_NATIVE,
    FAILURE_CONTINUE,
    FAILURE_HALT,
    LAYER_AUTO,
    LAYER_LOCAL,
    LAYER_REMOTE,
    DisruptionEvent,
    EventSequence,
    EventSequenceRunner,
    EventSequenceStatus,
    EventSequenceStore,
)
from app.logs.logger import log_error

__all__ = ["DisruptionEventPanel"]


class DisruptionEventPanel(QGroupBox):
    """Route normal DISRUPT actions and build an ordered event queue."""

    _status_ready = pyqtSignal(object)

    def __init__(
        self,
        clumsy_view: Any,
        parent: Optional[QWidget] = None,
        *,
        store: Optional[EventSequenceStore] = None,
    ) -> None:
        super().__init__("DIRECT CLUMSY / EVENT QUEUE", parent)
        self._clumsy_view = clumsy_view
        self._store = store or EventSequenceStore()
        self._runner: Optional[EventSequenceRunner] = None
        self._sequence = self._load_sequence()
        self._status_ready.connect(self._apply_runner_status)
        self.destroyed.connect(lambda _obj=None: self.stop_runner())

        self.setStyleSheet(self._group_qss())
        self._build_ui()
        self._install_param_adapter()
        self._wire_emergency_controls()
        self._refresh_list()
        self._update_route_status()
        self._set_queue_running(False)

    def _load_sequence(self) -> EventSequence:
        existing = self._store.list_sequences()
        if existing:
            return existing[0]
        sequence = EventSequence(name="My DupeZ Event Queue")
        self._store.save(sequence)
        return sequence

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        route_help = QLabel(
            "Choose how normal DISRUPT actions and newly added events run. "
            "Auto prefers verified standalone Clumsy behavior and uses Native "
            "only when the packet semantics remain equivalent."
        )
        route_help.setWordWrap(True)
        route_help.setStyleSheet(self._muted_qss())
        layout.addWidget(route_help)

        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("Engine"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Auto — verified Clumsy first", ENGINE_AUTO)
        self.engine_combo.addItem("Clumsy — direct owned process", ENGINE_CLUMSY)
        self.engine_combo.addItem("Native — WinDivert extensions", ENGINE_NATIVE)
        self.engine_combo.currentIndexChanged.connect(self._update_route_status)
        route_row.addWidget(self.engine_combo, 1)

        route_row.addWidget(QLabel("Layer"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("Auto detect", LAYER_AUTO)
        self.layer_combo.addItem("Local / NETWORK", LAYER_LOCAL)
        self.layer_combo.addItem("Remote / NETWORK_FORWARD", LAYER_REMOTE)
        self.layer_combo.currentIndexChanged.connect(self._update_route_status)
        route_row.addWidget(self.layer_combo, 1)
        layout.addLayout(route_row)

        self.route_status = QLabel()
        self.route_status.setWordWrap(True)
        self.route_status.setStyleSheet(self._status_qss())
        layout.addWidget(self.route_status)

        timing_row = QHBoxLayout()
        timing_row.addWidget(QLabel("Delay"))
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 3600.0)
        self.delay_spin.setDecimals(1)
        self.delay_spin.setSuffix(" s")
        timing_row.addWidget(self.delay_spin)

        timing_row.addWidget(QLabel("Duration"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 3600.0)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setValue(10.0)
        self.duration_spin.setSuffix(" s")
        timing_row.addWidget(self.duration_spin)

        timing_row.addWidget(QLabel("On failure"))
        self.failure_combo = QComboBox()
        self.failure_combo.addItem("Halt queue", FAILURE_HALT)
        self.failure_combo.addItem("Continue", FAILURE_CONTINUE)
        timing_row.addWidget(self.failure_combo)
        layout.addLayout(timing_row)

        add_row = QHBoxLayout()
        self.add_button = QPushButton("ADD CURRENT EFFECTS")
        self.add_button.clicked.connect(self.add_current_event)
        add_row.addWidget(self.add_button)
        self.remove_button = QPushButton("REMOVE")
        self.remove_button.clicked.connect(self.remove_selected_event)
        add_row.addWidget(self.remove_button)
        self.up_button = QPushButton("UP")
        self.up_button.clicked.connect(lambda: self.move_selected_event(-1))
        add_row.addWidget(self.up_button)
        self.down_button = QPushButton("DOWN")
        self.down_button.clicked.connect(lambda: self.move_selected_event(1))
        add_row.addWidget(self.down_button)
        layout.addLayout(add_row)

        self.event_list = QListWidget()
        self.event_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.event_list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.event_list)

        run_row = QHBoxLayout()
        self.run_button = QPushButton("RUN ENABLED EVENTS")
        self.run_button.clicked.connect(self.run_sequence)
        run_row.addWidget(self.run_button)
        self.stop_button = QPushButton("STOP QUEUE")
        self.stop_button.clicked.connect(self.stop_runner)
        run_row.addWidget(self.stop_button)
        self.diagnostic_button = QPushButton("SHOW CLUMSY WINDOW")
        self.diagnostic_button.clicked.connect(self.show_diagnostic_window)
        run_row.addWidget(self.diagnostic_button)
        layout.addLayout(run_row)

        self.queue_status = QLabel("Queue idle")
        self.queue_status.setWordWrap(True)
        self.queue_status.setStyleSheet(self._muted_qss())
        layout.addWidget(self.queue_status)

    @property
    def engine_preference(self) -> str:
        return str(self.engine_combo.currentData() or ENGINE_AUTO)

    @property
    def network_layer(self) -> str:
        return str(self.layer_combo.currentData() or LAYER_AUTO)

    def augment_params(self, params: dict) -> dict:
        """Apply the current routing choice to a fresh parameter mapping."""

        routed = dict(params or {})
        routed["_engine_preference"] = self.engine_preference
        if self.network_layer == LAYER_AUTO:
            routed.pop("_network_local", None)
            routed.pop("_network_layer_explicit", None)
        else:
            routed["_network_local"] = self.network_layer == LAYER_LOCAL
            routed["_network_layer_explicit"] = True
        return routed

    def _install_param_adapter(self) -> None:
        view = self._clumsy_view
        if getattr(view, "_direct_event_param_adapter", None) is not None:
            return
        original = view._collect_params

        def collect_with_routing() -> dict:
            return self.augment_params(original())

        view._direct_event_param_adapter = self
        view._collect_params = collect_with_routing

    def _wire_emergency_controls(self) -> None:
        """Make the existing STOP controls halt a panel-owned queue too."""

        for name in ("btn_stop", "btn_stop_all"):
            button = getattr(self._clumsy_view, name, None)
            if button is not None:
                button.clicked.connect(self.stop_runner)

    def _set_queue_running(self, running: bool) -> None:
        """Prevent manual starts and queue edits from racing an active queue."""

        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for widget in (
            self.engine_combo,
            self.layer_combo,
            self.delay_spin,
            self.duration_spin,
            self.failure_combo,
            self.add_button,
            self.remove_button,
            self.up_button,
            self.down_button,
            self.event_list,
        ):
            widget.setEnabled(not running)

        # Leave STOP and STOP ALL enabled for emergency release, but disable
        # other start paths that could replace the target generation mid-queue.
        for name in (
            "btn_disrupt",
            "btn_sched_once",
            "btn_run_macro",
        ):
            button = getattr(self._clumsy_view, name, None)
            if button is not None:
                button.setEnabled(not running)

    def _enforce_clumsy_direction(self) -> None:
        """Make explicit Clumsy selection immediately representable.

        The verified bundled-Clumsy path currently guarantees equivalence only
        for bidirectional requests. The legacy effect UI defaults to outbound,
        which made an explicit Clumsy selection fail unless the operator knew
        to toggle inbound manually. Set and lock both controls while Clumsy is
        explicit; restore normal editing for Auto and Native.
        """

        inbound = getattr(self._clumsy_view, "dir_inbound", None)
        outbound = getattr(self._clumsy_view, "dir_outbound", None)
        explicit_clumsy = self.engine_preference == ENGINE_CLUMSY
        for checkbox in (inbound, outbound):
            if checkbox is None:
                continue
            if explicit_clumsy:
                checkbox.blockSignals(True)
                try:
                    checkbox.setChecked(True)
                finally:
                    checkbox.blockSignals(False)
            checkbox.setEnabled(not explicit_clumsy)

    def add_current_event(self) -> None:
        methods = list(self._clumsy_view._get_active_methods())
        if not methods:
            QMessageBox.warning(self, "No Effects", "Enable at least one effect.")
            return
        params = dict(self._clumsy_view._collect_params())
        params.pop("_engine_preference", None)
        params.pop("_network_local", None)
        params.pop("_network_layer_explicit", None)
        event = DisruptionEvent(
            name=" + ".join(
                method.replace("_", " ").title() for method in methods
            ),
            methods=methods,
            params=params,
            engine_preference=self.engine_preference,
            network_layer=self.network_layer,
            start_delay_seconds=self.delay_spin.value(),
            duration_seconds=self.duration_spin.value(),
            failure_policy=str(
                self.failure_combo.currentData() or FAILURE_HALT
            ),
        )
        self._sequence.events.append(event)
        self._save_and_refresh(select_event_id=event.event_id)

    def remove_selected_event(self) -> None:
        row = self.event_list.currentRow()
        if row < 0 or row >= len(self._sequence.events):
            return
        del self._sequence.events[row]
        self._save_and_refresh()

    def move_selected_event(self, offset: int) -> None:
        row = self.event_list.currentRow()
        destination = row + int(offset)
        if (
            row < 0
            or destination < 0
            or destination >= len(self._sequence.events)
        ):
            return
        event = self._sequence.events.pop(row)
        self._sequence.events.insert(destination, event)
        self._save_and_refresh(select_event_id=event.event_id)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        event_id = item.data(Qt.ItemDataRole.UserRole)
        for event in self._sequence.events:
            if event.event_id == event_id:
                event.enabled = item.checkState() == Qt.CheckState.Checked
                self._store.save(self._sequence)
                break

    def _save_and_refresh(self, select_event_id: str = "") -> None:
        self._store.save(self._sequence)
        self._refresh_list(select_event_id=select_event_id)

    def _refresh_list(self, select_event_id: str = "") -> None:
        self.event_list.blockSignals(True)
        self.event_list.clear()
        selected_row = -1
        for index, event in enumerate(self._sequence.events):
            item = QListWidgetItem(
                f"{index + 1}. {event.name} · {event.engine_preference} / "
                f"{event.network_layer} · {event.duration_seconds:g}s"
            )
            item.setData(Qt.ItemDataRole.UserRole, event.event_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if event.enabled
                else Qt.CheckState.Unchecked
            )
            self.event_list.addItem(item)
            if event.event_id == select_event_id:
                selected_row = index
        self.event_list.blockSignals(False)
        if selected_row >= 0:
            self.event_list.setCurrentRow(selected_row)

    def run_sequence(self) -> None:
        targets = list(self._clumsy_view._get_targets())
        if len(targets) != 1:
            QMessageBox.warning(
                self,
                "One Target Required",
                "Event queues run against exactly one selected private target.",
            )
            return
        if not self._sequence.events:
            QMessageBox.warning(self, "Empty Queue", "Add an event first.")
            return
        if self._runner is not None and self._runner.running:
            QMessageBox.information(
                self,
                "Queue Running",
                "Stop the current queue first.",
            )
            return
        controller = self._clumsy_view.controller
        if controller is None:
            QMessageBox.warning(self, "Unavailable", "No controller is attached.")
            return
        target_ip = targets[0]
        metadata = self._clumsy_view._lookup_device_meta(target_ip)
        self._runner = EventSequenceRunner(
            self._sequence,
            controller,
            target_ip,
            disrupt_kwargs=metadata,
            on_status=self._status_ready.emit,
        )
        if self._runner.start():
            self._set_queue_running(True)
            self.queue_status.setText("Queue starting…")
        else:
            self._set_queue_running(False)
            self.queue_status.setText("Queue did not start")

    def stop_runner(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            runner.stop()
        self._set_queue_running(False)
        self.queue_status.setText("Queue stopped")

    def show_diagnostic_window(self) -> None:
        targets = list(self._clumsy_view._get_targets())
        if len(targets) != 1:
            self.queue_status.setText(
                "Select the one active Clumsy target first"
            )
            return
        controller = self._clumsy_view.controller
        manager = getattr(controller, "disruption_manager", None)
        if manager is None:
            manager = getattr(controller, "_disruption_manager", None)
        show = getattr(manager, "show_clumsy_diagnostic_window", None)
        if not callable(show):
            self.queue_status.setText(
                "Diagnostic window restore is not available through this build path"
            )
            return
        try:
            shown = bool(show(targets[0]))
            self.queue_status.setText(
                "Clumsy diagnostic window restored"
                if shown
                else "No owned direct Clumsy window is active"
            )
        except Exception as exc:
            log_error(f"Show Clumsy diagnostic window failed: {exc}")
            self.queue_status.setText(f"Diagnostic window failed: {exc}")

    def _apply_runner_status(self, status: EventSequenceStatus) -> None:
        detail = f" — {status.detail}" if status.detail else ""
        engine = f" [{status.actual_engine}]" if status.actual_engine else ""
        name = status.event_name or "queue"
        self.queue_status.setText(
            f"{status.kind.upper()}: {name}{engine}{detail}"
        )
        if status.kind in {"complete", "stopped", "halted", "error"}:
            self._set_queue_running(False)
            if self._runner is not None and not self._runner.running:
                self._runner = None

    def _update_route_status(self, _index: int = -1) -> None:
        self._enforce_clumsy_direction()
        engine = self.engine_preference
        layer = self.network_layer
        if engine == ENGINE_CLUMSY:
            engine_text = (
                "Direct Clumsy is explicit: both directions are enabled and "
                "locked, no engine substitution is allowed, and only one "
                "Clumsy event may be active per helper."
            )
        elif engine == ENGINE_NATIVE:
            engine_text = "Native WinDivert is explicit: no Clumsy fallback."
        else:
            engine_text = (
                "Auto prefers verified Clumsy controls when direction is both, "
                "then uses Native only for equivalent effects."
            )
        layer_text = (
            "Target profile chooses Local/Remote."
            if layer == LAYER_AUTO
            else f"Capture layer is explicitly pinned to {layer}."
        )
        self.route_status.setText(f"{engine_text} {layer_text}")

    @staticmethod
    def _group_qss() -> str:
        return (
            "QGroupBox { background: #0f1626; color: #00f0ff; "
            "border: 1px solid #1a2a3a; border-radius: 7px; "
            "margin-top: 10px; padding: 12px; font-weight: bold; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; "
            "padding: 0 4px; }"
            "QComboBox, QDoubleSpinBox, QListWidget { background: #0a1628; "
            "color: #e2e8f0; border: 1px solid #26364a; border-radius: 5px; "
            "padding: 5px; }"
            "QPushButton { background: #132337; color: #e2e8f0; "
            "border: 1px solid #2b425d; border-radius: 5px; padding: 6px; }"
            "QPushButton:hover { border-color: #00f0ff; }"
            "QLabel { color: #cbd5e1; font-weight: normal; }"
        )

    @staticmethod
    def _muted_qss() -> str:
        return "color: #94a3b8; font-size: 10px; font-weight: normal;"

    @staticmethod
    def _status_qss() -> str:
        return (
            "color: #67e8f9; font-size: 10px; font-weight: normal; "
            "padding: 5px; background: #08121f; border-radius: 4px;"
        )
