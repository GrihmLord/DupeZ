from __future__ import annotations

from pathlib import Path

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
    assert auth.read_and_consume_token_sentinel() == token
    assert not path.exists()
