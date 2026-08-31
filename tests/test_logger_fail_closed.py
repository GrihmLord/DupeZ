from __future__ import annotations

import builtins
import logging
import sys
from typing import Any

import pytest

from app.logs.logger import _ScrubbingFormatter, _scrub_log_message


def _block_app_imports(
    monkeypatch: pytest.MonkeyPatch,
    *blocked_names: str,
) -> None:
    real_import = builtins.__import__
    blocked = set(blocked_names)

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in blocked:
            raise ImportError(f"simulated circular import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_scrubber_discards_record_when_secret_registry_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "unstructured-registered-secret-canary"
    _block_app_imports(monkeypatch, "app.core.secrets_manager")

    scrubbed = _scrub_log_message(
        f"operation failed with {canary} at 192.168.10.42"
    )

    assert scrubbed == "[REDACTED: secret scrubber unavailable]"
    assert canary not in scrubbed
    assert "192.168.10.42" not in scrubbed


def test_dependency_free_floor_scrubs_when_helper_import_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_app_imports(monkeypatch, "app.utils.helpers")
    message = (
        "payload={'api_key': 'credential-canary'} "  # pragma: allowlist secret
        "endpoint=https://user:pass@example.test/private?token=query-canary "  # pragma: allowlist secret
        r"path=C:\Users\SensitiveUser\AppData\Local\DupeZ\secrets.json "
        "peer=192.168.10.42 mac=AA-BB-CC-DD-EE-FF"
    )

    scrubbed = _scrub_log_message(message)

    for private_value in (
        "credential-canary",
        "user:pass",
        "/private",
        "query-canary",
        "SensitiveUser",
        "192.168.10.42",
        "AA-BB-CC-DD-EE-FF",
    ):
        assert private_value not in scrubbed
    assert "https://example.test/[REDACTED]" in scrubbed
    assert "192.168.10.x" in scrubbed
    assert "aa-bb-cc-**-**-**" in scrubbed


def test_formatter_scrubs_cached_traceback_and_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_app_imports(monkeypatch, "app.utils.helpers")
    token = "".join(("sk", "-", "0123456789abcdefghijklmnop"))  # pragma: allowlist secret
    url = "https://user:pass@example.test/private?token=query-canary"  # pragma: allowlist secret
    path = r"C:\Users\SensitiveUser\Private\settings.json"
    ip = "192.168.10.42"

    try:
        raise RuntimeError(
            f"token={token} url={url} path={path} peer={ip}"
        )
    except RuntimeError:
        record = logging.LogRecord(
            name="DupeZ.LoggerRegression",
            level=logging.ERROR,
            pathname=path,
            lineno=1,
            msg=f"request failed at {url}",
            args=(),
            exc_info=sys.exc_info(),
        )

    rendered = _ScrubbingFormatter(
        "%(levelname)s %(pathname)s %(message)s"
    ).format(record)

    assert "RuntimeError" in rendered
    assert record.exc_text is not None
    for output in (rendered, record.exc_text):
        for private_value in (
            token,
            "user:pass",
            "/private",
            "query-canary",
            "SensitiveUser",
            ip,
        ):
            assert private_value not in output
        assert "https://example.test/[REDACTED]" in output
        assert "192.168.10.x" in output
