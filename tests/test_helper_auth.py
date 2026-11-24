from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.firewall_helper import auth


def test_token_sentinel_prefers_windows_profile_resolution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    isolated_root = tmp_path / "isolated"
    monkeypatch.setenv("LOCALAPPDATA", str(isolated_root))
    monkeypatch.setattr(
        auth,
        "_windows_local_appdata",
        lambda: canonical_root,
    )

    assert auth.token_sentinel_path() == (
        canonical_root / "DupeZ" / "helper_auth.tok"
    )


def test_token_sentinel_falls_back_to_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: None)

    assert auth.token_sentinel_path() == (
        tmp_path / "DupeZ" / "helper_auth.tok"
    )


def test_token_sentinel_round_trip_consumes_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        auth,
        "_windows_local_appdata",
        lambda: tmp_path,
    )
    token = bytes(range(auth.TOKEN_BYTES))

    path = auth.write_token_sentinel(token)

    assert path.is_file()
    assert auth._sentinel_permissions_are_private(path, os.lstat(path))
    assert auth.read_and_consume_token_sentinel() == token
    assert not path.exists()


def test_write_refuses_reparse_backed_sentinel_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "DupeZ"
    directory.mkdir()
    directory_stat = os.lstat(directory)
    real_is_reparse = auth._is_reparse_point
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    monkeypatch.setattr(
        auth,
        "_is_reparse_point",
        lambda file_stat: (
            auth._same_file_identity(directory_stat, file_stat)
            or real_is_reparse(file_stat)
        ),
    )

    with pytest.raises(auth.AuthenticationError, match="directory"):
        auth.write_token_sentinel(bytes(range(auth.TOKEN_BYTES)))

    assert not (directory / "helper_auth.tok").exists()


def test_read_refuses_reparse_sentinel_without_following_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    token = bytes(range(auth.TOKEN_BYTES))
    path = auth.write_token_sentinel(token)
    sentinel_stat = os.lstat(path)
    real_is_reparse = auth._is_reparse_point
    monkeypatch.setattr(
        auth,
        "_is_reparse_point",
        lambda file_stat: (
            auth._same_file_identity(sentinel_stat, file_stat)
            or real_is_reparse(file_stat)
        ),
    )

    assert auth.read_and_consume_token_sentinel() is None
    assert path.read_bytes() == token


def test_read_never_returns_token_when_cleanup_cannot_be_confirmed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    token = bytes(range(auth.TOKEN_BYTES))
    path = auth.write_token_sentinel(token)
    monkeypatch.setattr(auth, "_unlink_exact_leaf", lambda *_args: False)

    assert auth.read_and_consume_token_sentinel() is None

    assert not path.exists()
    claims = list(path.parent.glob(".helper-auth-claim-*.tmp"))
    assert len(claims) == 1
    assert claims[0].read_bytes() == b""


def test_write_cleans_random_staging_file_when_replace_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)

    def _fail_replace(*_args) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(auth.os, "replace", _fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        auth.write_token_sentinel(bytes(range(auth.TOKEN_BYTES)))

    directory = tmp_path / "DupeZ"
    assert not (directory / "helper_auth.tok").exists()
    assert list(directory.glob(".helper-auth-write-*.tmp")) == []


def test_write_refuses_existing_reparse_sentinel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    original = bytes(range(auth.TOKEN_BYTES))
    path = auth.write_token_sentinel(original)
    sentinel_stat = os.lstat(path)
    real_is_reparse = auth._is_reparse_point
    monkeypatch.setattr(
        auth,
        "_is_reparse_point",
        lambda file_stat: (
            auth._same_file_identity(sentinel_stat, file_stat)
            or real_is_reparse(file_stat)
        ),
    )

    with pytest.raises(auth.AuthenticationError, match="non-reparse"):
        auth.write_token_sentinel(b"x" * auth.TOKEN_BYTES)

    assert path.read_bytes() == original


def test_replacing_stale_sentinel_wipes_old_file_before_install(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    original = b"o" * auth.TOKEN_BYTES
    replacement = b"n" * auth.TOKEN_BYTES
    path = auth.write_token_sentinel(original)
    original_stat = os.lstat(path)
    real_wipe = auth._wipe_and_unlink_regular
    wiped_old: list[bool] = []

    def observe_wipe(candidate, expected) -> bool:
        if auth._same_file_identity(original_stat, expected):
            wiped_old.append(True)
        return real_wipe(candidate, expected)

    monkeypatch.setattr(auth, "_wipe_and_unlink_regular", observe_wipe)

    auth.write_token_sentinel(replacement)

    assert wiped_old == [True]
    assert path.read_bytes() == replacement


def test_discard_token_sentinel_wipes_and_removes_pending_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_windows_local_appdata", lambda: tmp_path)
    path = auth.write_token_sentinel(b"s" * auth.TOKEN_BYTES)

    assert auth.discard_token_sentinel() is True
    assert not path.exists()
    assert auth.discard_token_sentinel() is True
