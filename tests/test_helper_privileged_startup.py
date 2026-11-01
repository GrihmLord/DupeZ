"""Fail-closed startup ordering for the High-IL firewall helper."""

from __future__ import annotations

import threading
import types

import psutil

import dupez_helper
from app.firewall_helper import auth, elevation


class _FrozenParent:
    def __init__(self, image: str) -> None:
        self._image = image

    def create_time(self) -> float:
        return 123.25

    def is_running(self) -> bool:
        return True

    def exe(self) -> str:
        return self._image


def test_frozen_helper_requires_exact_same_parent_image(
    monkeypatch,
    tmp_path,
) -> None:
    helper_image = tmp_path / "DupeZ-GPU.exe"
    other_image = tmp_path / "other.exe"
    helper_image.write_bytes(b"helper")
    other_image.write_bytes(b"other")
    monkeypatch.setattr(dupez_helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(dupez_helper.sys, "executable", str(helper_image))
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: _FrozenParent(str(other_image)),
    )
    monkeypatch.setattr(dupez_helper.os, "getpid", lambda: 9999)

    try:
        dupez_helper._validate_parent_identity(1234, 123.25)
    except RuntimeError as exc:
        assert "parent image" in str(exc)
    else:  # pragma: no cover - explicit assertion message
        raise AssertionError("frozen helper accepted a different parent image")


def test_helper_session_secret_is_consumed_and_size_checked(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "read_and_consume_token_sentinel",
        lambda: b"s" * auth.TOKEN_BYTES,
    )
    assert dupez_helper._consume_helper_session_secret() == (
        b"s" * auth.TOKEN_BYTES
    )

    monkeypatch.setattr(
        auth,
        "read_and_consume_token_sentinel",
        lambda: b"short",
    )
    try:
        dupez_helper._consume_helper_session_secret()
    except RuntimeError as exc:
        assert "authorization" in str(exc)
    else:  # pragma: no cover - explicit assertion message
        raise AssertionError("helper accepted a malformed session secret")


def test_helper_factor_failure_precedes_native_engine_import(monkeypatch) -> None:
    monkeypatch.setattr(dupez_helper, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        dupez_helper,
        "_parse_args",
        lambda: types.SimpleNamespace(parent_pid=1234, parent_created=123.25),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_validate_parent_identity",
        lambda *_args: 123.25,
    )
    monkeypatch.setattr(
        dupez_helper,
        "_consume_helper_session_secret",
        lambda: b"s" * auth.TOKEN_BYTES,
    )
    monkeypatch.setattr(dupez_helper, "_parent_watcher", lambda *_args: None)
    factor_calls: list[tuple[str, object]] = []

    def refuse(*, boundary: str, prompter) -> None:
        factor_calls.append((boundary, prompter))
        raise elevation.ElevationError("refused")

    monkeypatch.setattr(elevation, "enforce_second_factor", refuse)

    assert dupez_helper.main() == 6
    assert len(factor_calls) == 1
    assert factor_calls[0][0] == "helper_startup"
    assert callable(factor_calls[0][1])


def test_helper_missing_secret_never_prompts_for_factor(monkeypatch) -> None:
    monkeypatch.setattr(dupez_helper, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        dupez_helper,
        "_parse_args",
        lambda: types.SimpleNamespace(parent_pid=1234, parent_created=123.25),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_validate_parent_identity",
        lambda *_args: 123.25,
    )
    monkeypatch.setattr(
        dupez_helper,
        "_consume_helper_session_secret",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(dupez_helper, "_parent_watcher", lambda *_args: None)
    monkeypatch.setattr(
        elevation,
        "enforce_second_factor",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("factor prompt reached without a session secret")
        ),
    )

    assert dupez_helper.main() == 6


def test_parent_liveness_is_bound_before_factor_and_rechecked_before_import(
    monkeypatch,
) -> None:
    monkeypatch.setattr(dupez_helper, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        dupez_helper,
        "_parse_args",
        lambda: types.SimpleNamespace(parent_pid=1234, parent_created=123.25),
    )
    calls: list[str] = []

    def validate(*_args) -> float:
        calls.append("validate")
        if calls.count("validate") == 2:
            raise RuntimeError("stale")
        return 123.25

    monkeypatch.setattr(dupez_helper, "_validate_parent_identity", validate)
    monkeypatch.setattr(
        dupez_helper,
        "_parent_watcher",
        lambda *_args: calls.append("watcher"),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_consume_helper_session_secret",
        lambda: calls.append("secret") or b"s" * auth.TOKEN_BYTES,
    )

    def authorize(*, boundary: str, prompter) -> None:
        assert boundary == "helper_startup"
        assert callable(prompter)
        calls.append("factor")

    monkeypatch.setattr(elevation, "enforce_second_factor", authorize)

    assert dupez_helper.main() == 5
    assert calls == [
        "validate",
        "watcher",
        "secret",
        "factor",
        "validate",
    ]


def test_parent_loss_during_factor_refuses_before_native_import(monkeypatch) -> None:
    monkeypatch.setattr(dupez_helper, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        dupez_helper,
        "_parse_args",
        lambda: types.SimpleNamespace(parent_pid=1234, parent_created=123.25),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_validate_parent_identity",
        lambda *_args: 123.25,
    )
    monkeypatch.setattr(
        dupez_helper,
        "_consume_helper_session_secret",
        lambda: b"s" * auth.TOKEN_BYTES,
    )

    def lose_parent(_pid, shutdown_event: threading.Event, _created) -> None:
        shutdown_event.set()

    monkeypatch.setattr(dupez_helper, "_parent_watcher", lose_parent)

    def refuse(*, boundary: str, prompter) -> None:
        assert boundary == "helper_startup"
        assert callable(prompter)
        raise elevation.ElevationError("refused")

    monkeypatch.setattr(elevation, "enforce_second_factor", refuse)

    assert dupez_helper.main() == 5


def test_invalid_parent_securely_discards_pending_secret(monkeypatch) -> None:
    discarded: list[bool] = []
    monkeypatch.setattr(dupez_helper, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        dupez_helper,
        "_parse_args",
        lambda: types.SimpleNamespace(parent_pid=1234, parent_created=123.25),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_validate_parent_identity",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("invalid")),
    )
    monkeypatch.setattr(
        dupez_helper,
        "_discard_helper_session_secret",
        lambda: discarded.append(True),
    )

    assert dupez_helper.main() == 5
    assert discarded == [True]


def test_factor_prompt_refuses_immediately_after_parent_shutdown() -> None:
    parent_shutdown = threading.Event()
    parent_shutdown.set()

    assert dupez_helper._helper_second_factor_prompter(
        "elevation",
        parent_shutdown_event=parent_shutdown,
    ) == ""
