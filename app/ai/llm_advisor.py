#!/usr/bin/env python3
"""
LLM Advisor — natural-language disruption tuning via local or remote LLM.

Connects to:
  1. Ollama (local) — run Mistral 7B, Llama, etc. on your machine
  2. Any OpenAI-compatible API — remote hosted models
  3. Fallback — rule-based interpretation when no LLM is available

The advisor translates natural language requests into disruption configs:
  "I want to desync a PS5 on my hotspot playing DayZ"
    → {methods: [lag, duplicate, ood], params: {lag_delay: 800, ...}}

It also explains WHY certain settings work and can answer questions
about network disruption theory.
"""

import json
import re
import threading
import urllib.request
from typing import Optional, Callable
from dataclasses import dataclass
from app.logs.logger import log_info, log_error
from app.utils.helpers import mask_ip

@dataclass
class LLMConfig:
    """Configuration for LLM connection."""
    provider: str = "ollama"          # ollama, openai, none
    base_url: str = "http://localhost:11434"  # Ollama default
    model: str = "mistral"            # model name
    api_key: str = ""                 # for remote APIs
    temperature: float = 0.3          # low = more deterministic
    max_tokens: int = 1024
    timeout: int = 30

# System prompt that teaches the LLM about DupeZ's disruption system
SYSTEM_PROMPT = """You are the DupeZ Smart Disruption Advisor. You help users configure optimal network disruption parameters for DayZ (UDP 2302, Enfusion engine, ~60 tick).

Disruption modules (processed in chain order — first consumer wins):
- godmode: Directional lag — inbound packets lagged so target freezes, outbound pass through for real-time actions. Params: godmode_lag_ms (0-5000), godmode_drop_inbound_pct (0-100), godmode_keepalive_interval_ms (0-5000, default 800 — NAT keepalive)
- disconnect: Hard kill — drops packets at configurable rate. Params: disconnect_chance (0-100%, default 100 = total blackout)
- drop: Random packet drop. Params: drop_chance (0-100%)
- bandwidth: Limit throughput. Params: bandwidth_limit (KB/s), bandwidth_queue (0-1000)
- throttle: Time-gated packet flow. Params: throttle_chance (0-100%), throttle_frame (0-1000 ms)
- lag: Buffer packets and release after delay. Params: lag_delay (0-5000 ms). When stacked with duplicate/ood, lag auto-enables passthrough mode (queues delayed copy, lets original continue to downstream modules for desync combos).
- ood: Reorder packets randomly. Params: ood_chance (0-100%)
- duplicate: Clone packets. Params: duplicate_chance (0-100%), duplicate_count (1-50). Target receives 1 original + N copies = N+1 total packets.
- corrupt: Flip random bits in payload. Params: tamper_chance (0-100%)
- rst: Inject TCP RST flags. Params: rst_chance (0-100%)

Connection types:
- hotspot (192.168.137.x): Windows ICS/mobile hotspot. Fragile — needs less aggression. God Mode most effective here (you ARE the gateway).
- lan (192.168.x.x, 10.x.x.x): Resilient — needs aggressive settings.
- wan: Natural jitter — moderate settings work.

Device types:
- console (PlayStation, Xbox, Nintendo): Limited network stack, very sensitive to out-of-order/duplicate packets. Best desync targets.
- pc: Resilient, games often have reconnect logic.
- mobile: Already struggles with packet loss.

Proven DayZ scenarios:
- Desync/Dupe: lag + duplicate + ood. Lag in passthrough mode queues delayed copies while duplicate floods real-time copies. lag_delay=1500-3000ms, duplicate_count=10-20, ood_chance=70-90. This creates the inventory desync window.
- Full disconnect: disconnect + drop + bandwidth + throttle. disconnect_chance=100, drop_chance=95, bandwidth_limit=1.
- God mode: godmode module alone. godmode_lag_ms=2000-4000 for strong freeze. Add godmode_drop_inbound_pct=10-30 for harder freeze. keepalive=800ms default for NAT safety.
- Soft lag (rubber banding): lag only, 200-600ms, direction=both. No passthrough (lag is solo).
- General FPS: lag + drop. lag_delay=500-1500ms, drop_chance=30-60%.

Direction tuning:
- "both": all traffic (default)
- "inbound": only packets TO target
- "outbound": only packets FROM target

Respond ONLY with a valid JSON object:
{
  "name": "preset name",
  "description": "what this does",
  "methods": ["list", "of", "modules"],
  "params": {"param_key": value, ...},
  "direction": "both",
  "reasoning": "brief explanation of why these settings"
}

Always include "direction": "both" in params. Be precise with numbers."""

