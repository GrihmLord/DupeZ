"""Profile UI persistence feedback regressions."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from app.core.profiles import ProfilePersistenceError
from app.gui import clumsy_control


def test_failed_profile_save_never_displays_success(monkeypatch) -> None:
    messages: list[tuple[str, str]] = []

    class FailingManager:
        @staticmethod
        def save(**_kwargs):
            raise ProfilePersistenceError("private detail")

    harness = SimpleNamespace(
        preset_combo=SimpleNamespace(currentText=lambda: "Example"),
        _profile_manager=FailingManager(),
        _get_active_methods=lambda: ["lag"],
        _collect_params=lambda: {"lag_delay": 100},
    )
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kw: ("Safe", True))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, body: messages.append((title, body)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kw: (_ for _ in ()).throw(
            AssertionError("failed save displayed success")
        ),
    )

    clumsy_control.ClumsyControlView._on_save_profile(harness)

    assert messages == [
        (
            "Save Failed",
            "The profile was not saved. Check the name and storage access, "
            "then try again.",
        )
    ]
