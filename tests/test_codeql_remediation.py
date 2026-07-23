from __future__ import annotations

import base64
import json
import logging

from app.core.secrets_manager import SecretsManager, get_scrubber
from app.gui.dayz_map_gui_new import _is_izurvive_host
from app.logs.logger import DupeZLogger


def test_izurvive_host_check_is_label_bound() -> None:
    assert _is_izurvive_host("izurvive.com")
    assert _is_izurvive_host("tiles.izurvive.com")
    assert _is_izurvive_host("TILES.IZURVIVE.COM.")
    assert not _is_izurvive_host("evilizurvive.com")
    assert not _is_izurvive_host("izurvive.com.attacker.invalid")
    assert not _is_izurvive_host("")


def test_secret_record_uses_authenticated_ciphertext_only(tmp_path) -> None:
    canary = "redaction-canary-value"
    manager = SecretsManager(str(tmp_path))

    assert manager.store("provider", canary, ttl_seconds=0)

    store_text = manager._secrets_path.read_text(encoding="utf-8")
    stored = json.loads(store_text)["provider"]
    assert canary not in store_text
    assert "integrity" not in stored
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
