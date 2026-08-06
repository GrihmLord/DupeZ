"""Correctness tests for episode summaries and cache isolation."""

from __future__ import annotations

import json

import pytest

from app.ai.learning_loop import LearningLoop, _summarize_episode


def _event(ts: float, name: str, **payload) -> str:
    return json.dumps({
        "kind": "event",
        "ts": ts,
        "name": name,
        "payload": payload,
    })


def _write_episode(path, *, network: str, success: bool) -> None:
    rows = [
        _event(
            10.0,
            "engine_start",
            target_profile="ps5",
            network_class=network,
            goal="lag",
            direction="both",
            methods=["lag"],
            params={"lag_delay": 900},
        ),
        _event(12.0, "cut_start"),
        _event(15.0, "cut_end"),
        _event(15.1, "outcome", success=success),
        _event(16.0, "engine_stop", max_cut_state="degraded"),
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_summary_uses_actual_cut_window_and_engine_params(tmp_path) -> None:
    path = tmp_path / "episode_one.jsonl"
    path.write_text(
        "\n".join([
            _event(
                10.0,
                "engine_start",
                target_profile="ps5",
                network_class="hotspot",
                goal="lag",
                direction="both",
                methods=["lag"],
                params={"lag_delay": 1200},
            ),
            _event(20.0, "cut_start"),
            _event(24.0, "cut_end"),
            _event(30.0, "engine_stop"),
        ]) + "\n",
        encoding="utf-8",
    )

    summary = _summarize_episode(path)
    assert summary is not None
    assert summary.start_ts == 20.0
    assert summary.duration_s == 4.0
    assert summary.params == {"lag_delay": 1200}


def test_cache_refreshes_when_existing_jsonl_is_appended(tmp_path) -> None:
    path = tmp_path / "episode_append.jsonl"
    path.write_text(
        "\n".join([
            _event(
                1.0,
                "engine_start",
                target_profile="ps5",
                network_class="hotspot",
                goal="lag",
                direction="both",
                methods=["lag"],
            ),
            _event(2.0, "cut_start"),
        ]) + "\n",
        encoding="utf-8",
    )
    loop = LearningLoop(tmp_path)
    assert loop.all_episodes()[0].outcome is None

    with path.open("a", encoding="utf-8") as stream:
        stream.write(_event(4.0, "outcome", success=True) + "\n")
        stream.write(_event(5.0, "engine_stop") + "\n")

    refreshed = loop.all_episodes()[0]
    assert refreshed.outcome is True
    assert refreshed.duration_s == 3.0


def test_recommendations_are_isolated_by_network_class(tmp_path) -> None:
    for index in range(5):
        _write_episode(
            tmp_path / f"episode_hotspot_{index}.jsonl",
            network="hotspot",
            success=True,
        )
        _write_episode(
            tmp_path / f"episode_lan_{index}.jsonl",
            network="lan",
            success=False,
        )

    loop = LearningLoop(tmp_path)
    hotspot = loop.recommend("ps5", "lag", "hotspot")
    lan = loop.recommend("ps5", "lag", "lan")
    assert hotspot is not None and lan is not None
    assert hotspot.success_rate == pytest.approx(1.0)
    assert lan.success_rate == pytest.approx(0.0)
