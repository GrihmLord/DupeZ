"""Tests for the in-process plugin containment policy."""

import sys

import pytest

from app.plugins.loader import inprocess_capabilities_allowed
from app.plugins.sandbox import (
    SandboxViolation,
    activate_sandbox,
    plugin_scope,
)


def test_privileged_capabilities_rejected_outside_dev_mode() -> None:
    assert inprocess_capabilities_allowed(
        {"network.http", "process.spawn"},
        dev_mode=False,
    ) is False


def test_low_impact_capabilities_remain_available() -> None:
    assert inprocess_capabilities_allowed(
        {"network.http", "ui.panel"},
        dev_mode=False,
    ) is True


def test_dev_mode_can_exercise_privileged_plugin_during_development() -> None:
    assert inprocess_capabilities_allowed(
        {"fs.write_user_data"},
        dev_mode=True,
    ) is True


def test_ctypes_audit_events_are_denied_inside_plugin_scope() -> None:
    activate_sandbox()
    with plugin_scope("test-plugin", {"network.http"}):
        with pytest.raises(SandboxViolation, match="native memory"):
            sys.audit("ctypes.dlopen", "untrusted.dll")
