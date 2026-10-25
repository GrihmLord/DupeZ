"""Security regressions for the elevated helper's logging boundary."""

from __future__ import annotations

import io
import logging
import os
import sys
from types import SimpleNamespace

import pytest

import dupez_helper


def test_windows_log_path_ignores_inherited_localappdata(monkeypatch) -> None:
    attacker_root = r"C:\attacker-controlled"
    trusted_root = r"C:\Users\Trusted\AppData\Local"
    monkeypatch.setenv("LOCALAPPDATA", attacker_root)
    monkeypatch.setattr(dupez_helper.os, "name", "nt")
    monkeypatch.setattr(
        dupez_helper,
        "_windows_local_appdata",
        lambda: trusted_root,
    )

    log_path = dupez_helper._helper_log_path()

    assert log_path == os.path.join(
        trusted_root,
        "DupeZ",
        "logs",
        "firewall_helper.log",
    )
    assert attacker_root not in log_path


@pytest.mark.skipif(sys.platform != "win32", reason="Windows known-folder test")
def test_windows_localappdata_resolver_ignores_environment(
    monkeypatch,
    tmp_path,
) -> None:
    attacker_root = tmp_path / "attacker-controlled"
    monkeypatch.setenv("LOCALAPPDATA", str(attacker_root))

    resolved = dupez_helper._windows_local_appdata()

    assert os.path.isabs(resolved)
    assert os.path.normcase(resolved) != os.path.normcase(str(attacker_root))


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 handle test")
def test_secure_windows_log_uses_a_pinned_append_handle(tmp_path) -> None:
    log_path = tmp_path / "Local" / "DupeZ" / "logs" / "firewall_helper.log"

    stream = dupez_helper._open_secure_windows_log(str(log_path))
    try:
        stream.write("secure-log-canary\n")
        stream.flush()
    finally:
        stream.close()

    assert log_path.read_text(encoding="utf-8") == "secure-log-canary\n"


@pytest.mark.parametrize("as_symlink", [False, True], ids=["junction", "symlink"])
def test_log_directory_rejects_reparse_components(
    monkeypatch,
    tmp_path,
    as_symlink: bool,
) -> None:
    log_directory = tmp_path / "Local" / "DupeZ" / "logs"
    log_directory.mkdir(parents=True)
    unsafe_component = log_directory.parent
    real_lstat = os.lstat

    def fake_lstat(path):
        metadata = real_lstat(path)
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(
            os.path.abspath(unsafe_component)
        ):
            return metadata
        mode = 0o120777 if as_symlink else metadata.st_mode
        attributes = (
            0
            if as_symlink
            else dupez_helper._FILE_ATTRIBUTE_REPARSE_POINT
        )
        return SimpleNamespace(
            st_mode=mode,
            st_file_attributes=attributes,
        )

    monkeypatch.setattr(dupez_helper.os, "lstat", fake_lstat)

    with pytest.raises(OSError, match="reparse point"):
        dupez_helper._assert_non_reparse_directories(
            str(log_directory),
            allow_missing=False,
        )


def test_secure_log_open_rejects_raced_destination_and_closes_handle(
    monkeypatch,
    tmp_path,
) -> None:
    log_path = tmp_path / "Local" / "DupeZ" / "logs" / "firewall_helper.log"
    handle = 411
    closed: list[int] = []
    monkeypatch.setattr(dupez_helper, "_win32_open_log_handle", lambda _path: handle)
    monkeypatch.setattr(
        dupez_helper,
        "_win32_handle_is_regular_non_reparse",
        lambda _handle: True,
    )
    monkeypatch.setattr(
        dupez_helper,
        "_win32_final_handle_path",
        lambda _handle: r"C:\attacker-controlled\firewall_helper.log",
    )
    monkeypatch.setattr(
        dupez_helper,
        "_consume_win32_log_handle",
        lambda _handle: pytest.fail("raced log handle was consumed"),
    )
    monkeypatch.setattr(dupez_helper, "_win32_close_handle", closed.append)

    with pytest.raises(OSError, match="outside its expected path"):
        dupez_helper._open_secure_windows_log(str(log_path))

    assert closed == [handle]


def test_secure_log_open_rejects_final_reparse_file_and_closes_handle(
    monkeypatch,
    tmp_path,
) -> None:
    log_path = tmp_path / "Local" / "DupeZ" / "logs" / "firewall_helper.log"
    handle = 412
    closed: list[int] = []
    monkeypatch.setattr(dupez_helper, "_win32_open_log_handle", lambda _path: handle)
    monkeypatch.setattr(
        dupez_helper,
        "_win32_handle_is_regular_non_reparse",
        lambda _handle: False,
    )
    monkeypatch.setattr(
        dupez_helper,
        "_win32_final_handle_path",
        lambda _handle: pytest.fail("reparse handle path was queried"),
    )
    monkeypatch.setattr(dupez_helper, "_win32_close_handle", closed.append)

    with pytest.raises(OSError, match="not a regular file"):
        dupez_helper._open_secure_windows_log(str(log_path))

    assert closed == [handle]


def test_logging_falls_back_to_stream_only_when_secure_open_fails(
    monkeypatch,
) -> None:
    configured: dict[str, object] = {}
    warnings: list[str] = []

    def fail_secure_open():
        raise OSError("injected secure-open failure")

    def capture_basic_config(**kwargs) -> None:
        configured.update(kwargs)

    helper_logger = logging.getLogger("dupez-helper")
    monkeypatch.setattr(dupez_helper, "_open_secure_helper_log", fail_secure_open)
    monkeypatch.setattr(dupez_helper.logging, "basicConfig", capture_basic_config)
    monkeypatch.setattr(helper_logger, "warning", warnings.append)

    dupez_helper._configure_logging()

    handlers = configured["handlers"]
    assert isinstance(handlers, list)
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler
    assert warnings == [
        "secure file logging unavailable; using stream-only logging"
    ]


def test_helper_formatter_scrubs_paths_ips_credentials_and_urls() -> None:
    canary = "helper-secret-canary-value"
    record = logging.LogRecord(
        name="dupez-helper",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            r"failure C:\Users\PrivateOperator\workspace "
            "target=192.168.50.77 "
            f"token={canary} "
            "https://example.invalid/private?signature=sensitive"
        ),
        args=(),
        exc_info=None,
    )

    rendered = dupez_helper._HelperScrubbingFormatter("%(message)s").format(
        record
    )

    assert "PrivateOperator" not in rendered
    assert "192.168.50.77" not in rendered
    assert canary not in rendered
    assert "signature=sensitive" not in rendered
    assert "[REDACTED]" in rendered


def test_every_helper_handler_uses_scrubbing_formatter(monkeypatch) -> None:
    configured: dict[str, object] = {}
    monkeypatch.setattr(
        dupez_helper,
        "_open_secure_helper_log",
        lambda: io.StringIO(),
    )
    monkeypatch.setattr(
        dupez_helper.logging,
        "basicConfig",
        lambda **kwargs: configured.update(kwargs),
    )

    dupez_helper._configure_logging()

    handlers = configured["handlers"]
    assert isinstance(handlers, list)
    assert handlers
    assert all(
        isinstance(handler.formatter, dupez_helper._HelperScrubbingFormatter)
        for handler in handlers
    )
