#!/usr/bin/env python3
"""
Smart Disruption Engine — ML-based parameter optimizer.

Takes a NetworkProfile and outputs optimal disruption parameters.
No more guess and check.

Architecture:
  1. Rule-based expert system (always available, zero dependencies)
  2. Gradient-boosted model (optional, trained on session history)
  3. Reinforcement feedback loop (learns from disruption outcomes)

The engine understands that different network conditions require
different approaches:
  - High-quality LAN connection → needs aggressive multi-module stacking
  - Flaky hotspot connection → light touch, just nudge it over the edge
  - Console on NAT → target UDP, exploit NAT keepalive sensitivity
  - Gaming PC on fast LAN → need disconnect + bandwidth cap + lag combo

Disruption Goals (user-selectable):
  - "desync"      → cause game state desynchronization
  - "lag"         → induce perceivable lag without full disconnect
  - "disconnect"  → kill the connection entirely
  - "throttle"    → degrade to minimum playable state
  - "chaos"       → maximum unpredictable disruption
"""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List
from app.logs.logger import log_info, log_error
from app.utils.helpers import mask_ip
@dataclass
class DisruptionRecommendation:
    """Output of the smart engine — a complete disruption configuration."""

    # Human-readable
    name: str = ""
    description: str = ""
    confidence: float = 0.0      # 0-1, how confident the engine is
    goal: str = ""               # what this achieves

    # Disruption config (same format as PRESETS in clumsy_control.py)
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)

    # Explanation for the UI
    reasoning: List[str] = field(default_factory=list)

    # Estimated effectiveness (0-100)
    estimated_effectiveness: float = 0.0

    def to_preset(self) -> dict:
        """Convert to DupeZ preset format."""
        return {
            "description": self.description,
            "methods": self.methods,
            "params": self.params,
        }

    def to_dict(self) -> dict:
        return asdict(self)
