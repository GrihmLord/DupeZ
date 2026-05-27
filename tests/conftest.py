"""Shared pytest fixtures for DupeZ test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Pin basetemp to a repo-local directory.
#
# Pytest's default basetemp is %LOCALAPPDATA%\Temp\pytest-of-<USER> on
# Windows. If ANY pytest run on this machine was ever invoked under an
# elevated token (typical for this project -- dupez.py auto-elevates
# via UAC, and a test session launched from inside an elevated shell
# inherits the admin token), the DACL on that directory is written
# admin-only. Every subsequent non-elevated run then dies with
# "WinError 5 -- Access is denied" at the tmp_path fixture setup,
# producing dozens of bogus test errors that have nothing to do with
# the code under test.
#
# Repo-local basetemp avoids the problem entirely:
#   * the path is owned by whoever wrote out the repo (always the
#     developer's normal token);
#   * the directory creation uses the same token for elevated and
#     non-elevated runs;
#   * --basetemp on the CLI still overrides this, so CI can pin it to
#     a workspace-scoped path if needed.
#
# Computed from this file's path so it is always absolute regardless
# of the CWD pytest is invoked from. .pytest-tmp/ is in .gitignore.

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_BASETEMP = _REPO_ROOT / ".pytest-tmp"


def pytest_configure(config):
    """Pin --basetemp to a repo-local dir when the user hasn't set one."""
    if getattr(config.option, "basetemp", None):
        # Caller passed --basetemp explicitly. Respect it.
        return
    _REPO_BASETEMP.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(_REPO_BASETEMP)


# Per-test fixtures.


@pytest.fixture
def profiles_dir(tmp_path):
    """Provide a temporary directory for profile storage."""
    d = tmp_path / "profiles"
    d.mkdir()
    return str(d)


@pytest.fixture
def data_dir(tmp_path):
    """Provide a temporary directory for data persistence."""
    d = tmp_path / "data"
    d.mkdir()
    return str(d)
