"""Shared pytest fixtures for DupeZ test suite."""

import pytest


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
