"""Regression coverage for fail-closed frozen startup hardening."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest

from app.core import self_integrity


_ROOT = Path(__file__).resolve().parents[1]


class _FakeWin32Function:
    def __init__(self, result: int) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        return self.result


def test_dll_hardening_excludes_portable_application_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_default = _FakeWin32Function(1)
    add_directory = _FakeWin32Function(1)
    kernel32 = types.SimpleNamespace(
        SetDefaultDllDirectories=set_default,
        AddDllDirectory=add_directory,
    )
    monkeypatch.setattr(self_integrity.os, "name", "nt")
    monkeypatch.setattr(
        self_integrity.ctypes,
        "windll",
        types.SimpleNamespace(kernel32=kernel32),
        raising=False,
    )

    first = self_integrity.harden_dll_search_path()
    second = self_integrity.harden_dll_search_path()

    assert first is self_integrity.DllHardeningResult.APPLIED
    assert second is self_integrity.DllHardeningResult.APPLIED
    assert set_default.calls == [(0x00000C00,), (0x00000C00,)]
    assert add_directory.calls == []


@pytest.mark.parametrize(
    "result",
    [
        self_integrity.DllHardeningResult.SKIPPED_NON_WINDOWS,
        self_integrity.DllHardeningResult.UNAVAILABLE,
        self_integrity.DllHardeningResult.FAILED,
    ],
)
def test_required_dll_hardening_rejects_before_authenticode(
    monkeypatch: pytest.MonkeyPatch,
    result: self_integrity.DllHardeningResult,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        self_integrity,
        "harden_dll_search_path",
        lambda **_kwargs: calls.append("dll") or result,
    )
    monkeypatch.setattr(
        self_integrity,
        "verify_self_authenticode",
        lambda: pytest.fail("Authenticode ran after DLL hardening failed"),
    )

    with pytest.raises(RuntimeError, match="refusing startup"):
        self_integrity.apply_startup_hardening(
            require_dll_hardening=True,
        )

    assert calls == ["dll"]


def test_required_dll_hardening_accepts_applied_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        self_integrity,
        "harden_dll_search_path",
        lambda **_kwargs: self_integrity.DllHardeningResult.APPLIED,
    )
    monkeypatch.setattr(
        self_integrity,
        "verify_self_authenticode",
        lambda: self_integrity.TrustReport(
            self_integrity.TrustState.TRUSTED,
            "",
        ),
    )
    monkeypatch.setattr("app.logs.audit.audit_event", lambda *_args: None)

    report = self_integrity.apply_startup_hardening(
        require_dll_hardening=True,
    )

    assert report["dll_hardening"] == "applied"
    assert report["trust_state"] == "trusted"


def test_frozen_enforcer_wraps_unexpected_failure_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        self_integrity,
        "_is_frozen_windows_release",
        lambda: True,
    )
    monkeypatch.setattr(
        self_integrity,
        "apply_startup_hardening",
        lambda **_kwargs: (_ for _ in ()).throw(
            OSError(r"C:\attacker\secret.dll")
        ),
    )

    with pytest.raises(RuntimeError) as caught:
        self_integrity.enforce_startup_hardening()

    assert "refusing startup" in str(caught.value)
    assert "attacker" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_development_enforcer_preserves_best_effort_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        self_integrity,
        "_is_frozen_windows_release",
        lambda: False,
    )
    monkeypatch.setattr(
        self_integrity,
        "apply_startup_hardening",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("dev-only")),
    )

    assert self_integrity.enforce_startup_hardening() == {}


def test_frozen_launcher_hardening_failure_precedes_helper_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    integrity_stub = types.ModuleType("app.core.self_integrity")

    def fail_hardening() -> None:
        raise OSError(r"C:\attacker\secret.dll")

    integrity_stub.enforce_startup_hardening = fail_hardening
    helper_stub = types.ModuleType("dupez_helper")
    helper_stub.main = lambda: pytest.fail("helper imported before hardening")
    monkeypatch.setitem(sys.modules, "app.core.self_integrity", integrity_stub)
    monkeypatch.setitem(sys.modules, "dupez_helper", helper_stub)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["DupeZ-GPU.exe", "--role", "helper"],
    )

    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(_ROOT / "dupez.py"), run_name="__main__")

    assert caught.value.code == 1
    stderr = capsys.readouterr().err
    assert "refusing startup" in stderr
    assert "attacker" not in stderr


def test_both_launchers_enforce_hardening_before_native_imports() -> None:
    launcher = (_ROOT / "dupez.py").read_text(encoding="utf-8")
    main_source = (_ROOT / "app" / "main.py").read_text(encoding="utf-8")

    root_gate = launcher.index(
        "\n_enforce_frozen_windows_startup_hardening()\n"
    )
    assert root_gate < launcher.index("import faulthandler")
    assert root_gate < launcher.index("\n_maybe_dispatch_helper_role()\n")
    assert root_gate < launcher.index("\n_maybe_handle_v576_flags()\n")

    main_gate = main_source.index("enforce_startup_hardening")
    assert main_gate < main_source.index("from PyQt6.QtGui import QIcon")
    assert "if _FROZEN_WINDOWS_RELEASE:" in main_source
