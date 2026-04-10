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

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import threading
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from app.logs.logger import log_info, log_error
from app.utils.helpers import mask_ip

__all__ = ["SessionRecord", "SessionTracker"]


# ── HMAC integrity for history file ──────────────────────────────────

def _get_hmac_key() -> bytes:
    """Machine-bound HMAC key with domain separation."""
    import platform
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default")),
        platform.machine(),
        "DupeZ-SessionTracker-v1",
    ]
    return hashlib.sha384("|".join(parts).encode("utf-8")).digest()


def _compute_hmac(data: bytes) -> str:
    return _hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()


def _verify_hmac(data: bytes, expected_hex: str) -> bool:
    computed = _hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()
    return _hmac.compare_digest(computed, expected_hex)

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

    def __init__(self, history_path: str = "") -> None:
        if not history_path:
            from app.core.data_persistence import _resolve_data_directory
            history_path = os.path.join(_resolve_data_directory(), "session_history.json")
        self.history_path = history_path
        self._active_sessions: Dict[str, SessionRecord] = {}
        self._history: List[dict] = []
        self._lock = threading.Lock()
        self._load_history()

    def _load_history(self) -> None:
        """Load session history from disk with HMAC integrity check."""
        try:
            if not os.path.exists(self.history_path):
                return

            with open(self.history_path, "rb") as f:
                raw = f.read()

            # HMAC verification
            hmac_path = self.history_path + ".hmac"
            if os.path.exists(hmac_path):
                try:
                    with open(hmac_path, "r", encoding="utf-8") as hf:
                        stored = hf.read().strip()
                    if not _verify_hmac(raw, stored):
                        log_error("SessionTracker: HMAC verification FAILED — "
                                  "possible tampering, resetting history")
                        self._history = []
                        return
                except Exception as e:
                    log_error(f"SessionTracker: HMAC check error: {e}")

            self._history = json.loads(raw.decode("utf-8"))
            log_info(f"SessionTracker: loaded {len(self._history)} historical sessions")
        except Exception as e:
            log_error(f"SessionTracker: failed to load history: {e}")
            self._history = []

    def _save_history(self) -> None:
        """Persist history to disk (atomic write). Uses current _history under no lock."""
        self._save_history_snapshot(self._history)

    def _save_history_snapshot(self, snapshot: list) -> None:
        """Persist a history snapshot to disk (atomic write + HMAC, lock-free)."""
        try:
            os.makedirs(os.path.dirname(self.history_path) or ".", exist_ok=True)
            raw_json = json.dumps(snapshot, indent=2)
            raw_bytes = raw_json.encode("utf-8")

            # Atomic write: tmp -> fsync -> replace
            tmp_path = self.history_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(raw_json)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.history_path)

            # Write companion HMAC
            hmac_path = self.history_path + ".hmac"
            hmac_tmp = hmac_path + ".tmp"
            try:
                with open(hmac_tmp, "w", encoding="utf-8") as hf:
                    hf.write(_compute_hmac(raw_bytes))
                    hf.flush()
                    os.fsync(hf.fileno())
                os.replace(hmac_tmp, hmac_path)
            except Exception as he:
                log_error(f"SessionTracker: HMAC write failed: {he}")

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
        from app.core.crypto import generate_token
        session_id = generate_token(8)  # 64-bit CSPRNG hex token

        record = SessionRecord(
            session_id=session_id,
            timestamp=time.time(),
            target_ip=mask_ip(profile.target_ip),
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

        with self._lock:
            self._active_sessions[session_id] = record
        log_info(f"SessionTracker: started session {session_id} "
                 f"({recommendation.name} → {record.target_ip})")
        return session_id

    def end_session(self, session_id: str, user_rating: int = 0,
                    notes: str = "") -> None:
        """Record the end of a disruption session.

        Args:
            session_id: ID returned by start_session
            user_rating: 0-5 (0=unrated, 1=didn't work, 5=perfect)
            notes: Optional user notes
        """
        with self._lock:
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

        # Append to history (thread-safe), cap at 500 entries.
        # Copy history snapshot under lock, then save outside lock to avoid
        # blocking callers during disk I/O.
        with self._lock:
            self._history.append(asdict(record))
            if len(self._history) > 500:
                self._history = self._history[-400:]
            history_snapshot = list(self._history)
        self._save_history_snapshot(history_snapshot)

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
    def _mode(items: list) -> str:
        """Return most common item."""
        if not items:
            return "unknown"
        from collections import Counter
        return Counter(items).most_common(1)[0][0]

