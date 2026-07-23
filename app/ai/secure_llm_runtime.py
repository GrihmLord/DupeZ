# app/ai/secure_llm_runtime.py — hardened Smart Ops provider runtime
"""Secure configuration and request ownership for the legacy LLM advisor.

The original ``LLMConfig`` accidentally imported ``_LLM_SECRET_NAME`` from
``app.core.secrets_manager`` even though the constant is local to the advisor
module. That import always fails, causing encrypted retrieval to fall back to
the deprecated plaintext field. This wrapper fixes the boundary without
rewriting the mature parser/fallback engine.

It also adds:

* persisted non-secret provider/model/base-URL settings;
* encrypted API-key store, retrieve, rotate, and delete operations;
* provider URL validation;
* explicit availability refresh after configuration changes;
* generation-owned async callbacks so stale requests cannot update the UI;
* cooperative cancellation of callbacks while preserving bounded HTTP timeouts;
* offline rule-based fallback through the existing advisor implementation.
"""

from __future__ import annotations

import ipaddress
import threading
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from app.ai.llm_advisor import LLMAdvisor, LLMConfig
from app.core.data_persistence import settings_manager
from app.core.secrets_manager import get_secrets_manager
from app.logs.logger import log_error, log_info

__all__ = [
    "LLM_SETTINGS_KEY",
    "LLM_SECRET_NAME",
    "SecureLLMConfig",
    "ConfiguredLLMAdvisor",
]

LLM_SETTINGS_KEY = "llm_advisor"
LLM_SECRET_NAME = "llm_api_key"
_VALID_PROVIDERS = frozenset({"ollama", "openai", "none"})
_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(
    value: object,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _is_loopback_host(hostname: str) -> bool:
    lowered = (hostname or "").strip().lower()
    if lowered in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _validated_base_url(provider: str, value: str) -> str:
    provider = provider.strip().lower()
    if provider == "none":
        return ""
    text = str(value or "").strip().rstrip("/")
    if not text:
        text = (
            "http://localhost:11434"
            if provider == "ollama"
            else "https://api.openai.com"
        )
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("provider URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("provider URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("provider URL must not contain query or fragment data")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ValueError(
            "unencrypted provider URLs are allowed only for loopback services"
        )
    return text


@dataclass
class SecureLLMConfig(LLMConfig):
    """LLMConfig with correct encrypted secret handling and validation."""

    def __post_init__(self) -> None:
        provider = str(self.provider or "ollama").strip().lower()
        self.provider = provider if provider in _VALID_PROVIDERS else "none"
        self.base_url = _validated_base_url(self.provider, self.base_url)
        self.model = str(self.model or "mistral").strip()[:128] or "mistral"
        self.temperature = _bounded_float(
            self.temperature,
            default=0.3,
            minimum=0.0,
            maximum=2.0,
        )
        self.max_tokens = _bounded_int(
            self.max_tokens,
            default=1024,
            minimum=64,
            maximum=8192,
        )
        self.timeout = _bounded_int(
            self.timeout,
            default=30,
            minimum=5,
            maximum=120,
        )
        plaintext = str(self.api_key or "")
        self.api_key = ""
        if plaintext and not self.store_api_key(plaintext):
            log_error("Smart Ops API key migration failed; plaintext was discarded")

    def get_api_key(self) -> str:
        """Retrieve the API key only from the encrypted secrets manager."""

        try:
            return get_secrets_manager().retrieve(LLM_SECRET_NAME) or ""
        except Exception as exc:
            log_error(f"Smart Ops API key retrieval failed: {exc}")
            return ""

    def store_api_key(self, value: str) -> bool:
        """Encrypt and store a replacement API key."""

        secret = str(value or "").strip()
        if not secret:
            return False
        try:
            stored = bool(get_secrets_manager().store(LLM_SECRET_NAME, secret))
            if stored:
                log_info("Smart Ops API key stored in encrypted secrets manager")
            return stored
        except Exception as exc:
            log_error(f"Smart Ops API key storage failed: {exc}")
            return False

    def delete_api_key(self) -> bool:
        try:
            return bool(get_secrets_manager().delete(LLM_SECRET_NAME))
        except Exception as exc:
            log_error(f"Smart Ops API key deletion failed: {exc}")
            return False

    def public_settings(self) -> dict:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

    def save_public_settings(self) -> None:
        settings_manager.update_setting(LLM_SETTINGS_KEY, self.public_settings())

    @classmethod
    def from_settings(cls) -> "SecureLLMConfig":
        raw = settings_manager.get_setting(LLM_SETTINGS_KEY, {})
        data = raw if isinstance(raw, dict) else {}
        return cls(
            provider=data.get("provider", "ollama"),
            base_url=data.get("base_url", "http://localhost:11434"),
            model=data.get("model", "mistral"),
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 1024),
            timeout=data.get("timeout", 30),
        )


class ConfiguredLLMAdvisor(LLMAdvisor):
    """LLMAdvisor with provider refresh and stale-callback rejection."""

    def __init__(self, config: Optional[SecureLLMConfig] = None) -> None:
        super().__init__(config or SecureLLMConfig.from_settings())
        self._request_lock = threading.RLock()
        self._request_generation = 0
        self._cancel_event = threading.Event()

    @classmethod
    def from_settings(cls) -> "ConfiguredLLMAdvisor":
        return cls(SecureLLMConfig.from_settings())

    def reconfigure(self, config: SecureLLMConfig, *, persist: bool = True) -> None:
        self.cancel_pending()
        self.config = config
        self._available = None
        self.reset_conversation()
        if persist:
            config.save_public_settings()

    def refresh_availability(self) -> bool:
        self._available = None
        return bool(self.is_available())

    def refresh_availability_async(
        self,
        callback: Optional[Callable[[bool], None]] = None,
    ) -> threading.Thread:
        generation, cancel_event = self._begin_request()

        def _run() -> None:
            available = self.refresh_availability()
            if self._owns_request(generation, cancel_event) and callback:
                callback(available)

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name="SmartOpsProviderCheck",
        )
        thread.start()
        return thread

    def ask_async(
        self,
        prompt: str,
        callback: Callable,
        profile_context: dict = None,
    ) -> threading.Thread:
        generation, cancel_event = self._begin_request()

        def _run() -> None:
            result = self.ask(prompt, profile_context)
            if self._owns_request(generation, cancel_event) and callback:
                callback(result)

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name="SmartOpsAdvisor",
        )
        thread.start()
        return thread

    def cancel_pending(self) -> None:
        with self._request_lock:
            self._request_generation += 1
            self._cancel_event.set()
            self._cancel_event = threading.Event()

    def _begin_request(self) -> tuple[int, threading.Event]:
        with self._request_lock:
            self._request_generation += 1
            self._cancel_event.set()
            self._cancel_event = threading.Event()
            return self._request_generation, self._cancel_event

    def _owns_request(
        self,
        generation: int,
        cancel_event: threading.Event,
    ) -> bool:
        with self._request_lock:
            return (
                generation == self._request_generation
                and cancel_event is self._cancel_event
                and not cancel_event.is_set()
            )
