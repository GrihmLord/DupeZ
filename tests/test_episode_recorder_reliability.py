"""Reliability and path-safety tests for episode recording."""

from __future__ import annotations

from app.ai.episode_recorder import EpisodeRecorder


def test_recorders_started_together_never_share_a_file(tmp_path) -> None:
    first = EpisodeRecorder(tmp_path, session_tag="same")
    second = EpisodeRecorder(tmp_path, session_tag="same")
    try:
        assert first.path != second.path
        assert first.path.parent == tmp_path
        assert second.path.parent == tmp_path
    finally:
        first.stop()
        second.stop()


def test_session_tag_cannot_escape_episode_directory(tmp_path) -> None:
    recorder = EpisodeRecorder(tmp_path, session_tag="../../outside\\bad:name")
    try:
        assert recorder.path.parent == tmp_path
        assert ".." not in recorder.path.name
        assert "/" not in recorder.path.name
        assert "\\" not in recorder.path.name
    finally:
        recorder.stop()
