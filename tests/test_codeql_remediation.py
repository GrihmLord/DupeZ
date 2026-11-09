from __future__ import annotations

import base64
import json
import logging

import pytest

from app.core import secrets_manager as secrets_manager_module
from app.core.secrets_manager import SecretsManager, get_scrubber
from app.gui.map_host.request_policy import is_izurvive_host
from app.logs.logger import DupeZLogger


def test_izurvive_host_check_is_label_bound() -> None:
    assert is_izurvive_host("izurvive.com")
    assert is_izurvive_host("tiles.izurvive.com")
    assert is_izurvive_host("TILES.IZURVIVE.COM.")
    assert not is_izurvive_host("evilizurvive.com")
    assert not is_izurvive_host("izurvive.com.attacker.invalid")
    assert not is_izurvive_host("")


@pytest.fixture
def _isolated_secrets_master(monkeypatch) -> bytes:
    master = bytes(range(32))
    monkeypatch.setattr(
        secrets_manager_module,
        "get_or_create_secret",
        lambda *_args, **_kwargs: master,
    )
    return master


def test_secret_record_uses_authenticated_ciphertext_only(
    tmp_path, _isolated_secrets_master
) -> None:
    canary = "redaction-canary-value"
    manager = SecretsManager(str(tmp_path))

    assert manager.store("provider", canary, ttl_seconds=0)

    store_text = manager._secrets_path.read_text(encoding="utf-8")
    stored = json.loads(store_text)["provider"]
    assert canary not in store_text
    assert "integrity" not in stored
    assert stored["key_source"] == "secret-store-v1"
    assert manager.retrieve("provider") == canary

    tag = bytearray(base64.b64decode(stored["tag"]))
    tag[0] ^= 0x01
    stored["tag"] = base64.b64encode(tag).decode("ascii")
    manager._secrets_path.write_text(
        json.dumps({"provider": stored}),
        encoding="utf-8",
    )
    reloaded = SecretsManager(str(tmp_path))
    assert reloaded.retrieve("provider") is None


def test_secret_store_write_failure_rolls_back_memory(
    tmp_path, monkeypatch, _isolated_secrets_master
) -> None:
    manager = SecretsManager(str(tmp_path))

    def fail_replace(*_args, **_kwargs):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(secrets_manager_module.os, "replace", fail_replace)

    assert manager.store("provider", "must-not-survive", ttl_seconds=0) is False
    assert manager.has_secret("provider") is False
    assert not manager._secrets_path.exists()


def test_logger_scrubs_exception_and_context_before_output(tmp_path) -> None:
    canary = "log-redaction-canary"
    get_scrubber().register(canary)
    wrapped = DupeZLogger("DupeZ.CodeQLRegression", str(tmp_path))

    try:
        wrapped.info("provider request", value=canary)
        try:
            raise RuntimeError(f"request failed with {canary}")
        except RuntimeError as exc:
            wrapped.error("provider failure", exception=exc)

        for handler in wrapped.logger.handlers:
            handler.flush()

        rendered = "\n".join(
            path.read_text(encoding="utf-8")
            for path in tmp_path.glob("*.log")
        )
        assert canary not in rendered
        assert "[REDACTED]" in rendered
        assert "RuntimeError" in rendered
    finally:
        get_scrubber().unregister(canary)
        for handler in list(wrapped.logger.handlers):
            handler.close()
            wrapped.logger.removeHandler(handler)
        logging.Logger.manager.loggerDict.pop(wrapped.logger.name, None)


def test_audit_key_fallback_does_not_log_exception_payload(
    monkeypatch, tmp_path
) -> None:
    from app.core import secret_store
    from app.logs import audit as audit_module

    canary = r"C:\Users\SensitiveUser\AppData\Local\DupeZ\secrets"
    messages: list[str] = []

    def fail_to_load_key(*_args, **_kwargs):
        raise PermissionError(canary)

    monkeypatch.setattr(secret_store, "get_or_create_secret", fail_to_load_key)
    monkeypatch.setattr(audit_module, "log_error", messages.append)

    logger = audit_module.AuditLogger(audit_dir=str(tmp_path))
    rendered = "\n".join(messages)

    assert logger.degraded is True
    assert canary not in rendered
    assert "PermissionError" in rendered
