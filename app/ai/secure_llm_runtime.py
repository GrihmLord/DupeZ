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
* two-slot provider concurrency with validated offline overload fallback;
* offline rule-based fallback through the existing advisor implementation.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

from app.ai.llm_advisor import LLMAdvisor, LLMConfig
from app.ai.ollama_transport import validate_ollama_base_url
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
LLM_SECRET_NAME = "llm_api_key"  # pragma: allowlist secret
_VALID_PROVIDERS = frozenset({"ollama", "openai", "none"})
_MAX_PROVIDER_REQUESTS = 2


@dataclass
class _RequestSnapshot:
    generation: int
    cancel_event: threading.Event
    config: SecureLLMConfig
    history: list
    available: Optional[bool]
    api_key: Optional[str] = field(default=None, repr=False)


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


def _validated_base_url(provider: str, value: str) -> str:
    provider = provider.strip().lower()
    if provider == "none":
        return ""
    supplied = str(value or "")
    if not supplied.strip():
        supplied = (
            "http://localhost:11434"
            if provider == "ollama"
            else "https://api.openai.com"
        )
    if provider == "ollama":
        return validate_ollama_base_url(supplied)

    text = supplied.strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("provider URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("provider URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("provider URL must not contain query or fragment data")
    if parsed.scheme != "https":
        raise ValueError("remote provider URLs must use HTTPS")
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
        # Ownership checks and shared state writes must use the same lock.
        self._history_lock = self._request_lock
        self._request_local = threading.local()
        self._request_generation = 0
        self._cancel_event = threading.Event()
        self._provider_slots = threading.BoundedSemaphore(
            _MAX_PROVIDER_REQUESTS
        )

    @classmethod
    def from_settings(cls) -> "ConfiguredLLMAdvisor":
        return cls(SecureLLMConfig.from_settings())

    def reconfigure(self, config: SecureLLMConfig, *, persist: bool = True) -> None:
        with self._request_lock:
            self.cancel_pending()
            self.config = config
            self._available = None
            super().reset_conversation()
        if persist:
            config.save_public_settings()

    def _snapshot_request(self) -> _RequestSnapshot:
        with self._request_lock:
            return _RequestSnapshot(
                self._request_generation,
                self._cancel_event,
                copy(self.config),
                [dict(message) for message in self._conversation_history[-8:]],
                self._available,
            )

    @contextmanager
    def _request_scope(self, snapshot: Optional[_RequestSnapshot] = None):
        current = getattr(self._request_local, "snapshot", None)
        if current is not None:
            yield current
            return
        self._request_local.snapshot = snapshot or self._snapshot_request()
        try:
            yield self._request_local.snapshot
        finally:
            self._request_local.snapshot.api_key = None
            del self._request_local.snapshot

    def _request_config(self) -> SecureLLMConfig:
        snapshot = getattr(self._request_local, "snapshot", None)
        return snapshot.config if snapshot is not None else self.config

    def _request_api_key(self) -> str:
        snapshot = getattr(self._request_local, "snapshot", None)
        if snapshot is None:
            return super()._request_api_key()
        if snapshot.config.provider != "openai":
            return ""
        if snapshot.api_key is None:
            # Freeze credentials at first use for the entire request, including
            # its availability probe. Never pair a later vault rotation with
            # the original provider URL. Vault I/O must stay outside the lock.
            if not self._owns_request(snapshot.generation, snapshot.cancel_event):
                return ""
            secret = snapshot.config.get_api_key()
            with self._request_lock:
                snapshot.api_key = (
                    secret
                    if self._owns_request(snapshot.generation, snapshot.cancel_event)
                    else ""
                )
        return snapshot.api_key

    def _cached_availability(self) -> Optional[bool]:
        snapshot = getattr(self._request_local, "snapshot", None)
        if snapshot is not None:
            return snapshot.available
        with self._request_lock:
            return self._available

    def _store_availability(self, available: Optional[bool]) -> None:
        snapshot = getattr(self._request_local, "snapshot", None)
        with self._request_lock:
            if snapshot is not None:
                snapshot.available = available
                if not self._owns_request(
                    snapshot.generation, snapshot.cancel_event
                ):
                    return
            self._available = available

    def _request_history(self) -> list:
        snapshot = getattr(self._request_local, "snapshot", None)
        return snapshot.history if snapshot is not None else super()._request_history()

    def _remember_exchange(self, prompt: str, response_text: str) -> None:
        snapshot = getattr(self._request_local, "snapshot", None)
        with self._request_lock:
            if snapshot is not None and not self._owns_request(
                snapshot.generation, snapshot.cancel_event
            ):
                return
            super()._remember_exchange(prompt, response_text)

    def is_available(self) -> bool:
        with self._request_scope():
            return super().is_available()

    def ask(self, prompt: str, profile_context: dict = None) -> Optional[dict]:
        with self._request_scope():
            return super().ask(prompt, profile_context)

    def get_explanation(self, config: dict) -> str:
        with self._request_scope():
            return super().get_explanation(config)

    def reset_conversation(self) -> None:
        with self._request_lock:
            self.cancel_pending()
            super().reset_conversation()

    def refresh_availability(self) -> bool:
        with self._request_scope():
            if not self._provider_slots.acquire(blocking=False):
                # A busy provider is not evidence that its cached state changed.
                log_info("Smart Ops provider capacity reached; check deferred")
                return False
            try:
                self._store_availability(None)
                return bool(self.is_available())
            finally:
                self._provider_slots.release()

    def refresh_availability_async(
        self,
        callback: Optional[Callable[[bool], None]] = None,
    ) -> threading.Thread:
        with self._request_lock:
            generation, cancel_event = self._begin_request()
            snapshot = self._snapshot_request()

        def _run() -> None:
            with self._request_scope(snapshot):
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
        with self._request_lock:
            generation, cancel_event = self._begin_request()
            snapshot = self._snapshot_request()

        def _run() -> None:
            with self._request_scope(snapshot):
                if not self._provider_slots.acquire(blocking=False):
                    log_info(
                        "Smart Ops provider capacity reached; using validated "
                        "offline recommendation"
                    )
                    result = self._fallback_interpret(prompt)
                else:
                    try:
                        result = self.ask(prompt, profile_context)
                    finally:
                        self._provider_slots.release()
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