class LLMAdvisor:
    """Natural-language disruption advisor powered by LLM.

    Usage:
        advisor = LLMAdvisor()
        if advisor.is_available():
            result = advisor.ask("desync a PS5 on my hotspot playing DayZ")
            # result = {"methods": [...], "params": {...}, ...}

        # Or async:
        advisor.ask_async("heavy lag on xbox", callback=on_result)
    """

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self._available = None  # lazy check
        self._conversation_history = []
        self._history_lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if the LLM backend is reachable."""
        if self._available is not None:
            return self._available

        if self.config.provider == "none":
            self._available = False
            return False

        try:
            url = f"{self.config.base_url}/api/tags"
            if self.config.provider == "openai":
                url = f"{self.config.base_url}/v1/models"

            req = urllib.request.Request(url, method="GET")
            if self.config.api_key:
                req.add_header("Authorization", f"Bearer {self.config.api_key}")

            resp = urllib.request.urlopen(req, timeout=5)
            self._available = resp.status == 200
            if self._available:
                log_info(f"LLMAdvisor: connected to {self.config.provider} "
                         f"at {self.config.base_url}")
            return self._available

        except Exception as e:
            log_info(f"LLMAdvisor: {self.config.provider} not available ({e})")
            self._available = False
            return False

    def ask(self, prompt: str, profile_context: dict = None) -> Optional[dict]:
        """Send a natural-language request to the LLM and parse the response.

        Args:
            prompt: User's natural language request
            profile_context: Optional NetworkProfile.to_dict() for context

        Returns:
            Parsed disruption config dict, or None on failure
        """
        if not self.is_available():
            # Fall back to keyword-based interpretation
            return self._fallback_interpret(prompt)

        try:
            # Build the messages
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

            if profile_context:
                context_msg = (
                    f"Current target profile:\n"
                    f"  IP: {mask_ip(profile_context.get('target_ip', 'unknown'))}\n"
                    f"  RTT: {profile_context.get('avg_rtt_ms', 0):.0f}ms\n"
                    f"  Jitter: {profile_context.get('jitter_ms', 0):.0f}ms\n"
                    f"  Loss: {profile_context.get('packet_loss_pct', 0):.0f}%\n"
                    f"  Connection: {profile_context.get('connection_type', 'unknown')}\n"
                    f"  Device: {profile_context.get('device_type', 'unknown')} "
                    f"({profile_context.get('device_hint', '')})\n"
                    f"  Quality: {profile_context.get('quality_score', 0):.0f}/100\n"
                )
                messages.append({"role": "system", "content": context_msg})

            # Add conversation history (last 4 exchanges)
            with self._history_lock:
                messages.extend(self._conversation_history[-8:])

            messages.append({"role": "user", "content": prompt})

            # Call the LLM
            response_text = self._call_llm(messages)
            if not response_text:
                return self._fallback_interpret(prompt)

            # Parse JSON from response
            result = self._extract_json(response_text)
            if result:
                # Store in conversation history (thread-safe for ask_async)
                with self._history_lock:
                    self._conversation_history.append(
                        {"role": "user", "content": prompt})
                    self._conversation_history.append(
                        {"role": "assistant", "content": response_text})
                    # Cap history to prevent unbounded memory growth
                    if len(self._conversation_history) > 20:
                        self._conversation_history = self._conversation_history[-16:]
                log_info(f"LLMAdvisor: parsed recommendation: {result.get('name', 'unnamed')}")
                return result

            log_error(f"LLMAdvisor: could not parse JSON from response")
            return self._fallback_interpret(prompt)

        except Exception as e:
            log_error(f"LLMAdvisor: error: {e}")
            return self._fallback_interpret(prompt)

    def ask_async(self, prompt: str, callback: Callable,
                  profile_context: dict = None):
        """Ask in background thread."""
        def _run():
            result = self.ask(prompt, profile_context)
            if callback:
                callback(result)
        t = threading.Thread(target=_run, daemon=True, name="LLMAdvisor")
        t.start()
        return t

    def get_explanation(self, config: dict) -> str:
        """Ask the LLM to explain why a configuration works."""
        if not self.is_available():
            return self._fallback_explanation(config)

        try:
            prompt = (
                f"Explain in 2-3 sentences why this disruption configuration is effective:\n"
                f"{json.dumps(config, indent=2)}"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = self._call_llm(messages)
            return response or self._fallback_explanation(config)
        except Exception as e:
            log_error(f"LLMAdvisor: explanation error: {e}")
            return self._fallback_explanation(config)

    def reset_conversation(self):
        """Clear conversation history."""
        with self._history_lock:
            self._conversation_history = []

    # LLM API calls
    def _post_json(self, url: str, payload: dict, headers: dict = None) -> Optional[dict]:
        """POST JSON to a URL and return the parsed response dict, or None."""
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     method="POST", headers=hdrs)
        try:
            resp = urllib.request.urlopen(req, timeout=self.config.timeout)
            return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log_error(f"LLMAdvisor: API call to {url} failed: {e}")
            return None

    def _call_llm(self, messages: list) -> Optional[str]:
        """Make the actual API call to the LLM."""
        if self.config.provider == "ollama":
            data = self._post_json(f"{self.config.base_url}/api/chat", {
                "model": self.config.model, "messages": messages, "stream": False,
                "options": {"temperature": self.config.temperature,
                            "num_predict": self.config.max_tokens},
            })
            return data.get("message", {}).get("content", "") if data else None

        if self.config.provider == "openai":
            hdrs = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
            data = self._post_json(f"{self.config.base_url}/v1/chat/completions", {
                "model": self.config.model, "messages": messages,
                "temperature": self.config.temperature, "max_tokens": self.config.max_tokens,
            }, hdrs)
            try:
                return data["choices"][0]["message"]["content"] if data else None
            except (KeyError, IndexError):
                return None

        return None

    # Response parsing
    # Required keys in a valid LLM disruption config
    _REQUIRED_KEYS = {"methods", "params"}
    _VALID_METHODS = frozenset({
        "lag", "drop", "throttle", "duplicate", "ood", "corrupt",
        "rst", "disconnect", "bandwidth", "godmode",
    })

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract and validate JSON object from LLM response text."""
        candidates = []

        # Try to find JSON in code blocks
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if code_match:
            try:
                candidates.append(json.loads(code_match.group(1)))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if brace_match:
            try:
                candidates.append(json.loads(brace_match.group(0)))
            except json.JSONDecodeError:
                pass

        # Try the whole thing
        try:
            candidates.append(json.loads(text))
        except json.JSONDecodeError:
            pass

        # Validate: must have "methods" (list) and "params" (dict)
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            if not self._REQUIRED_KEYS.issubset(obj):
                continue
            methods = obj.get("methods")
            if not isinstance(methods, list) or not methods:
                continue
            # Strip unknown method names
            obj["methods"] = [m for m in methods if m in self._VALID_METHODS]
            if not obj["methods"]:
                continue
            if not isinstance(obj.get("params"), dict):
                obj["params"] = {}
            # Clamp numeric params to valid ranges
            obj["params"] = self._clamp_params(obj["params"])
            return obj

        return None

    # Parameter range constraints — prevents LLM from generating out-of-bounds values
    _PARAM_RANGES = {
        "disconnect_chance": (0, 100),
        "drop_chance": (0, 100), "lag_delay": (0, 5000),
        "throttle_chance": (0, 100), "throttle_frame": (0, 1000),
        "duplicate_chance": (0, 100), "duplicate_count": (1, 50),
        "ood_chance": (0, 100), "tamper_chance": (0, 100),
        "rst_chance": (0, 100), "bandwidth_limit": (0, 100000),
        "bandwidth_queue": (0, 1000),
        "godmode_lag_ms": (0, 5000), "godmode_drop_inbound_pct": (0, 100),
        "godmode_keepalive_interval_ms": (0, 5000),
    }

    def _clamp_params(self, params: dict) -> dict:
        """Clamp numeric parameters to valid ranges."""
        for key, (lo, hi) in self._PARAM_RANGES.items():
            if key in params:
                try:
                    val = params[key]
                    if isinstance(val, (int, float)):
                        params[key] = type(val)(max(lo, min(hi, val)))
                except (TypeError, ValueError):
                    pass
        return params

    # Fallback: Keyword-based interpretation (no LLM needed)
    def _fallback_interpret(self, prompt: str) -> dict:
        """Parse natural language into disruption config using keywords.
        Works without any LLM — pure pattern matching.

        Priority order matters: stop commands first, then specific goals
        before broad ones (chaos last to avoid false positives).
        """
        prompt_lower = prompt.lower().strip()

        # --- Stop/start commands (highest priority) ---
        # These match even when combined with other words like "stop everything"
        stop_words = {"stop", "off", "disable", "halt", "cancel"}
        start_words = {"start", "on", "enable", "go", "begin", "resume"}
        first_word = prompt_lower.split()[0] if prompt_lower else ""

        if first_word in stop_words:
            return {
                "goal": "stop", "name": "Stop", "description": "Stop disruption",
                "methods": [], "params": {}, "action": "stop",
                "reasoning": "Stop command detected (keyword-parsed, no LLM)",
            }
        if first_word in start_words and len(prompt_lower.split()) <= 3:
            return {
                "goal": "start", "name": "Start", "description": "Start disruption",
                "methods": [], "params": {}, "action": "start",
                "reasoning": "Start command detected (keyword-parsed, no LLM)",
            }

        # --- Specific disruption goals (narrower matches first) ---
        if any(w in prompt_lower for w in ["god mode", "godmode", "invincib",
                                            "invisible", "freeze them", "freeze other",
                                            "keep moving", "can't see me"]):
            return self._fallback_godmode(prompt_lower)

        if any(w in prompt_lower for w in ["desync", "duplicate", "clone", "flood"]):
            return self._fallback_desync(prompt_lower)

        if any(w in prompt_lower for w in ["disconnect", "kill", "boot", "kick"]):
            return self._fallback_disconnect(prompt_lower)

        if any(w in prompt_lower for w in ["rubber", "rubberband", "teleport", "warp"]):
            return self._fallback_rubberband(prompt_lower)

        if any(w in prompt_lower for w in ["corrupt", "tamper", "glitch", "break packet"]):
            return self._fallback_corrupt(prompt_lower)

        if any(w in prompt_lower for w in ["reorder", "out of order", "shuffle"]):
            return self._fallback_ood(prompt_lower)

        if any(w in prompt_lower for w in ["lag", "delay", "slow"]):
            return self._fallback_lag(prompt_lower)

        if any(w in prompt_lower for w in ["throttle", "bandwidth", "cap", "limit"]):
            return self._fallback_throttle(prompt_lower)

        # Chaos — broad match, must come last. "everything" only matches chaos
        # when NOT preceded by stop/cancel words (handled above).
        if any(w in prompt_lower for w in ["chaos", "everything", "destroy", "nuke"]):
            return self._fallback_chaos(prompt_lower)

        return self._fallback_disconnect(prompt_lower)

    def _detect_intensity(self, prompt: str) -> float:
        """Detect intensity from keywords."""
        if any(w in prompt for w in ["max", "full", "hard", "heavy", "brutal",
                                      "destroy", "nuke", "100"]):
            return 1.0
        elif any(w in prompt for w in ["light", "soft", "gentle", "mild", "low"]):
            return 0.4
        elif any(w in prompt for w in ["medium", "moderate", "normal"]):
            return 0.6
        return 0.8  # default

    def _make_fallback(self, goal: str, methods: list, params: dict,
                       intensity: float, description: str = "") -> dict:
        """Build a standard fallback config dict."""
        params["direction"] = "both"
        return {
            "goal": goal,
            "name": f"AI {goal.title()}",
            "description": description or f"Keyword-parsed {goal} configuration",
            "methods": methods,
            "params": params,
            "reasoning": f"{goal.title()} config at {intensity:.0%} intensity (keyword-parsed, no LLM)",
        }

    def _fallback_disconnect(self, prompt: str) -> dict:
        i = self._detect_intensity(prompt)
        return self._make_fallback("disconnect",
            ["disconnect", "drop", "lag", "bandwidth", "throttle"], {
                "disconnect_chance": 100,  # 100% = true hard disconnect
                "drop_chance": int(70 + 29 * i), "lag_delay": int(800 + 1700 * i),
                "bandwidth_limit": 1, "bandwidth_queue": 0,
                "throttle_chance": int(70 + 30 * i),
                "throttle_frame": int(200 + 400 * i), "throttle_drop": True,
            }, i)

    def _fallback_lag(self, prompt: str) -> dict:
        i = self._detect_intensity(prompt)
        return self._make_fallback("lag", ["lag", "drop"], {
            "lag_delay": int(300 + 2000 * i), "drop_chance": int(20 + 50 * i),
        }, i)

    def _fallback_desync(self, prompt: str) -> dict:
        i = self._detect_intensity(prompt)
        # DayZ-specific tuning: higher duplicate count for inventory exploits
        is_dayz = any(w in prompt for w in ["dayz", "day z", "chernarus", "livonia", "dupe"])
        dup_count = int(10 + 15 * i) if is_dayz else int(5 + 15 * i)
        lag_ms = int(500 + 1500 * i) if is_dayz else int(300 + 900 * i)
        return self._make_fallback("desync", ["lag", "duplicate", "ood"], {
            "lag_delay": lag_ms, "duplicate_chance": int(60 + 35 * i),
            "duplicate_count": dup_count, "ood_chance": int(50 + 40 * i),
        }, i)

    def _fallback_throttle(self, prompt: str) -> dict:
        i = self._detect_intensity(prompt)
        return self._make_fallback("throttle", ["bandwidth", "throttle"], {
            "bandwidth_limit": max(1, int(50 * (1 - i))), "bandwidth_queue": 0,
            "throttle_chance": int(50 + 50 * i),
            "throttle_frame": int(100 + 500 * i), "throttle_drop": True,
        }, i)

    def _fallback_godmode(self, prompt: str) -> dict:
        """God Mode: inbound-only lag so others freeze while you keep moving."""
        i = self._detect_intensity(prompt)
        lag_ms = int(1500 + 2500 * i)
        drop_pct = int(20 + 30 * (i - 0.8) / 0.2) if i >= 0.8 else 0
        on_hotspot = any(w in prompt for w in ["hotspot", "ics", "mobile", "tether", "137"])
        if on_hotspot:
            lag_ms = int(lag_ms * 0.8)
        # NAT keepalive: reduce at high intensity, disable at max
        keepalive_ms = 0 if i >= 0.95 else int(800 - 400 * i)
        result = self._make_fallback("godmode", ["godmode"], {
            "godmode_lag_ms": lag_ms, "godmode_drop_inbound_pct": drop_pct,
            "godmode_keepalive_interval_ms": keepalive_ms,
        }, i, "Directional lag — inbound packets delayed so others freeze")
        result["reasoning"] = (
            f"God Mode at {i:.0%} intensity: {lag_ms}ms inbound lag"
            f"{f', {drop_pct}% inbound drop' if drop_pct else ''}"
            f", NAT keepalive={keepalive_ms}ms"
            f"{' (hotspot-tuned)' if on_hotspot else ''}"
            " (keyword-parsed, no LLM)")
        return result

    def _fallback_rubberband(self, prompt: str) -> dict:
        """Soft lag — rubber-banding / teleport effect without hard disconnect."""
        i = self._detect_intensity(prompt)
        return self._make_fallback("rubberband", ["lag"], {
            "lag_delay": int(200 + 500 * i),
        }, i, "Soft lag — causes rubber-banding and teleport artifacts")

    def _fallback_corrupt(self, prompt: str) -> dict:
        """Corrupt packet payloads — causes glitches and protocol errors."""
        i = self._detect_intensity(prompt)
        return self._make_fallback("corrupt", ["corrupt", "lag"], {
            "tamper_chance": int(40 + 55 * i),
            "lag_delay": int(100 + 300 * i),
        }, i, "Payload corruption — flips random bits causing glitches")

    def _fallback_ood(self, prompt: str) -> dict:
        """Out-of-order packets — causes desync by reordering packet delivery."""
        i = self._detect_intensity(prompt)
        return self._make_fallback("reorder", ["ood", "lag"], {
            "ood_chance": int(50 + 45 * i),
            "lag_delay": int(100 + 400 * i),
        }, i, "Packet reordering — disrupts sequence-sensitive protocols")

    def _fallback_chaos(self, prompt: str) -> dict:
        return self._make_fallback("chaos",
            ["disconnect", "drop", "lag", "duplicate", "corrupt", "rst", "ood", "bandwidth", "throttle"], {
                "drop_chance": 95, "lag_delay": 2000,
                "duplicate_chance": 85, "duplicate_count": 15,
                "tamper_chance": 70, "rst_chance": 90, "ood_chance": 85,
                "bandwidth_limit": 1, "bandwidth_queue": 0,
                "throttle_chance": 100, "throttle_frame": 600, "throttle_drop": True,
            }, 1.0, "Maximum disruption — all modules")

    # Method → explanation template (param_key or None for static text)
    _EXPLAIN_MAP = [
        ("disconnect", "disconnect drops 99% of packets", None),
        ("drop", "drop removes {v}% of remaining packets", "drop_chance"),
        ("lag", "lag adds {v}ms delay", "lag_delay"),
        ("duplicate", "duplicate floods with packet copies causing desync", None),
        ("bandwidth", "bandwidth caps throughput to {v} KB/s", "bandwidth_limit"),
    ]

    def _fallback_explanation(self, config: dict) -> str:
        """Generate explanation without LLM."""
        methods = config.get("methods", [])
        params = config.get("params", {})
        parts = []
        for method, tpl, param_key in self._EXPLAIN_MAP:
            if method in methods:
                parts.append(tpl.format(v=params.get(param_key, '?')) if param_key else tpl)
        if "godmode" in methods:
            lag = params.get('godmode_lag_ms', '?')
            drop = params.get('godmode_drop_inbound_pct', 0)
            keepalive = params.get('godmode_keepalive_interval_ms', 800)
            parts.append(f"god mode lags inbound {lag}ms while passing outbound instantly"
                        f"{f', dropping {drop}% inbound' if drop else ''}"
                        f"{f', NAT keepalive every {keepalive}ms' if keepalive else ''}")
        return "This configuration " + ", ".join(parts) + "." if parts else "Custom disruption configuration."

