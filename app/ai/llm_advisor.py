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
import os
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from app.logs.logger import log_info, log_error


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
SYSTEM_PROMPT = """You are the DupeZ Smart Disruption Advisor. You help users configure optimal network disruption parameters.

You have access to these disruption modules:
- lag: Add delay to packets. Params: lag_delay (0-5000 ms)
- drop: Randomly drop packets. Params: drop_chance (0-100%)
- throttle: Throttle packet flow. Params: throttle_chance (0-100%), throttle_frame (0-1000 ms)
- duplicate: Clone packets. Params: duplicate_chance (0-100%), duplicate_count (1-50)
- ood: Reorder packets randomly. Params: ood_chance (0-100%)
- corrupt: Flip random bits in payload. Params: tamper_chance (0-100%)
- rst: Inject TCP RST flags to kill connections. Params: rst_chance (0-100%)
- disconnect: Drop 99% of packets (hard kill)
- bandwidth: Limit throughput. Params: bandwidth_limit (KB/s), bandwidth_queue (0-1000)

Connection types and their characteristics:
- hotspot (192.168.137.x): Windows ICS/mobile hotspot. Already fragile, needs less aggression.
- lan (192.168.x.x, 10.x.x.x): Local network. Resilient, needs aggressive settings.
- wan: Internet. Has natural jitter, moderate settings work.

Device types:
- console (PlayStation, Xbox, Nintendo): Limited network stack, sensitive to out-of-order/duplicate packets
- pc: Resilient, games often have reconnect logic
- mobile: Already struggles with packet loss

Common gaming scenarios:
- DayZ: UDP-heavy, very sensitive to desync. Best approach: lag + duplicate + ood
- General FPS: Lag + drop is usually sufficient
- Full disconnect: disconnect + drop + bandwidth cap + throttle

When the user describes what they want, respond ONLY with a valid JSON object:
{
  "name": "preset name",
  "description": "what this does",
  "methods": ["list", "of", "modules"],
  "params": {"param_key": value, ...},
  "direction": "both",
  "reasoning": "brief explanation of why these settings"
}

Always include "direction": "both" in params. Be precise with numbers. Tune aggressiveness based on what the user describes."""


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

    def is_available(self) -> bool:
        """Check if the LLM backend is reachable."""
        if self._available is not None:
            return self._available

        if self.config.provider == "none":
            self._available = False
            return False

        try:
            import urllib.request
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

            # Add profile context if available
            if profile_context:
                context_msg = (
                    f"Current target profile:\n"
                    f"  IP: {profile_context.get('target_ip', 'unknown')}\n"
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
            messages.extend(self._conversation_history[-8:])

            # Add user prompt
            messages.append({"role": "user", "content": prompt})

            # Call the LLM
            response_text = self._call_llm(messages)
            if not response_text:
                return self._fallback_interpret(prompt)

            # Parse JSON from response
            result = self._extract_json(response_text)
            if result:
                # Store in conversation history
                self._conversation_history.append(
                    {"role": "user", "content": prompt})
                self._conversation_history.append(
                    {"role": "assistant", "content": response_text})
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

    def reset_conversation(self):
        """Clear conversation history."""
        self._conversation_history = []

    # ------------------------------------------------------------------
    # LLM API calls
    # ------------------------------------------------------------------
    def _call_llm(self, messages: list) -> Optional[str]:
        """Make the actual API call to the LLM."""
        import urllib.request

        if self.config.provider == "ollama":
            return self._call_ollama(messages)
        elif self.config.provider == "openai":
            return self._call_openai_compat(messages)
        return None

    def _call_ollama(self, messages: list) -> Optional[str]:
        """Call Ollama's /api/chat endpoint."""
        import urllib.request

        url = f"{self.config.base_url}/api/chat"
        payload = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            resp = urllib.request.urlopen(req, timeout=self.config.timeout)
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")
        except Exception as e:
            log_error(f"LLMAdvisor: Ollama call failed: {e}")
            return None

    def _call_openai_compat(self, messages: list) -> Optional[str]:
        """Call any OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.request

        url = f"{self.config.base_url}/v1/chat/completions"
        payload = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        req = urllib.request.Request(url, data=payload, method="POST",
                                     headers=headers)

        try:
            resp = urllib.request.urlopen(req, timeout=self.config.timeout)
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log_error(f"LLMAdvisor: OpenAI-compat call failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON object from LLM response text."""
        import re

        # Try to find JSON in code blocks
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if code_match:
            try:
                return json.loads(code_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try the whole thing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Fallback: Keyword-based interpretation (no LLM needed)
    # ------------------------------------------------------------------
    def _fallback_interpret(self, prompt: str) -> dict:
        """Parse natural language into disruption config using keywords.
        Works without any LLM — pure pattern matching."""
        prompt_lower = prompt.lower()

        # Detect goal
        if any(w in prompt_lower for w in ["desync", "duplicate", "clone", "flood"]):
            return self._fallback_desync(prompt_lower)
        elif any(w in prompt_lower for w in ["disconnect", "kill", "boot", "kick"]):
            return self._fallback_disconnect(prompt_lower)
        elif any(w in prompt_lower for w in ["lag", "delay", "slow"]):
            return self._fallback_lag(prompt_lower)
        elif any(w in prompt_lower for w in ["throttle", "bandwidth", "cap", "limit"]):
            return self._fallback_throttle(prompt_lower)
        elif any(w in prompt_lower for w in ["chaos", "everything", "destroy", "nuke"]):
            return self._fallback_chaos(prompt_lower)
        else:
            # Default to disconnect
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

    def _fallback_disconnect(self, prompt: str) -> dict:
        intensity = self._detect_intensity(prompt)
        return {
            "goal": "disconnect",
            "name": "AI Disconnect",
            "description": "Keyword-parsed disconnect configuration",
            "methods": ["disconnect", "drop", "lag", "bandwidth", "throttle"],
            "params": {
                "drop_chance": int(70 + 29 * intensity),
                "lag_delay": int(800 + 1700 * intensity),
                "bandwidth_limit": 1,
                "bandwidth_queue": 0,
                "throttle_chance": int(70 + 30 * intensity),
                "throttle_frame": int(200 + 400 * intensity),
                "throttle_drop": True,
                "direction": "both",
            },
            "reasoning": f"Disconnect config at {intensity:.0%} intensity (keyword-parsed, no LLM)",
        }

    def _fallback_lag(self, prompt: str) -> dict:
        intensity = self._detect_intensity(prompt)
        return {
            "goal": "lag",
            "name": "AI Lag",
            "description": "Keyword-parsed lag configuration",
            "methods": ["lag", "drop"],
            "params": {
                "lag_delay": int(300 + 2000 * intensity),
                "drop_chance": int(20 + 50 * intensity),
                "direction": "both",
            },
            "reasoning": f"Lag config at {intensity:.0%} intensity (keyword-parsed, no LLM)",
        }

    def _fallback_desync(self, prompt: str) -> dict:
        intensity = self._detect_intensity(prompt)
        return {
            "goal": "desync",
            "name": "AI Desync",
            "description": "Keyword-parsed desync configuration",
            "methods": ["lag", "duplicate", "ood"],
            "params": {
                "lag_delay": int(300 + 900 * intensity),
                "duplicate_chance": int(60 + 35 * intensity),
                "duplicate_count": int(5 + 15 * intensity),
                "ood_chance": int(50 + 40 * intensity),
                "direction": "both",
            },
            "reasoning": f"Desync config at {intensity:.0%} intensity (keyword-parsed, no LLM)",
        }

    def _fallback_throttle(self, prompt: str) -> dict:
        intensity = self._detect_intensity(prompt)
        return {
            "goal": "throttle",
            "name": "AI Throttle",
            "description": "Keyword-parsed throttle configuration",
            "methods": ["bandwidth", "throttle"],
            "params": {
                "bandwidth_limit": max(1, int(50 * (1 - intensity))),
                "bandwidth_queue": 0,
                "throttle_chance": int(50 + 50 * intensity),
                "throttle_frame": int(100 + 500 * intensity),
                "throttle_drop": True,
                "direction": "both",
            },
            "reasoning": f"Throttle config at {intensity:.0%} intensity (keyword-parsed, no LLM)",
        }

    def _fallback_chaos(self, prompt: str) -> dict:
        return {
            "goal": "chaos",
            "name": "AI Chaos",
            "description": "Maximum disruption — all modules",
            "methods": ["disconnect", "drop", "lag", "duplicate",
                        "corrupt", "rst", "ood", "bandwidth", "throttle"],
            "params": {
                "drop_chance": 95, "lag_delay": 2000,
                "duplicate_chance": 85, "duplicate_count": 15,
                "tamper_chance": 70, "rst_chance": 90, "ood_chance": 85,
                "bandwidth_limit": 1, "bandwidth_queue": 0,
                "throttle_chance": 100, "throttle_frame": 600,
                "throttle_drop": True, "direction": "both",
            },
            "reasoning": "Full chaos — every module at maximum (keyword-parsed, no LLM)",
        }

    def _fallback_explanation(self, config: dict) -> str:
        """Generate explanation without LLM."""
        methods = config.get("methods", [])
        parts = []
        if "disconnect" in methods:
            parts.append("disconnect drops 99% of packets")
        if "drop" in methods:
            parts.append(f"drop removes {config.get('params', {}).get('drop_chance', '?')}% of remaining packets")
        if "lag" in methods:
            parts.append(f"lag adds {config.get('params', {}).get('lag_delay', '?')}ms delay")
        if "duplicate" in methods:
            parts.append("duplicate floods with packet copies causing desync")
        if "bandwidth" in methods:
            parts.append(f"bandwidth caps throughput to {config.get('params', {}).get('bandwidth_limit', '?')} KB/s")
        return "This configuration " + ", ".join(parts) + "." if parts else "Custom disruption configuration."