class SmartDisruptionEngine:
    """Maps network profiles to optimal disruption parameters.

    Usage:
        engine = SmartDisruptionEngine()
        profile = NetworkProfiler().profile("198.51.100.5")
        rec = engine.recommend(profile, goal="disconnect")
        # rec.methods, rec.params → feed directly into NativeWinDivertEngine
    """

    # Disruption goals
    GOALS = ["desync", "lag", "disconnect", "throttle", "chaos", "godmode", "auto"]

    def __init__(self, history_path: str = ""):
        if not history_path:
            from app.core.data_persistence import _resolve_data_directory
            history_path = os.path.join(_resolve_data_directory(), "session_history.json")
        self.history_path = history_path
        self._model = None  # Future: trained model
        self._load_history()

    def _load_history(self):
        """Load past session outcomes for feedback learning."""
        self._history = []
        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, 'r') as f:
                    self._history = json.load(f)
        except Exception as e:
            log_error(f"SmartEngine: failed to load history: {e}")

    def recommend(self, profile, goal: str = "auto",
                  intensity: float = 0.8) -> DisruptionRecommendation:
        """Generate optimal disruption recommendation.

        Args:
            profile: NetworkProfile from the profiler
            goal: One of GOALS — what the user wants to achieve
            intensity: 0.0-1.0 — how aggressive (0=gentle, 1=maximum)

        Returns:
            DisruptionRecommendation with methods, params, and reasoning
        """
        # Clamp intensity to valid range
        intensity = max(0.0, min(1.0, intensity))

        if goal == "auto":
            goal = self._infer_goal(profile)

        # Safe attribute access — guard against malformed profiles
        target_ip = getattr(profile, 'target_ip', 'unknown')
        quality = getattr(profile, 'quality_score', 50)

        log_info(f"SmartEngine: computing recommendation for {mask_ip(target_ip)} "
                 f"(goal={goal}, intensity={intensity:.1f}, "
                 f"quality={quality:.0f})")

        # Route to goal-specific strategy
        strategy_map = {
            "disconnect": self._strategy_disconnect,
            "lag":        self._strategy_lag,
            "desync":     self._strategy_desync,
            "throttle":   self._strategy_throttle,
            "chaos":      self._strategy_chaos,
            "godmode":    self._strategy_godmode,
        }

        # Normalize goal key (GUI sends "god mode", map uses "godmode")
        goal_key = goal.replace(" ", "")
        strategy_fn = strategy_map.get(goal_key, self._strategy_disconnect)
        rec = strategy_fn(profile, intensity)

        # Apply connection-specific adjustments
        self._adjust_for_connection(rec, profile, intensity)

        # Apply device-specific adjustments
        self._adjust_for_device(rec, profile)

        rec.goal = goal
        rec.confidence = self._compute_confidence(profile, rec)

        log_info(f"SmartEngine: recommendation → {rec.name} "
                 f"(methods={rec.methods}, confidence={rec.confidence:.0%}, "
                 f"effectiveness={rec.estimated_effectiveness:.0f}%)")

        return rec

    def recommend_multiple(self, profile, count: int = 3,
                           intensity: float = 0.8) -> List[DisruptionRecommendation]:
        """Generate multiple recommendations for different goals."""
        goals = ["disconnect", "lag", "desync", "throttle", "chaos"]
        recs = []
        for goal in goals[:count]:
            recs.append(self.recommend(profile, goal=goal, intensity=intensity))
        # Sort by estimated effectiveness
        recs.sort(key=lambda r: r.estimated_effectiveness, reverse=True)
        return recs

    # Goal Inference
    def _infer_goal(self, profile) -> str:
        """Infer the best goal based on network profile."""
        # Hotspot + console → usually want disconnect or desync for gaming
        if profile.connection_type == "hotspot" and profile.device_type == "console":
            return "disconnect"
        # Already lossy connection → lag is enough to tip it
        if profile.packet_loss_pct > 5 or profile.quality_score < 50:
            return "lag"
        # High quality connection → need heavy approach
        if profile.quality_score > 80:
            return "disconnect"
        return "disconnect"

    # Strategy: Disconnect
    def _strategy_disconnect(self, profile, intensity: float) -> DisruptionRecommendation:
        """Kill the connection entirely."""
        rec = DisruptionRecommendation(
            name="Smart Disconnect",
            description="Calculated disconnect — tuned to this connection's profile",
        )

        quality = profile.quality_score

        if quality > 75:
            # Strong connection — need to stack everything
            rec.methods = ["disconnect", "drop", "lag", "bandwidth", "throttle"]
            rec.params = {
                "disconnect_chance": 100,
                "drop_chance": self._scale(85, 99, intensity),
                "lag_delay": self._scale(1000, 3000, intensity),
                "bandwidth_limit": 1,
                "bandwidth_queue": 0,
                "throttle_chance": self._scale(80, 100, intensity),
                "throttle_frame": self._scale(300, 800, intensity),
                "throttle_drop": True,
                "direction": "both",
            }
            rec.reasoning = [
                f"Connection quality is high ({quality:.0f}/100) — aggressive stacking required",
                "Using 5-module chain: disconnect → drop → lag → bandwidth → throttle",
                f"Drop chance scaled to {rec.params['drop_chance']}% based on intensity",
                "Bandwidth capped to 1 KB/s to prevent recovery",
            ]
            rec.estimated_effectiveness = self._scale(75, 95, intensity)

        elif quality > 40:
            # Medium connection — moderate approach
            rec.methods = ["disconnect", "drop", "bandwidth", "throttle"]
            rec.params = {
                "disconnect_chance": 100,
                "drop_chance": self._scale(70, 95, intensity),
                "bandwidth_limit": self._scale(1, 5, 1 - intensity),
                "bandwidth_queue": 0,
                "throttle_chance": self._scale(60, 95, intensity),
                "throttle_frame": self._scale(200, 500, intensity),
                "throttle_drop": True,
                "direction": "both",
            }
            rec.reasoning = [
                f"Connection quality is moderate ({quality:.0f}/100)",
                "4-module chain sufficient: disconnect → drop → bandwidth → throttle",
                "Lower drop chance needed — connection already has weaknesses",
            ]
            rec.estimated_effectiveness = self._scale(80, 98, intensity)

        else:
            # Weak connection — light touch will kill it
            rec.methods = ["disconnect", "drop"]
            rec.params = {
                "disconnect_chance": 100,
                "drop_chance": self._scale(50, 80, intensity),
                "direction": "both",
            }
            rec.reasoning = [
                f"Connection quality is already poor ({quality:.0f}/100)",
                "Minimal disruption needed — 2-module chain is enough",
                f"Drop at {rec.params['drop_chance']}% will overwhelm the connection",
            ]
            rec.estimated_effectiveness = self._scale(90, 100, intensity)

        return rec

    # Strategy: Lag
    def _strategy_lag(self, profile, intensity: float) -> DisruptionRecommendation:
        """Induce perceivable lag without full disconnect."""
        rec = DisruptionRecommendation(
            name="Smart Lag",
            description="Calculated latency injection — keeps connection alive but unplayable",
        )

        # Scale lag based on existing RTT — lower RTT needs more added lag
        base_rtt = profile.avg_rtt_ms
        lo, hi = ((500,2000) if base_rtt < 10 else (300,1500) if base_rtt < 50 else (200,800))
        target_lag = self._scale(lo, hi, intensity)

        rec.methods = ["lag", "drop"]
        rec.params = {
            "lag_delay": int(target_lag),
            "drop_chance": self._scale(20, 60, intensity),
            "direction": "both",
        }
        rec.reasoning = [
            f"Target baseline RTT is {base_rtt:.0f}ms",
            f"Adding {target_lag:.0f}ms lag will make total RTT ~{base_rtt + target_lag:.0f}ms",
            f"Light drop ({rec.params['drop_chance']}%) adds packet-level chaos",
            "Connection stays alive but gameplay becomes impossible",
        ]
        rec.estimated_effectiveness = self._scale(70, 90, intensity)

        return rec

    # Strategy: Desync
    def _strategy_desync(self, profile, intensity: float) -> DisruptionRecommendation:
        """Cause game state desynchronization."""
        rec = DisruptionRecommendation(
            name="Smart Desync",
            description="Packet manipulation to break game state synchronization",
        )

        rec.methods = ["lag", "duplicate", "ood"]
        dup_count = int(self._scale(5, 25, intensity))
        rec.params = {
            "lag_delay": int(self._scale(300, 1200, intensity)),
            "duplicate_chance": self._scale(70, 95, intensity),
            "duplicate_count": dup_count,
            "ood_chance": self._scale(60, 90, intensity),
            "direction": "both",
        }
        rec.reasoning = [
            "Desync strategy: flood with duplicates + reorder + delay",
            f"Sending {dup_count}x copies of each packet at {rec.params['duplicate_chance']}% chance",
            "Out-of-order delivery confuses sequence-dependent game protocols",
            "Lag adds temporal desynchronization on top of packet chaos",
            "This is particularly effective against UDP-based game state sync",
        ]

        # Desync is more effective on UDP-heavy connections
        if profile.udp_pct > 60:
            rec.estimated_effectiveness = self._scale(80, 98, intensity)
            rec.reasoning.append(f"Target is {profile.udp_pct:.0f}% UDP — desync will be highly effective")
        else:
            rec.estimated_effectiveness = self._scale(60, 85, intensity)

        return rec

    # Strategy: Throttle
    def _strategy_throttle(self, profile, intensity: float) -> DisruptionRecommendation:
        """Degrade to minimum playable state."""
        rec = DisruptionRecommendation(
            name="Smart Throttle",
            description="Bandwidth degradation — starve the connection slowly",
        )

        # Scale bandwidth limit based on current estimated bandwidth
        if profile.estimated_bandwidth_kbps > 20000:
            bw_limit = self._scale(1, 50, 1 - intensity)
        else:
            bw_limit = self._scale(1, 20, 1 - intensity)

        rec.methods = ["bandwidth", "throttle"]
        rec.params = {
            "bandwidth_limit": max(1, int(bw_limit)),
            "bandwidth_queue": 0,
            "throttle_chance": self._scale(50, 90, intensity),
            "throttle_frame": self._scale(100, 500, intensity),
            "throttle_drop": True,
            "direction": "both",
        }
        rec.reasoning = [
            f"Target estimated bandwidth: {profile.estimated_bandwidth_kbps:.0f} Kbps",
            f"Capping to {rec.params['bandwidth_limit']} KB/s "
            f"({rec.params['bandwidth_limit'] * 8:.0f} Kbps) — "
            f"{profile.estimated_bandwidth_kbps / max(1, rec.params['bandwidth_limit']):.0f}x reduction",
            f"Throttle at {rec.params['throttle_chance']}% drops excess bursts",
        ]
        rec.estimated_effectiveness = self._scale(60, 85, intensity)

        return rec

    # Strategy: Chaos
    def _strategy_chaos(self, profile, intensity: float) -> DisruptionRecommendation:
        """Maximum unpredictable disruption — all modules."""
        rec = DisruptionRecommendation(
            name="Smart Chaos",
            description="All disruption modules activated — total network destruction",
        )

        rec.methods = ["disconnect", "drop", "lag", "duplicate",
                       "corrupt", "rst", "ood", "bandwidth", "throttle"]
        rec.params = {
            "drop_chance": self._scale(80, 99, intensity),
            "lag_delay": int(self._scale(800, 2500, intensity)),
            "duplicate_chance": self._scale(60, 90, intensity),
            "duplicate_count": int(self._scale(5, 15, intensity)),
            "tamper_chance": self._scale(40, 80, intensity),
            "rst_chance": self._scale(70, 95, intensity),
            "ood_chance": self._scale(60, 90, intensity),
            "bandwidth_limit": 1,
            "bandwidth_queue": 0,
            "throttle_chance": self._scale(80, 100, intensity),
            "throttle_frame": self._scale(300, 700, intensity),
            "throttle_drop": True,
            "direction": "both",
        }
        rec.reasoning = [
            "CHAOS MODE: Every disruption module activated simultaneously",
            f"9-module chain with {intensity:.0%} intensity across the board",
            "Packets are dropped, lagged, duplicated, corrupted, reordered, "
            "and RST-injected all at once",
            "Connection has near-zero chance of maintaining state",
        ]
        rec.estimated_effectiveness = self._scale(90, 100, intensity)

        return rec

    # Strategy: God Mode
    def _strategy_godmode(self, profile, intensity: float) -> DisruptionRecommendation:
        """Directional lag — freeze others' view of you while you keep moving.

        How it works:
          - Inbound packets (server → target) are lagged heavily.
            The target's game client stops receiving position updates about you.
            To them, you freeze in place or disappear.
          - Outbound packets (target → server) pass through untouched.
            Your actions (movement, shots, damage) register on the server
            in real time.

        The net effect: you can move freely and deal damage while being
        functionally invisible. When God Mode is deactivated, the
        target's client catches up — all delayed packets arrive at once
        and the game state reconciles.

        Intensity controls:
          - Low intensity (0.3): short lag, minimal desync
          - Medium (0.6): noticeable freeze, good for repositioning
          - High (1.0): long freeze + inbound drop, maximum invisibility
        """
        rec = DisruptionRecommendation(
            name="Smart God Mode",
            description="Directional lag — freeze their view, keep moving freely",
        )

        # Scale lag based on RTT — low-latency needs more lag to be noticeable
        base_rtt = profile.avg_rtt_ms
        lo, hi = ((1000,4000) if base_rtt < 20 else (800,3000) if base_rtt < 80 else (500,2000))
        lag_ms = int(self._scale(lo, hi, intensity))

        # At high intensity, also drop some inbound packets
        # This makes the freeze more aggressive — some server updates
        # never arrive at all, increasing desync
        drop_inbound = 0
        if intensity > 0.7:
            drop_inbound = int(self._scale(0, 40, (intensity - 0.7) / 0.3))

        # NAT keepalive interval: at high intensity we can reduce it (more
        # aggressive = fewer keepalives = harder freeze but more NAT risk).
        # At low intensity, keep default 800ms for safety.
        keepalive_ms = int(self._scale(800, 400, intensity))
        if intensity >= 0.95:
            keepalive_ms = 0  # max intensity disables keepalive entirely

        rec.methods = ["godmode"]
        rec.params = {
            "godmode_lag_ms": lag_ms,
            "godmode_drop_inbound_pct": drop_inbound,
            "godmode_keepalive_interval_ms": keepalive_ms,
            "direction": "both",
        }
        rec.reasoning = [
            "God Mode: inbound packets (server→target) lagged, outbound (target→server) pass through",
            f"Inbound lag set to {lag_ms}ms — target won't see you move for "
            f"~{lag_ms/1000:.1f}s at a time",
            f"Their outbound actions still register in real time on the server",
            f"NAT keepalive: 1 packet every {keepalive_ms}ms to prevent NAT table timeout"
            if keepalive_ms > 0 else
            "NAT keepalive DISABLED — maximum freeze but risk of NAT timeout on long sessions",
        ]

        if drop_inbound > 0:
            rec.reasoning.append(
                f"Aggressive mode: {drop_inbound}% of inbound packets dropped entirely "
                "for harder freeze")

        # God Mode is most effective on hotspot/ICS where you control the gateway
        if profile.connection_type == "hotspot":
            rec.estimated_effectiveness = self._scale(85, 99, intensity)
            rec.reasoning.append(
                "Hotspot detected — God Mode is maximally effective when you "
                "are the gateway (ICS/mobile hotspot, NETWORK_FORWARD layer)")
        else:
            rec.estimated_effectiveness = self._scale(70, 90, intensity)
            rec.reasoning.append(
                "Note: God Mode works best on hotspot/ICS where your machine "
                "is the gateway. On regular LAN, effectiveness depends on "
                "network topology.")

        return rec

    # Connection-specific adjustments
    # (param_key, scale_factor) pairs for hotspot reduction
    _HOTSPOT_SCALE = {"lag_delay": 0.7, "godmode_lag_ms": 0.8}

    def _adjust_for_connection(self, rec: DisruptionRecommendation,
                               profile, intensity: float):
        """Tune recommendation based on connection type."""
        if profile.connection_type == "hotspot":
            for key, factor in self._HOTSPOT_SCALE.items():
                if key in rec.params:
                    rec.params[key] = int(rec.params[key] * factor)
            if "drop_chance" in rec.params:
                rec.params["drop_chance"] = min(rec.params["drop_chance"],
                                                 self._scale(60, 90, intensity))
            rec.reasoning.append(
                "Adjusted for hotspot: reduced aggression (hotspot amplifies disruption)")
            rec.estimated_effectiveness = min(100, rec.estimated_effectiveness + 10)

        elif profile.connection_type == "lan":
            if "drop_chance" in rec.params:
                rec.params["drop_chance"] = min(100, rec.params["drop_chance"] + 5)
            rec.reasoning.append(
                "Adjusted for LAN: increased aggression (LAN connections are resilient)")

        elif profile.connection_type == "wan":
            rec.reasoning.append(
                "WAN connection detected — natural latency variability works in our favor")

    # Device-specific adjustments
    def _adjust_for_device(self, rec: DisruptionRecommendation, profile):
        """Tune recommendation based on device type."""
        if profile.device_type == "console":
            # Consoles have limited network stack recovery
            # They're more sensitive to out-of-order and duplicate packets
            if "duplicate" not in rec.methods and "desync" not in rec.goal:
                rec.methods.append("duplicate")
                rec.params.setdefault("duplicate_chance", 30)
                rec.params.setdefault("duplicate_count", 3)
            rec.reasoning.append(
                f"Adjusted for {profile.device_hint or 'console'}: "
                "added light duplication (consoles are sensitive to packet anomalies)")
            rec.estimated_effectiveness = min(100, rec.estimated_effectiveness + 5)

        elif profile.device_type == "mobile":
            # Mobile devices handle disruption poorly
            rec.reasoning.append(
                "Adjusted for mobile: these devices already struggle with packet loss")
            rec.estimated_effectiveness = min(100, rec.estimated_effectiveness + 10)

    # Confidence Score
    def _compute_confidence(self, profile, rec: DisruptionRecommendation) -> float:
        """How confident we are in this recommendation (0-1)."""
        confidence = 0.7 + sum(delta for cond, delta in [
            (profile.packets_received > 5, 0.1),
            (profile.jitter_ms > 0, 0.05),
            (len(profile.open_ports) > 0, 0.05),
            (profile.device_type != "unknown", 0.1),
        ] if cond)

        if self._history and any(
            h.get("device_type") == profile.device_type
            and h.get("connection_type") == profile.connection_type
            for h in self._history
        ):
            confidence += 0.1

        return min(1.0, confidence)

    # Utility
    @staticmethod
    def _scale(low: float, high: float, t: float) -> float:
        """Linear interpolation between low and high based on t (0-1)."""
        t = max(0.0, min(1.0, t))
        return low + (high - low) * t

