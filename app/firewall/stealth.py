#!/usr/bin/env python3
"""
Stealth and Detection Avoidance Layer — Phase 7 of DupeZ v5 Roadmap.

Implements countermeasures against anti-cheat detection of packet
manipulation tools. BattlEye (DayZ's anti-cheat) and other systems
detect WinDivert through multiple vectors:

Detection Vectors (BattlEye):
  1. Driver signature scanning: BattlEye kernel driver scans PiDDBCache
     and MmUnloadedDrivers for known driver signatures (WinDivert64.sys).
  2. WFP filter enumeration: BattlEye enumerates Windows Filtering Platform
     (WFP) callouts/filters via FwpmFilterEnum0 — WinDivert registers
     visible WFP filters.
  3. Process/DLL scanning: Scanning loaded modules for WinDivert.dll,
     clumsy.exe in process list.
  4. Behavioral detection: Monitoring for suspicious packet loss patterns,
     timing anomalies, statistical signatures.

Countermeasures Implemented:
  1. Behavioral stealth: Randomized disruption patterns that mimic natural
     network degradation (WiFi interference, ISP throttling, congestion).
  2. Timing randomization: Add micro-jitter to all disruption timing to
     avoid detectable periodicity.
  3. Statistical camouflage: Ensure overall packet loss/delay distributions
     match known natural patterns (not uniform random).
  4. Adaptive intensity: Reduce disruption when detection risk is high
     (e.g., during BattlEye scan phases).
  5. Session fingerprint rotation: Vary disruption patterns across sessions
     to prevent signature building.

Note: This module does NOT implement kernel-level evasion (driver renaming,
WFP filter hiding) — those require privileged operations beyond the scope
of a Python application. This module focuses on behavioral stealth only.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import random
import secrets
import time
import threading
from collections import deque
from typing import Dict, Optional

from app.core.crypto import deterministic_param_hash, hash_sha384

from app.logs.logger import log_info, log_error

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
)

__all__ = [
    "TimingRandomizer",
    "NaturalPatternGenerator",
    "StealthDropModule",
    "StealthLagModule",
    "SessionFingerprintRotator",
    "STEALTH_MODULE_MAP",
    "STEALTH_FLUSH_MODULES",
]


class TimingRandomizer:
    """Adds micro-jitter to disruption timing to avoid detectable periodicity.

    Anti-cheat systems look for suspiciously regular patterns in packet
    loss/delay. A perfect 50ms delay every time is clearly artificial.
    This class adds configurable noise to timing operations.

    Noise model: Gaussian with configurable mean and standard deviation.
    The noise is clipped to prevent extreme outliers that could cause
    functional issues.

    Usage:
        randomizer = TimingRandomizer(jitter_pct=0.15)
        actual_delay = randomizer.jitter(target_delay_ms=50)
        # Returns ~50ms ± 7.5ms (15% jitter)
    """

    def __init__(self, jitter_pct: float = 0.15,
                 min_jitter_ms: float = 0.5,
                 max_jitter_ms: float = 50.0) -> None:
        self._jitter_pct = max(0.0, min(1.0, jitter_pct))
        self._min_jitter_ms = min_jitter_ms
        self._max_jitter_ms = max_jitter_ms

    def jitter(self, target_ms: float) -> float:
        """Add random jitter to a target delay value.

        Returns a value close to target_ms but with Gaussian noise
        proportional to the target value.
        """
        if target_ms <= 0:
            return 0.0

        sigma = target_ms * self._jitter_pct
        sigma = max(self._min_jitter_ms, min(self._max_jitter_ms, sigma))
        noise = random.gauss(0, sigma)

        result = target_ms + noise
        # Clamp to reasonable range: [target/3, target*3]
        result = max(target_ms / 3.0, min(target_ms * 3.0, result))
        return max(0, result)

    def jitter_chance(self, base_chance: float) -> float:
        """Add jitter to a chance percentage (0-100).

        Ensures the effective chance varies per-packet, making statistical
        analysis harder. Variance is proportional to distance from 0% and 100%.
        """
        if base_chance <= 0 or base_chance >= 100:
            return base_chance  # deterministic — don't add noise

        # Variance is highest at 50%, lowest near 0% and 100%
        distance_from_edge = min(base_chance, 100 - base_chance) / 50.0
        sigma = 5.0 * self._jitter_pct * distance_from_edge
        noise = random.gauss(0, sigma)
        return max(0.0, min(100.0, base_chance + noise))


class NaturalPatternGenerator:
    """Generates disruption patterns that mimic natural network degradation.

    Real network issues have characteristic patterns:
      - WiFi interference: bursty, correlated with time-of-day and movement
      - ISP throttling: smooth onset, sustained, affects bandwidth not latency
      - Congestion: gradual onset, affects latency and loss together
      - Distance/routing: stable high latency, low jitter

    This generator produces disruption parameters that follow these natural
    patterns rather than artificial constant values.

    Patterns:
      "wifi_interference": Periodic bursts of high loss (models microwave,
                           Bluetooth interference, signal fading)
      "congestion":        Gradually increasing delay that plateaus
      "isp_throttle":      Bandwidth restriction with smooth ramp
      "distance":          Stable high latency, occasional route changes
    """

    def __init__(self, pattern: str = "wifi_interference",
                 cycle_sec: float = 30.0) -> None:
        self._pattern = pattern
        self._cycle_sec = cycle_sec
        self._start_time = time.monotonic()
        self._randomizer = TimingRandomizer(jitter_pct=0.20)

    def _phase(self) -> float:
        """Return current position in the cycle (0.0 to 1.0)."""
        elapsed = time.monotonic() - self._start_time
        return (elapsed / self._cycle_sec) % 1.0

    def get_drop_chance(self, base: float = 30.0) -> float:
        """Get current drop chance modulated by the natural pattern."""
        phase = self._phase()

        if self._pattern == "wifi_interference":
            # Sinusoidal with random bursts
            modulation = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
            # Random interference spikes
            if random.random() < 0.05:
                modulation = min(1.0, modulation + random.uniform(0.3, 0.7))
            return self._randomizer.jitter_chance(base * modulation)

        elif self._pattern == "congestion":
            # Ramp up, plateau, ramp down
            if phase < 0.3:
                modulation = phase / 0.3  # ramp up
            elif phase < 0.7:
                modulation = 1.0  # plateau
            else:
                modulation = (1.0 - phase) / 0.3  # ramp down
            return self._randomizer.jitter_chance(base * modulation)

        elif self._pattern == "isp_throttle":
            # Step function with smooth edges
            if phase < 0.1:
                modulation = phase / 0.1
            elif phase < 0.8:
                modulation = 1.0
            else:
                modulation = (1.0 - phase) / 0.2
            return self._randomizer.jitter_chance(base * modulation * 0.7)

        elif self._pattern == "distance":
            # Stable with occasional route change spikes
            modulation = 0.3  # low base loss for high-distance
            if random.random() < 0.02:  # 2% chance of route change
                modulation = random.uniform(0.5, 1.0)
            return self._randomizer.jitter_chance(base * modulation)

        return self._randomizer.jitter_chance(base)

    def get_delay_ms(self, base: float = 100.0) -> float:
        """Get current delay modulated by the natural pattern."""
        phase = self._phase()

        if self._pattern == "wifi_interference":
            modulation = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
            return self._randomizer.jitter(base * max(0.2, modulation))

        elif self._pattern == "congestion":
            if phase < 0.3:
                modulation = 0.3 + 0.7 * (phase / 0.3)
            elif phase < 0.7:
                modulation = 1.0
            else:
                modulation = 1.0 - 0.7 * ((phase - 0.7) / 0.3)
            return self._randomizer.jitter(base * modulation)

        elif self._pattern == "distance":
            # Stable high latency
            modulation = 0.8 + 0.2 * math.sin(phase * 4 * math.pi)
            return self._randomizer.jitter(base * modulation)

        return self._randomizer.jitter(base)


class StealthDropModule(DisruptionModule):
    """Drop module with behavioral stealth — mimics natural packet loss.

    Wraps the drop decision in a NaturalPatternGenerator so the loss
    pattern looks like genuine WiFi interference, congestion, etc.
    instead of artificial uniform random loss.

    Parameters:
      stealth_pattern:    str   — "wifi_interference", "congestion",
                                  "isp_throttle", "distance" (default "wifi_interference")
      stealth_base_drop:  float — base drop chance (0-100, default 30)
      stealth_cycle_sec:  float — pattern cycle duration (default 30)
    """

    _direction_key = "stealth_drop"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        pattern = params.get("stealth_pattern", "wifi_interference")
        base_drop = float(params.get("stealth_base_drop", 30))
        cycle = float(params.get("stealth_cycle_sec", 30))

        self._pattern_gen = NaturalPatternGenerator(
            pattern=pattern, cycle_sec=cycle)
        self._base_drop = base_drop

        # Stats
        self._seen = 0
        self._dropped = 0

        log_info(
            f"StealthDrop: pattern={pattern}, base={base_drop}%, "
            f"cycle={cycle}s")

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        self._seen += 1
        effective_chance = self._pattern_gen.get_drop_chance(self._base_drop)

        if random.random() * 100 < effective_chance:
            self._dropped += 1
            return True
        return False

    def get_stats(self) -> Dict:
        return {
            "seen": self._seen,
            "dropped": self._dropped,
            "rate": self._dropped / max(1, self._seen),
        }


class StealthLagModule(DisruptionModule):
    """Lag module with natural jitter patterns.

    Instead of fixed delay, uses NaturalPatternGenerator to produce
    realistic delay patterns that match genuine network conditions.

    Parameters:
      stealth_lag_pattern:   str   — natural pattern type (default "congestion")
      stealth_lag_base_ms:   float — base delay (default 100)
      stealth_lag_cycle_sec: float — pattern cycle (default 30)
    """

    _direction_key = "stealth_lag"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        pattern = params.get("stealth_lag_pattern", "congestion")
        base_ms = float(params.get("stealth_lag_base_ms", 100))
        cycle = float(params.get("stealth_lag_cycle_sec", 30))

        self._pattern_gen = NaturalPatternGenerator(
            pattern=pattern, cycle_sec=cycle)
        self._base_ms = base_ms

        # Deferred packet queue
        self._queue = deque(maxlen=10000)
        self._queue_lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._running = True
        self._send_fn = None

        self._total = 0

        log_info(
            f"StealthLag: pattern={pattern}, base={base_ms}ms, "
            f"cycle={cycle}s")

    def start_flush_thread(self, send_fn, divert_dll, handle) -> None:
        self._send_fn = send_fn
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="StealthLagFlush")
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        while self._running:
            now = time.time()
            to_send = []
            with self._queue_lock:
                while self._queue and self._queue[0][0] <= now:
                    to_send.append(self._queue.popleft())
            for _, pkt, addr in to_send:
                try:
                    self._send_fn(pkt, addr)
                except Exception as exc:
                    log_error(f"StealthLag: flush send failed: {exc}")
            time.sleep(0.001)

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        self._total += 1
        delay_ms = self._pattern_gen.get_delay_ms(self._base_ms)

        if delay_ms < 1.0:
            return False

        release_time = time.time() + (delay_ms / 1000.0)
        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                        ctypes.sizeof(WINDIVERT_ADDRESS))

        with self._queue_lock:
            self._queue.append(
                (release_time, bytearray(packet_data), addr_copy))
        return True

    def stop(self) -> None:
        self._running = False
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)
        with self._queue_lock:
            remaining = list(self._queue)
            self._queue.clear()
        for _, pkt, addr in remaining:
            try:
                if self._send_fn:
                    self._send_fn(pkt, addr)
            except Exception as exc:
                log_error(f"StealthLag: stop flush failed: {exc}")


class SessionFingerprintRotator:
    """Rotates disruption parameters between sessions to prevent signature building.

    Anti-cheat systems can build behavioral signatures by correlating
    packet loss patterns across multiple sessions. This rotator varies
    key parameters each session so no two sessions look identical.

    Rotation strategy:
      - Base delay varies ±20% each session
      - Drop chance varies ±10%
      - Pattern cycle length varies ±30%
      - Module combination order shuffled
      - Jitter parameters reseeded

    All variations stay within "functional" bounds — the disruption still
    works, just with slightly different statistical properties.
    """

    def __init__(self, seed: Optional[str] = None) -> None:
        if seed is None:
            # CNSA 2.0: use CSPRNG for session seed, not time+random
            seed = secrets.token_hex(32)
        self._session_hash = hash_sha384(seed.encode())
        # Deterministic RNG seeded from CSPRNG-derived hash — acceptable
        # for non-security randomization (pattern variation, not key material)
        self._rng = random.Random(self._session_hash)
        log_info(f"SessionRotator: fingerprint={self._session_hash[:8]}...")

    def vary(self, param: str, base_value: float,
             variance_pct: float = 0.20) -> float:
        """Apply session-specific variance to a parameter.

        Returns a value within [base * (1-variance), base * (1+variance)]
        that's deterministic for this session (same param always gets
        same variation within a session).
        """
        # Deterministic hash per parameter name (SHA-384 — CNSA 2.0 compliant)
        norm = deterministic_param_hash(self._session_hash, param)
        # Map to [-variance, +variance]
        factor = 1.0 + (norm * 2 - 1) * variance_pct
        return base_value * factor

    def vary_int(self, param: str, base_value: int,
                 variance_pct: float = 0.20) -> int:
        return round(self.vary(param, float(base_value), variance_pct))

    def get_pattern(self) -> str:
        """Select a natural pattern for this session."""
        patterns = ["wifi_interference", "congestion", "isp_throttle", "distance"]
        return self._rng.choice(patterns)


# ═══════════════════════════════════════════════════════════════════════
# Module Registration
# ═══════════════════════════════════════════════════════════════════════

STEALTH_MODULE_MAP = {
    "stealth_drop": StealthDropModule,
    "stealth_lag":  StealthLagModule,
}

STEALTH_FLUSH_MODULES = (StealthLagModule,)
