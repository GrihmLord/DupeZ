"""Fail-closed integration tests for second-factor protected boundaries."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import pytest

import app.firewall_helper.auth as helper_auth
import app.firewall_helper.elevation as elevation
import app.offsec.runner as offsec_runner
import app.plugins.loader as plugin_loader_module
from app.plugins.loader import PluginLoader


_SENSITIVE_ASSERTION = "SENSITIVE_SECOND_FACTOR_ASSERTION"

_FAILURE_MODES = (
    ("gate_import", "dependency_unavailable"),
    ("store_probe", "store_probe_failed"),
    ("store_unavailable", "store_unavailable"),
    ("invalid_store_health", "store_unavailable"),
    ("store_read", "store_read_failed"),
    ("gate_unavailable", "gate_unavailable"),
    ("enrollment_query", "enrollment_query_failed"),
    ("invalid_enrollment", "invalid_enrollment_state"),
    ("inconsistent_enrollment", "enrollment_state_inconsistent"),
    ("verification_refused", "verification_failed"),
    ("verification_error", "verification_failed"),
    ("invalid_verification", "invalid_verification_result"),
)

_READINESS_FAILURE_MODES = _FAILURE_MODES[:-3]


class _SecondFactorRequired(RuntimeError):
    pass


class _Gate:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.enrollment_queries = 0
        self.require_calls = 0

    def is_enrolled(self):
        self.enrollment_queries += 1
        if self.mode == "enrollment_query":
            raise AssertionError(_SENSITIVE_ASSERTION)
        if self.mode == "invalid_enrollment":
            return None
        return self.mode in {
            "verified",
            "verification_refused",
            "verification_error",
            "invalid_verification",
        }

    def require(
        self,
        _scope: str,
        *,
        reason: str,
        prompter=None,
        cache_ttl_sec: int = 300,
        bypass_cache: bool = False,
    ):
        del reason
        del prompter
        if _scope == "elevation":
            assert cache_ttl_sec == 0
            assert bypass_cache is True
        self.require_calls += 1
        if self.mode == "verification_refused":
            raise _SecondFactorRequired(_SENSITIVE_ASSERTION)
        if self.mode == "verification_error":
            raise AssertionError(_SENSITIVE_ASSERTION)
        if self.mode == "invalid_verification":
            return None
        return True


def _install_second_factor_state(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    audit_events: list[tuple[str, dict]],
) -> _Gate:
    gate = _Gate(mode)

    second_factor_module = types.ModuleType("app.core.second_factor")
    second_factor_module.SecondFactorRequired = _SecondFactorRequired

    def get_gate():
        if mode == "gate_unavailable":
            raise AssertionError(_SENSITIVE_ASSERTION)
        return gate

    if mode != "gate_import":
        second_factor_module.get_gate = get_gate

    secret_store_module = types.ModuleType("app.core.secret_store")

    def check_store_health():
        if mode == "store_probe":
            raise AssertionError(_SENSITIVE_ASSERTION)
        if mode == "invalid_store_health":
            return None
        return types.SimpleNamespace(healthy=mode != "store_unavailable")

    secret_store_module.check_store_health = check_store_health

    def get_secret(_kind: str):
        if mode == "store_read":
            raise AssertionError(_SENSITIVE_ASSERTION)
        if mode == "inconsistent_enrollment":
            return b"stored-enrollment"
        return None

    secret_store_module.get_secret = get_secret

    audit_module = types.ModuleType("app.logs.audit")

    def audit_event(event: str, data=None) -> None:
        audit_events.append((event, dict(data or {})))

    audit_module.audit_event = audit_event

    monkeypatch.setitem(sys.modules, "app.core.second_factor", second_factor_module)
    monkeypatch.setitem(sys.modules, "app.core.secret_store", secret_store_module)
    monkeypatch.setitem(sys.modules, "app.logs.audit", audit_module)
    monkeypatch.setenv("DUPEZ_SECOND_FACTOR_DISABLED", "1")
    return gate


def _assert_refusal_audited(
    events: list[tuple[str, dict]],
    *,
    boundary: str,
    failure: str,
) -> None:
    assert events
    assert all(event == "second_factor_boundary_refused" for event, _ in events)
    assert all(data == {"boundary": boundary, "failure": failure} for _, data in events)
    assert _SENSITIVE_ASSERTION not in repr(events)


@pytest.mark.parametrize(("mode", "failure"), _READINESS_FAILURE_MODES)
def test_elevation_gate_failures_never_write_or_launch_helper(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
    failure: str,
) -> None:
    events: list[tuple[str, dict]] = []
    _install_second_factor_state(monkeypatch, mode, events)
    sentinel_writes: list[bytes] = []
    launches: list[int] = []
    monkeypatch.setattr(
        helper_auth,
        "write_token_sentinel",
        lambda secret: sentinel_writes.append(secret),
    )

    def launch(parent_pid: int, pipe_name=None) -> int:
        del pipe_name
        launches.append(parent_pid)
        return 123

    monkeypatch.setattr(elevation, "launch_helper_runas", launch)
    caplog.set_level(logging.WARNING, logger=elevation.__name__)

    with pytest.raises(elevation.ElevationError, match="authorization"):
        elevation.ensure_helper_running(
            mode="runas",
            shared_secret=b"s" * 32,
        )

    assert sentinel_writes == []
    assert launches == []
    _assert_refusal_audited(events, boundary="elevation", failure=failure)
    assert _SENSITIVE_ASSERTION not in caplog.text


@pytest.mark.parametrize(("mode", "failure"), _FAILURE_MODES)
def test_privileged_helper_gate_fails_closed_inside_high_il(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
    failure: str,
) -> None:
    events: list[tuple[str, dict]] = []
    gate = _install_second_factor_state(monkeypatch, mode, events)
    prompts: list[str] = []

    def prompt(scope: str) -> str:
        prompts.append(scope)
        return "123456"

    caplog.set_level(logging.WARNING, logger=elevation.__name__)
    with pytest.raises(elevation.ElevationError, match="authorization"):
        elevation.enforce_second_factor(
            boundary="helper_startup",
            prompter=prompt,
        )

    assert gate.require_calls <= 1
    _assert_refusal_audited(
        events,
        boundary="helper_startup",
        failure=failure,
    )
    assert _SENSITIVE_ASSERTION not in caplog.text


@pytest.mark.parametrize("mode", ("unenrolled", "verified"))
def test_elevation_allows_only_affirmative_gate_states(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    events: list[tuple[str, dict]] = []
    gate = _install_second_factor_state(monkeypatch, mode, events)
    sentinel_writes: list[bytes] = []
    launches: list[int] = []
    monkeypatch.setattr(
        helper_auth,
        "write_token_sentinel",
        lambda secret: sentinel_writes.append(secret),
    )

    def launch(parent_pid: int, pipe_name=None) -> int:
        del pipe_name
        launches.append(parent_pid)
        return 123

    monkeypatch.setattr(elevation, "launch_helper_runas", launch)

    assert elevation.ensure_helper_running(
        mode="runas",
        shared_secret=b"s" * 32,
    ) == 123
    assert sentinel_writes == [b"s" * 32]
    assert len(launches) == 1
    assert gate.enrollment_queries == 1
    # Medium IL performs readiness checks only.  Verification belongs to the
    # High-IL helper, where a direct --role invocation cannot bypass it.
    assert gate.require_calls == 0
    assert events == []


@pytest.mark.parametrize("mode", ("unenrolled", "verified"))
def test_privileged_helper_gate_allows_only_affirmative_states(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    events: list[tuple[str, dict]] = []
    gate = _install_second_factor_state(monkeypatch, mode, events)

    elevation.enforce_second_factor(
        boundary="helper_startup",
        prompter=lambda _scope: "123456",
    )

    assert gate.enrollment_queries == 1
    assert gate.require_calls == (1 if mode == "verified" else 0)
    assert events == []


@pytest.mark.parametrize(("mode", "failure"), _FAILURE_MODES)
def test_plugin_gate_failures_never_import_or_activate_plugin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    failure: str,
) -> None:
    events: list[tuple[str, dict]] = []
    _install_second_factor_state(monkeypatch, mode, events)
    messages: list[str] = []
    imported: list[object] = []
    monkeypatch.setattr(plugin_loader_module, "log_error", messages.append)

    loader = PluginLoader(str(tmp_path))
    manifest = object()
    loader.manifests = {"Boundary Test": manifest}

    def load_plugin(candidate):
        imported.append(candidate)
        return object()

    monkeypatch.setattr(loader, "_load_plugin", load_plugin)

    assert loader.load_plugin("Boundary Test") is None
    assert loader.load_all(controller=object()) == []
    assert imported == []
    _assert_refusal_audited(events, boundary="plugin_load", failure=failure)
    assert _SENSITIVE_ASSERTION not in "\n".join(messages)


@pytest.mark.parametrize("mode", ("unenrolled", "verified"))
def test_plugin_loading_allows_only_affirmative_gate_states(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    events: list[tuple[str, dict]] = []
    gate = _install_second_factor_state(monkeypatch, mode, events)
    imported: list[object] = []
    loader = PluginLoader(str(tmp_path))
    manifest = object()
    loaded_plugin = object()
    loader.manifests = {"Boundary Test": manifest}

    def load_plugin(candidate):
        imported.append(candidate)
        return loaded_plugin

    monkeypatch.setattr(loader, "_load_plugin", load_plugin)

    assert loader.load_plugin("Boundary Test") is loaded_plugin
    assert imported == [manifest]
    assert gate.enrollment_queries == 1
    assert gate.require_calls == (1 if mode == "verified" else 0)
    assert events == []


def _disable_startup_hardening(monkeypatch: pytest.MonkeyPatch) -> None:
    self_integrity_module = types.ModuleType("app.core.self_integrity")
    self_integrity_module.apply_startup_hardening = lambda: None
    monkeypatch.setitem(
        sys.modules,
        "app.core.self_integrity",
        self_integrity_module,
    )


@pytest.mark.parametrize(("mode", "failure"), _FAILURE_MODES)
def test_offsec_gate_failures_never_dispatch_or_execute_tactics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    failure: str,
) -> None:
    events: list[tuple[str, dict]] = []
    _install_second_factor_state(monkeypatch, mode, events)
    _disable_startup_hardening(monkeypatch)
    monkeypatch.setenv(
        offsec_runner.OFFSEC_CONSENT_ENV,
        offsec_runner.OFFSEC_CONSENT_VALUE,
    )
    dispatched: list[list[str]] = []
    tactic_imports: list[str] = []

    def run_all(tactics, _registry):
        dispatched.append(list(tactics))
        return {}

    def import_tactic(module_name: str):
        tactic_imports.append(module_name)
        raise AssertionError(_SENSITIVE_ASSERTION)

    monkeypatch.setattr(offsec_runner, "run_all", run_all)
    monkeypatch.setattr(offsec_runner.importlib, "import_module", import_tactic)
    output = tmp_path / "blocked.json"

    assert offsec_runner.main(
        ["--only", "recon", "--out", str(output)]
    ) == 2
    assert dispatched == []
    assert tactic_imports == []
    assert not output.exists()
    _assert_refusal_audited(events, boundary="offsec_runner", failure=failure)
    captured = capsys.readouterr()
    assert _SENSITIVE_ASSERTION not in captured.out
    assert _SENSITIVE_ASSERTION not in captured.err


@pytest.mark.parametrize("mode", ("unenrolled", "verified"))
def test_offsec_runner_allows_only_affirmative_gate_states(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    events: list[tuple[str, dict]] = []
    gate = _install_second_factor_state(monkeypatch, mode, events)
    _disable_startup_hardening(monkeypatch)
    monkeypatch.setenv(
        offsec_runner.OFFSEC_CONSENT_ENV,
        offsec_runner.OFFSEC_CONSENT_VALUE,
    )
    dispatched: list[list[str]] = []

    def run_all(tactics, _registry):
        dispatched.append(list(tactics))
        return {"recon": "ok"}

    monkeypatch.setattr(offsec_runner, "run_all", run_all)

    assert offsec_runner.main(
        ["--only", "recon", "--out", str(tmp_path / "allowed.json")]
    ) == 0
    assert dispatched == [["recon"]]
    assert gate.enrollment_queries == 1
    assert gate.require_calls == (1 if mode == "verified" else 0)
    assert events == []
