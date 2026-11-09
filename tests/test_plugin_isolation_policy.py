"""Tests for the in-process plugin containment policy."""

import os
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


@pytest.mark.parametrize(
    "flags",
    (
        os.O_WRONLY,
        os.O_RDWR,
        os.O_CREAT | os.O_WRONLY,
        os.O_TRUNC | os.O_WRONLY,
    ),
)
def test_low_level_open_write_flags_require_declared_capability(flags: int) -> None:
    activate_sandbox()
    with plugin_scope("test-plugin", set()):
        with pytest.raises(SandboxViolation, match="file open for write"):
            sys.audit("open", "test-output", None, flags)


def test_low_level_read_only_open_remains_available() -> None:
    activate_sandbox()
    with plugin_scope("test-plugin", set()):
        sys.audit("open", "test-input", None, os.O_RDONLY)
