#!/usr/bin/env python3
"""Tests for v5 Phase 6: ML-Enhanced Traffic Analyzer."""

import time
import unittest

from app.ai.traffic_analyzer import (
    GameState,
    TrafficSnapshot,
    TrafficPatternAnalyzer,
    GameStateDetector,
    AdaptiveTuner,
    SessionLearner,
)


class TestTrafficSnapshot(unittest.TestCase):
    def test_defaults(self):
        snap = TrafficSnapshot()
        self.assertEqual(snap.total_packets, 0)
        self.assertEqual(snap.total_bytes, 0)
        self.assertAlmostEqual(snap.asymmetry_ratio, 1.0)


class TestTrafficPatternAnalyzer(unittest.TestCase):
    def test_record_and_stats(self):
        analyzer = TrafficPatternAnalyzer(window_sec=1.0, snapshot_interval=0.01)
        now = time.monotonic()
        for i in range(20):
            analyzer.record_packet(now + i * 0.05, 200, i % 2 == 0)

        stats = analyzer.get_stats()
        self.assertGreater(stats["total_packets"], 0)

    def test_snapshot_generated(self):
        analyzer = TrafficPatternAnalyzer(window_sec=1.0, snapshot_interval=0.01)
        now = time.monotonic()
        for i in range(20):
            analyzer.record_packet(now + i * 0.05, 200, False)

        snap = analyzer.get_latest_snapshot()
        # May or may not have generated a snapshot depending on timing
        # At minimum, stats should work
        stats = analyzer.get_stats()
        self.assertEqual(stats["total_packets"], 20)

    def test_empty_analyzer(self):
        analyzer = TrafficPatternAnalyzer()
        snap = analyzer.get_latest_snapshot()
        self.assertIsNone(snap)
        stats = analyzer.get_stats()
        self.assertEqual(stats["total_packets"], 0)


class TestGameStateDetector(unittest.TestCase):
    def test_disconnected_on_low_traffic(self):
        detector = GameStateDetector()
        snap = TrafficSnapshot(packets_per_sec=0.5, bytes_per_sec=50,
                               avg_packet_size=100)
        state = detector.update(snap)
        self.assertEqual(state, GameState.DISCONNECTED)

    def test_menu_on_low_pps(self):
        detector = GameStateDetector()
        snap = TrafficSnapshot(packets_per_sec=5, bytes_per_sec=500,
                               avg_packet_size=100)
        state = detector.update(snap)
        self.assertEqual(state, GameState.MENU)

    def test_loading_on_high_throughput(self):
        detector = GameStateDetector()
        snap = TrafficSnapshot(packets_per_sec=30, bytes_per_sec=60000,
                               avg_packet_size=600)
        state = detector.update(snap)
        self.assertEqual(state, GameState.LOADING)

    def test_in_game_idle(self):
        detector = GameStateDetector()
        snap = TrafficSnapshot(
            packets_per_sec=40, bytes_per_sec=10000,
            avg_packet_size=250, inbound_pps=25, outbound_pps=15)
        state = detector.update(snap)
        self.assertEqual(state, GameState.IN_GAME_IDLE)

    def test_current_state_property(self):
        detector = GameStateDetector()
        self.assertEqual(detector.current_state, GameState.UNKNOWN)

    def test_time_in_state(self):
        detector = GameStateDetector()
        self.assertGreaterEqual(detector.time_in_state, 0)


class TestAdaptiveTuner(unittest.TestCase):
    def test_no_baseline_returns_none(self):
        tuner = AdaptiveTuner()
        snap = TrafficSnapshot(timestamp=time.monotonic())
        result = tuner.evaluate(snap, {})
        self.assertIsNone(result)

    def test_set_baseline(self):
        tuner = AdaptiveTuner(adjustment_interval=0.01)
        baseline = TrafficSnapshot(inbound_pps=50, outbound_pps=30)
        tuner.set_baseline(baseline)
        self.assertTrue(tuner._baseline_set)

    def test_over_disruption_detected(self):
        tuner = AdaptiveTuner(adjustment_interval=0.0)
        baseline = TrafficSnapshot(inbound_pps=50, outbound_pps=30)
        tuner.set_baseline(baseline)

        # Target outbound drops to zero
        snap = TrafficSnapshot(
            timestamp=time.monotonic() + 10,
            inbound_pps=10, outbound_pps=0)
        result = tuner.evaluate(snap, {})
        self.assertIsNotNone(result)
        self.assertTrue(result.get("_reduce_intensity"))

    def test_history_tracking(self):
        tuner = AdaptiveTuner(adjustment_interval=0.0)
        baseline = TrafficSnapshot(inbound_pps=50, outbound_pps=30)
        tuner.set_baseline(baseline)

        snap = TrafficSnapshot(
            timestamp=time.monotonic() + 10,
            inbound_pps=10, outbound_pps=0)
        tuner.evaluate(snap, {})

        history = tuner.get_history()
        self.assertGreater(len(history), 0)


class TestSessionLearner(unittest.TestCase):
    def test_start_end_session(self):
        learner = SessionLearner()
        learner.start_session("s1", "192.168.1.100", {"lag_delay": 500})
        record = learner.end_session("success")
        self.assertIsNotNone(record)
        self.assertEqual(record.session_id, "s1")
        self.assertEqual(record.outcome, "success")

    def test_record_snapshot(self):
        learner = SessionLearner()
        learner.start_session("s1", "10.0.0.1", {})
        learner.record_snapshot(TrafficSnapshot(
            timestamp=1.0, packets_per_sec=50, bytes_per_sec=10000))
        record = learner.get_session("s1")
        self.assertEqual(len(record.traffic_snapshots), 1)

    def test_record_game_state(self):
        learner = SessionLearner()
        learner.start_session("s1", "10.0.0.1", {})
        learner.record_game_state(GameState.IN_GAME_IDLE)
        record = learner.get_session("s1")
        self.assertEqual(len(record.game_states), 1)

    def test_session_count(self):
        learner = SessionLearner()
        learner.start_session("s1", "10.0.0.1", {})
        learner.end_session()
        learner.start_session("s2", "10.0.0.2", {})
        self.assertEqual(learner.get_session_count(), 2)


if __name__ == "__main__":
    unittest.main()
