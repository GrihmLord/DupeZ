"""Privacy regressions for fatal crash reports."""

from __future__ import annotations

import sys
from pathlib import Path

from app import main as app_main
from app.core.secrets_manager import get_scrubber


def test_traceback_scrubber_covers_credentials_urls_and_identifiers() -> None:
    known_secret = "registered-crash-canary"
    bearer = "bearer-crash-canary-123456"
    # Assemble high-confidence token shapes at runtime so this redaction test
    # does not itself trip the repository's source-secret scanner.
    api_key = "s" + "k-" + "ABCDEFGHIJKLMNOPQRSTUV"
    github_token = "gh" + "p_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    jwt = (
        "abcdefghij.klmnopqrst.uvwxyzABCD"
    )
    raw = (
        "C:\\Users\\Alice\\project\\module.py /home/bob/project.py\n"
        f"known={known_secret}\n"
        f"Authorization: Bearer {bearer}\n"
        f"api_key='{api_key}' token={github_token}\n"
        f"jwt={jwt}\n"
        "endpoint=https://user:password@example.test/hook?token=private\n"
        "target=192.168.1.99 mac=aa:bb:cc:dd:ee:ff\n"
    )
    scrubber = get_scrubber()
    scrubber.register(known_secret)
    try:
        rendered = app_main._scrub_traceback(raw)
    finally:
        scrubber.unregister(known_secret)

    for secret in (
        "Alice",
        "/home/bob/",
        known_secret,
        bearer,
        api_key,
        github_token,
        jwt,
        "user:password",
        "token=private",
        "192.168.1.99",
        "aa:bb:cc:dd:ee:ff",
    ):
        assert secret not in rendered
    assert "[REDACTED]" in rendered
    assert "example.test/[REDACTED]" in rendered
    assert "192.168.1.x" in rendered
    assert "aa:bb:cc:**:**:**" in rendered


def test_dump_crash_never_replays_raw_exception_to_stderr(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import app.core.app_paths as app_paths

    secret = "redact-me"  # pragma: allowlist secret
    monkeypatch.setattr(app_paths, "crashes_dir", lambda: tmp_path)
    try:
        raise RuntimeError(f"Authorization: Bearer {secret}")
    except RuntimeError:
        exctype, value, tb = sys.exc_info()
        app_main.dump_crash(exctype, value, tb)

    report = (tmp_path / "FATAL_CRASH.txt").read_text(encoding="utf-8")
    stderr = capsys.readouterr().err
    assert secret not in report
    assert secret not in stderr
    assert "Bearer [REDACTED]" in report
    assert "Bearer [REDACTED]" in stderr
