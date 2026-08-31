"""Regression tests for Compat whole-GUI privilege authorization."""

from __future__ import annotations

from app import main as app_main
from app.firewall_helper import elevation


def test_split_gui_does_not_run_whole_process_factor(monkeypatch) -> None:
    monkeypatch.setattr(
        elevation,
        "enforce_second_factor",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("split GUI attempted in-process authorization")
        ),
    )

    assert app_main._authorize_inproc_startup(split_mode=True)


def test_inproc_gui_requires_factor_before_startup(monkeypatch) -> None:
    calls: list[str] = []

    def authorize(*, boundary: str) -> None:
        calls.append(boundary)

    monkeypatch.setattr(elevation, "enforce_second_factor", authorize)

    assert app_main._authorize_inproc_startup(split_mode=False)
    assert calls == ["inproc_startup"]


def test_inproc_gui_factor_failure_is_fixed_and_path_free(monkeypatch) -> None:
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        elevation,
        "enforce_second_factor",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(r"SENSITIVE C:\Users\owner\secret")
        ),
    )
    monkeypatch.setattr(
        app_main.QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )

    assert not app_main._authorize_inproc_startup(split_mode=False)
    assert messages == [
        (
            "Authorization Required",
            "DupeZ could not authorize privileged firewall startup. "
            "No network engine was initialized.",
        )
    ]
    assert "SENSITIVE" not in repr(messages)
    assert "Users" not in repr(messages)
