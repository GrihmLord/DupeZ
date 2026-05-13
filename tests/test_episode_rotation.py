"""Tests for the v5.7.1 episode-store rotation policy."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.ai.episode_recorder import rotate_episodes


@pytest.fixture
def episode_tmpdir(tmp_path: Path) -> Path:
    """Provide a temp dir as the episode store + populate test files."""
    return tmp_path


def _make_episode(dir_: Path, name: str, age_days: float) -> Path:
    """Create an episode file with a controlled mtime."""
    p = dir_ / f"episode_{name}.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    if age_days > 0:
        old_ts = time.time() - age_days * 86400.0
        os.utime(p, (old_ts, old_ts))
    return p


class TestAgeCap:
    """Episodes older than retention_days are deleted."""

    def test_removes_old_files(self, episode_tmpdir: Path) -> None:
        _make_episode(episode_tmpdir, "old1", age_days=120)
        _make_episode(episode_tmpdir, "old2", age_days=100)
        _make_episode(episode_tmpdir, "recent", age_days=1)
        removed = rotate_episodes(
            episode_tmpdir, retention_days=90, max_files=1000,
        )
        assert removed == 2
        survivors = list(episode_tmpdir.glob("episode_*.jsonl"))
        assert len(survivors) == 1
        assert survivors[0].name == "episode_recent.jsonl"

    def test_zero_retention_disables_age_cap(self, episode_tmpdir: Path) -> None:
        # retention_days=0 means "no age-based deletion" — useful for
        # purely count-based rotation policies.
        _make_episode(episode_tmpdir, "ancient", age_days=10000)
        removed = rotate_episodes(
            episode_tmpdir, retention_days=0, max_files=1000,
        )
        assert removed == 0


class TestCountCap:
    """Beyond max_files, oldest-first deletion until cap reached."""

    def test_trims_oldest_first(self, episode_tmpdir: Path) -> None:
        # 6 files, max_files=4 → 2 oldest should go
        for i, age in enumerate([10, 8, 6, 4, 2, 1]):
            _make_episode(episode_tmpdir, f"f{i}", age_days=age)
        removed = rotate_episodes(
            episode_tmpdir, retention_days=365, max_files=4,
        )
        assert removed == 2
        survivors = sorted(p.name for p in episode_tmpdir.glob("episode_*.jsonl"))
        # f0 (10d) and f1 (8d) are oldest — should have been removed.
        assert "episode_f0.jsonl" not in survivors
        assert "episode_f1.jsonl" not in survivors
        # f4 (2d) and f5 (1d) are newest — should survive.
        assert "episode_f4.jsonl" in survivors
        assert "episode_f5.jsonl" in survivors

    def test_under_cap_removes_nothing(self, episode_tmpdir: Path) -> None:
        for i in range(3):
            _make_episode(episode_tmpdir, f"f{i}", age_days=1)
        removed = rotate_episodes(
            episode_tmpdir, retention_days=365, max_files=10,
        )
        assert removed == 0


class TestSafety:
    """Robustness — missing dir, empty dir, mixed extensions."""

    def test_missing_dir_is_safe(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does-not-exist"
        # Should return 0, not raise.
        assert rotate_episodes(nonexistent) == 0

    def test_empty_dir_returns_zero(self, episode_tmpdir: Path) -> None:
        assert rotate_episodes(episode_tmpdir) == 0

    def test_only_touches_episode_files(self, episode_tmpdir: Path) -> None:
        # Non-matching files MUST be left alone.
        _make_episode(episode_tmpdir, "old", age_days=200)
        unrelated = episode_tmpdir / "unrelated.json"
        unrelated.write_text("{}", encoding="utf-8")
        rotate_episodes(episode_tmpdir, retention_days=90, max_files=1000)
        assert unrelated.exists()

    def test_combined_age_and_count_caps(self, episode_tmpdir: Path) -> None:
        # 3 ancient + 5 recent; retention=90d, max_files=3
        # Age pass kills 3 ancient. Count pass kills 2 oldest of recent.
        for i, age in enumerate([200, 200, 200]):
            _make_episode(episode_tmpdir, f"old{i}", age_days=age)
        for i, age in enumerate([30, 20, 10, 5, 2]):
            _make_episode(episode_tmpdir, f"new{i}", age_days=age)
        removed = rotate_episodes(
            episode_tmpdir, retention_days=90, max_files=3,
        )
        assert removed == 5
        survivors = sorted(p.name for p in episode_tmpdir.glob("episode_*.jsonl"))
        assert len(survivors) == 3
        # 3 newest of the recent batch should survive.
        assert "episode_new2.jsonl" in survivors  # 10d
        assert "episode_new3.jsonl" in survivors  # 5d
        assert "episode_new4.jsonl" in survivors  # 2d
