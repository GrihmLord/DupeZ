"""Regression coverage for actionable splash startup failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import controller as controller_module
from app.gui import splash as splash_module
from app.gui.splash import DupeZSplash


class _Signal:
    def __init__(self) -> None:
        self.values = []

    def emit(self, *values) -> None:
        self.values.append(values)


def test_controller_exception_is_preserved_for_user(monkeypatch) -> None:
    def _fail():
        raise RuntimeError("helper handshake rejected")

    monkeypatch.setattr(controller_module, "AppController", _fail)
    fake = SimpleNamespace(
        controller=None,
        init_error=None,
        _try_log_info=lambda _message: None,
    )

    with pytest.raises(RuntimeError, match="helper handshake rejected"):
        DupeZSplash._init_controller(fake)

    assert fake.init_error == (
        "Controller failed to initialize: helper handshake rejected"
    )


def test_finalize_does_not_replace_specific_controller_error() -> None:
    signal = _Signal()
    fake = SimpleNamespace(
        controller=None,
        init_error="Controller failed to initialize: pipe timeout",
        _error_signal=signal,
    )

    DupeZSplash._init_finalize(fake)

    assert fake.init_error.endswith("pipe timeout")
    assert signal.values == []


def test_pipeline_stops_dependent_steps_after_controller_failure(
    monkeypatch,
) -> None:
    calls = []

    def _ok():
        calls.append("preflight")

    def _init_controller():
        calls.append("controller")
        raise RuntimeError("WinDivert helper unavailable")

    def _later():
        calls.append("later")

    fake = SimpleNamespace(
        _init_logging=_ok,
        _init_admin_check=_ok,
        _init_app_identity=_ok,
        _init_game_profiles=_ok,
        _init_windivert=_ok,
        _init_modules=_ok,
        _init_controller=_init_controller,
        _init_plugins=_later,
        _init_theme=_later,
        _init_scanner=_later,
        _init_finalize=_later,
        _status_signal=_Signal(),
        _progress_signal=_Signal(),
        _error_signal=_Signal(),
        _done_signal=_Signal(),
        _try_log_error=lambda _message: None,
        init_error=None,
    )
    monkeypatch.setattr(splash_module.time, "sleep", lambda _seconds: None)

    DupeZSplash._pipeline(fake)

    assert calls[-1] == "controller"
    assert "later" not in calls
    assert fake._done_signal.values == [()]
    assert "WinDivert helper unavailable" in fake._error_signal.values[0][0]
