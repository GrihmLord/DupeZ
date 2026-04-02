#!/usr/bin/env python3
"""
Session Tracker — logs disruption sessions and outcomes for feedback learning.

Every time a disruption runs, we record:
  - The NetworkProfile of the target
  - The DisruptionRecommendation that was used
  - The outcome (user-reported or auto-detected effectiveness)
  - Duration, timestamp, etc.

This data feeds back into SmartDisruptionEngine to improve future
recommendations. Over time, the system learns what works against
different connection types and device profiles.
"""

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional
from app.logs.logger import log_info, log_error


@dataclass
class SessionRecord:
    """A single disruption session record."""

    # Identifiers
    session_id: str = ""
    timestamp: float = 0.0
    duration_seconds: float = 0.0

    # Target info
    target_ip: str = ""
    device_type: str = ""
    device_hint: str = ""
    connection_type: str = ""

    # Network profile snapshot
    avg_rtt_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    quality_score: float = 0.0
    estimated_bandwidth_kbps: float = 0.0

    # What was used
    goal: str = ""
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)
    recommendation_name: str = ""
    confidence: float = 0.0
    intensity: float = 0.0

    # Outcome (1-5 rating, or auto-detected)
    user_rating: int = 0          # 0=unrated, 1=ineffective, 5=perfect
    auto_effectiveness: float = 0.0  # 0-100 auto-detected

    # Notes
    notes: str = ""


class SessionTracker:
    """Tracks disruption sessions and maintains history for learning.

    Usage:
        tracker = SessionTracker()
        session_id = tracker.start_session(profile, recommendation)
        # ... disruption runs ...
        tracker.end_session(session_id, user_rating=4)
        history = tracker.get_history(limit=50)
    """

    def __init__(self, history_path: str = "app/data/session_history.json"):
        self.history_path = history_path
        self._active_sessions: Dict[str, SessionRecord] = {}
        self._history: List[dict] = []
        self._load_history()

    def _load_history(self):
        """Load session history from disk."""
        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, 'r') as f:
                    self._history = json.load(f)
                log_info(f"SessionTracker: loaded {len(self._history)} historical sessions")
        except Exception as e:
            log_error(f"SessionTracker: failed to load history: {e}")
            self._history = []

    def _save_history(self):
        """Persist history to disk (atomic write)."""
        try:
            os.makedirs(os.path.dirname(self.history_path) or ".", exist_ok=True)
            tmp_path = self.history_path + ".tmp"
            with open(tmp_path, 'w') as f:
                json.dump(self._history, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.history_path)
        except Exception as e:
            log_error(f"SessionTracker: failed to save history: {e}")

    def start_session(self, profile, recommendation,
                      intensity: float = 0.8) -> str:
        """Record the start of a disruption session.

        Args:
            profile: NetworkProfile of the target
            recommendation: DisruptionRecommendation being applied

        Returns:
            session_id (string)
        """
        import uuid
        session_id = str(uuid.uuid4())[:8]

        record = SessionRecord(
            session_id=session_id,
            timestamp=time.time(),
            target_ip=self._mask_ip(profile.target_ip),
            device_type=profile.device_type,
            device_hint=profile.device_hint,
            connection_type=profile.connection_type,
            avg_rtt_ms=profile.avg_rtt_ms,
            jitter_ms=profile.jitter_ms,
            packet_loss_pct=profile.packet_loss_pct,
            quality_score=profile.quality_score,
            estimated_bandwidth_kbps=profile.estimated_bandwidth_kbps,
            goal=recommendation.goal,
            methods=recommendation.methods,
            params=recommendation.params,
            recommendation_name=recommendation.name,
            confidence=recommendation.confidence,
            intensity=intensity,
        )

        self._active_sessions[session_id] = record
        log_info(f"SessionTracker: started session {session_id} "
                 f"({recommendation.name} → {profile.target_ip})")
        return session_id

    def end_session(self, session_id: str, user_rating: int = 0,
                    notes: str = ""):
        """Record the end of a disruption session.

        Args:
            session_id: ID returned by start_session
            user_rating: 0-5 (0=unrated, 1=didn't work, 5=perfect)
            notes: Optional user notes
        """
        record = self._active_sessions.pop(session_id, None)
        if not record:
            log_error(f"SessionTracker: unknown session {session_id}")
            return

        record.duration_seconds = time.time() - record.timestamp
        record.user_rating = user_rating
        record.notes = notes

        # Auto-compute effectiveness from duration and rating
        if user_rating > 0:
            record.auto_effectiveness = user_rating * 20  # 1→20, 5→100
        elif record.duration_seconds > 30:
            # If it ran for a while, assume it was somewhat effective
            record.auto_effectiveness = min(80, 30 + record.duration_seconds * 0.5)

        # Append to history
        self._history.append(asdict(record))
        self._save_history()

        log_info(f"SessionTracker: ended session {session_id} "
                 f"(duration={record.duration_seconds:.0f}s, "
                 f"rating={user_rating}/5, "
                 f"effectiveness={record.auto_effectiveness:.0f}%)")

    def get_history(self, limit: int = 50,
                    device_type: str = None,
                    connection_type: str = None) -> List[dict]:
        """Get session history, optionally filtered."""
        results = self._history
        if device_type:
            results = [r for r in results if r.get("device_type") == device_type]
        if connection_type:
            results = [r for r in results
                       if r.get("connection_type") == connection_type]
        # Most recent first
        results = sorted(results, key=lambda r: r.get("timestamp", 0),
                         reverse=True)
        return results[:limit]

    def get_best_config_for(self, device_type: str = None,
                            connection_type: str = None) -> Optional[dict]:
        """Find the highest-rated configuration for similar targets."""
        candidates = self.get_history(
            limit=100, device_type=device_type,
            connection_type=connection_type
        )
        # Filter to rated sessions
        rated = [r for r in candidates if r.get("user_rating", 0) >= 4]
        if not rated:
            return None

        # Return the highest rated
        best = max(rated, key=lambda r: (r.get("user_rating", 0),
                                          r.get("auto_effectiveness", 0)))
        return {
            "methods": best.get("methods", []),
            "params": best.get("params", {}),
            "rating": best.get("user_rating", 0),
            "effectiveness": best.get("auto_effectiveness", 0),
        }

    def get_stats(self) -> dict:
        """Get aggregate statistics about session history."""
        if not self._history:
            return {"total_sessions": 0}

        rated = [r for r in self._history if r.get("user_rating", 0) > 0]
        return {
            "total_sessions": len(self._history),
            "rated_sessions": len(rated),
            "avg_rating": (sum(r["user_rating"] for r in rated) / len(rated)
                           if rated else 0),
            "avg_duration": (sum(r.get("duration_seconds", 0)
                                 for r in self._history) / len(self._history)),
            "most_used_goal": self._mode([r.get("goal", "") for r in self._history]),
            "most_effective_goal": (
                self._mode([r.get("goal", "") for r in rated
                            if r.get("user_rating", 0) >= 4])
                if rated else "unknown"
            ),
        }

    @staticmethod
    def _mask_ip(ip: str) -> str:
        """Mask the last octet for privacy in logs."""
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
        return ip

    @staticmethod
    def _mode(items: list) -> str:
        """Return most common item."""
        if not items:
            return "unknown"
        from collections import Counter
        return Counter(items).most_common(1)[0][0]
