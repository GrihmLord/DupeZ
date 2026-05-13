"""Custom preset editor dialog (v5.6.9 feature #1).

Minimal Qt dialog for creating / editing / deleting user-authored
presets via :mod:`app.core.preset_store`. Designed to be invoked from
the Tools or File menu (wiring lives in :mod:`app.gui.clumsy_control`).

The dialog deliberately does NOT recreate the full slider UI from
clumsy_control. For numeric param tuning the operator should pick the
preset in the main view and use the existing sliders + the "Save as
Custom Preset…" button. This dialog focuses on the LIFECYCLE: name,
description, method selection, port list, process scope, save / load /
export / import / delete.

Wiring (one-liner from the main GUI):

    from app.gui.dialogs.preset_editor_dialog import PresetEditorDialog
    PresetEditorDialog(self).exec()

The dialog never raises into the caller — all errors surface as
QMessageBox warnings inside the dialog so the GUI stays responsive.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
    QWidget,
)

from app.core.preset_store import (
    CustomPreset,
    PresetValidationError,
    VALID_METHODS,
    delete_custom_preset,
    export_preset,
    get_custom_preset,
    import_preset,
    list_custom_presets,
    save_custom_preset,
    validate_preset,
)

__all__ = ["PresetEditorDialog"]


# Method labels sorted for stable presentation. Mapping is method-name
# (engine key) → user-facing label. Kept in this file to avoid a circular
# import on app.gui.clumsy_control where engine-side method docs live.
_METHOD_LABELS = {
    "drop":         "Drop (chance-based packet loss)",
    "lag":          "Lag (delay queue)",
    "throttle":     "Throttle (frame/burst slowdown)",
    "duplicate":    "Duplicate (replay copies)",
    "corrupt":      "Corrupt (payload byte flips)",
    "rst":          "RST (TCP reset injection)",
    "bandwidth":    "Bandwidth cap (token bucket)",
    "disconnect":   "Disconnect (stateful timed cut)",
    "ooo":          "Out-of-order (reorder window)",
    "godmode":      "God Mode (pulse cycle)",
    "pulse":        "Pulse (timed bidirectional)",
    "tick_sync":    "Tick-Sync (server-tick aligned drop)",
    "stealth_drop": "Stealth Drop (jittered loss)",
    "stealth_lag":  "Stealth Lag (jittered delay)",
}


class PresetEditorDialog(QDialog):
    """Modal editor for the custom-preset store."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Preset Editor")
        self.setMinimumSize(680, 520)
        self._current: Optional[CustomPreset] = None
        self._build_ui()
        self._reload_list()

    # ── UI construction ────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # Left: list of existing custom presets + new/delete/export/import
        left = QVBoxLayout()
        left.addWidget(QLabel("Custom Presets"))
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list_widget, 1)

        list_btns = QHBoxLayout()
        for label, slot in (
            ("New", self._on_new),
            ("Delete", self._on_delete),
            ("Export…", self._on_export),
            ("Import…", self._on_import),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            list_btns.addWidget(b)
        left.addLayout(list_btns)
        root.addLayout(left, 1)

        # Right: edit form for the selected/new preset
        right = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Surgical 7s")
        form.addRow("Name:", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Short description (optional)")
        form.addRow("Description:", self.desc_edit)

        # Methods as a stacked column of checkboxes — clearer than a
        # multiselect for a finite list and easier to validate.
        methods_box = QWidget()
        mb = QVBoxLayout(methods_box)
        mb.setContentsMargins(0, 0, 0, 0)
        self.method_checks = {}
        for m in sorted(VALID_METHODS):
            cb = QCheckBox(_METHOD_LABELS.get(m, m))
            cb.setProperty("method_key", m)
            self.method_checks[m] = cb
            mb.addWidget(cb)
        form.addRow("Methods:", methods_box)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["both", "inbound", "outbound"])
        form.addRow("Direction:", self.direction_combo)

        self.ports_edit = QLineEdit()
        self.ports_edit.setPlaceholderText(
            "Comma-separated ports, e.g. 2302,2303,2304,2305  (empty = all)"
        )
        form.addRow("Ports (v5.6.9 #3):", self.ports_edit)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["(none)", "auto", "dayz"])
        form.addRow("Process scope (v5.6.9 #4):", self.scope_combo)

        self.params_edit = QTextEdit()
        self.params_edit.setPlaceholderText(
            "Extra params as JSON (optional). Merged with the fields "
            "above on save. Use this for module-specific tuning that "
            "doesn't have a dedicated field, e.g. drop_chance, "
            "lag_delay, disconnect_duration_ms."
        )
        self.params_edit.setMaximumHeight(120)
        form.addRow("Params JSON:", self.params_edit)

        right.addLayout(form)

        # Bottom: standard Save / Close button bar
        buttons = QDialogButtonBox()
        save_btn = buttons.addButton(
            "Save", QDialogButtonBox.ButtonRole.AcceptRole
        )
        close_btn = buttons.addButton(
            "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        save_btn.clicked.connect(self._on_save)
        close_btn.clicked.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 2)

    # ── List management ────────────────────────────────────────────
    def _reload_list(self) -> None:
        self.list_widget.clear()
        for p in list_custom_presets():
            QListWidgetItem(p.name, self.list_widget)

    def _on_select(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        if current is None:
            self._clear_form()
            return
        p = get_custom_preset(current.text())
        if p is None:
            self._clear_form()
            return
        self._load_form(p)

    # ── Form ↔ CustomPreset ────────────────────────────────────────
    def _clear_form(self) -> None:
        self._current = None
        self.name_edit.clear()
        self.desc_edit.clear()
        for cb in self.method_checks.values():
            cb.setChecked(False)
        self.direction_combo.setCurrentText("both")
        self.ports_edit.clear()
        self.scope_combo.setCurrentText("(none)")
        self.params_edit.clear()

    def _load_form(self, p: CustomPreset) -> None:
        import json
        self._current = p
        self.name_edit.setText(p.name)
        self.desc_edit.setText(p.description)
        for m, cb in self.method_checks.items():
            cb.setChecked(m in p.methods)
        self.direction_combo.setCurrentText(p.params.get("direction", "both"))
        ports = p.params.get("_ports") or []
        ports_str = ",".join(
            str(e if isinstance(e, int) else e.get("port", "")) for e in ports
        )
        self.ports_edit.setText(ports_str)
        scope = p.params.get("_process_scope") or ""
        self.scope_combo.setCurrentText(scope if scope else "(none)")
        # Hide the "managed" keys from the JSON box to avoid double-edits.
        extra = {
            k: v for k, v in p.params.items()
            if k not in ("direction", "_ports", "_process_scope")
        }
        self.params_edit.setPlainText(
            json.dumps(extra, indent=2) if extra else ""
        )

    def _form_to_preset(self) -> CustomPreset:
        import json
        name = self.name_edit.text().strip()
        desc = self.desc_edit.text().strip()
        methods = sorted(
            m for m, cb in self.method_checks.items() if cb.isChecked()
        )

        # Parse ports list
        ports_raw = self.ports_edit.text().strip()
        ports = []
        if ports_raw:
            for part in ports_raw.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ports.append(int(part))
                except ValueError:
                    raise PresetValidationError(f"port not an integer: {part!r}")

        scope_text = self.scope_combo.currentText()
        scope = "" if scope_text == "(none)" else scope_text

        # Merge extras (JSON box) with managed fields. Managed keys
        # win on collision — operator's intent in the dedicated fields
        # trumps stale JSON in the free-text box.
        extras_raw = self.params_edit.toPlainText().strip()
        if extras_raw:
            try:
                extras = json.loads(extras_raw)
                if not isinstance(extras, dict):
                    raise PresetValidationError(
                        "params JSON must be an object (dict)"
                    )
            except json.JSONDecodeError as e:
                raise PresetValidationError(
                    f"params JSON invalid: {e}"
                )
        else:
            extras = {}

        params = dict(extras)
        params["direction"] = self.direction_combo.currentText()
        if ports:
            params["_ports"] = ports
        if scope:
            params["_process_scope"] = scope

        return CustomPreset(
            name=name, description=desc, methods=methods, params=params,
        )

    # ── Button handlers ────────────────────────────────────────────
    def _on_new(self) -> None:
        self.list_widget.clearSelection()
        self._clear_form()
        self.name_edit.setFocus()

    def _on_save(self) -> None:
        try:
            p = self._form_to_preset()
            validate_preset(p)
        except PresetValidationError as e:
            QMessageBox.warning(self, "Invalid Preset", str(e))
            return
        if save_custom_preset(p):
            QMessageBox.information(
                self, "Preset Saved", f"Saved preset {p.name!r}"
            )
            self._reload_list()
            # Re-select the row we just saved so the form stays sticky.
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).text() == p.name:
                    self.list_widget.setCurrentRow(i)
                    break
        else:
            QMessageBox.critical(
                self, "Save Failed",
                "Could not persist preset. Check logs."
            )

    def _on_delete(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        name = current.text()
        if QMessageBox.question(
            self, "Delete Preset",
            f"Delete custom preset {name!r}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if delete_custom_preset(name):
            self._reload_list()
            self._clear_form()
        else:
            QMessageBox.warning(
                self, "Delete Failed",
                f"Could not delete {name!r}. Check logs."
            )

    def _on_export(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            QMessageBox.information(
                self, "Export Preset",
                "Select a preset on the left first."
            )
            return
        p = get_custom_preset(current.text())
        if p is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Preset",
            f"{p.name.replace(' ', '_')}.dupez-preset.json",
            "DupeZ Preset (*.json)",
        )
        if not path:
            return
        if export_preset(p, path):
            QMessageBox.information(
                self, "Export Complete",
                f"Preset exported to:\n{path}"
            )
        else:
            QMessageBox.critical(
                self, "Export Failed",
                "Could not write the preset file. Check logs."
            )

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Preset", "",
            "DupeZ Preset (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            p = import_preset(path)
        except PresetValidationError as e:
            QMessageBox.warning(self, "Import Failed", str(e))
            return
        self._reload_list()
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == p.name:
                self.list_widget.setCurrentRow(i)
                break
        QMessageBox.information(
            self, "Import Complete",
            f"Imported as {p.name!r}"
        )
