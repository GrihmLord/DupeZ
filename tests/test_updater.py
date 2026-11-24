"""Tests for app.core.updater — version ordering and secure asset fetches."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from urllib.error import HTTPError, URLError

import pytest

from app.core import secure_http
from app.core import updater as updater_module
from app.core.update_verify import UpdateManifest
from app.core.updater import _parse_version, CURRENT_VERSION
from app.core.updater import UpdateChecker


class TestParseVersion:
    """Test the _parse_version helper."""

    def test_simple_version(self):
        """Standard semver string produces correct tuple."""
        assert _parse_version("4.0.0") == (4, 0, 0)

    def test_v_prefix(self):
        """Leading 'v' is stripped."""
        assert _parse_version("v4.1.0") == (4, 1, 0)

    def test_uppercase_v_prefix(self):
        """Leading 'V' is also stripped."""
        assert _parse_version("V3.2.1") == (3, 2, 1)

    def test_beta_suffix(self):
        """Non-numeric suffix is stripped from each segment."""
        assert _parse_version("v4.1.0-beta1") == (4, 1, 0)

    def test_two_part_version(self):
        """Two-part version string works."""
        assert _parse_version("4.1") == (4, 1)

    def test_single_number(self):
        """Single number returns single-element tuple."""
        assert _parse_version("5") == (5,)

    def test_empty_string(self):
        """Empty string returns tuple with zero."""
        assert _parse_version("") == (0,)

    def test_version_comparison(self):
        """Higher version compares greater."""
        assert _parse_version("4.1.0") > _parse_version("4.0.0")
        assert _parse_version("4.0.1") > _parse_version("4.0.0")
        assert _parse_version("5.0.0") > _parse_version("4.9.9")

    def test_equal_versions(self):
        """Same version strings compare equal."""
        assert _parse_version("4.0.0") == _parse_version("v4.0.0")


class TestCurrentVersion:
    """Test the CURRENT_VERSION constant."""

    def test_format(self):
        """CURRENT_VERSION is a valid dotted version string."""
        parts = CURRENT_VERSION.split(".")
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit()

    def test_parseable(self):
        """CURRENT_VERSION can be parsed by _parse_version."""
        result = _parse_version(CURRENT_VERSION)
        assert len(result) >= 2
        assert all(isinstance(x, int) for x in result)


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("5.8.0-rc.1", "v5.8.0", True),
        ("5.8.0", "v5.8.0-rc.1", False),
        ("5.8.0", "not-a-version", False),
        ("5.8.0", " 99.0.0 ", False),
    ],
)
def test_update_availability_uses_strict_semver(
    monkeypatch: pytest.MonkeyPatch,
    current: str,
    latest: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        secure_http,
        "secure_get_json",
        lambda *_args, **_kwargs: {
            "tag_name": latest,
            "html_url": "https://example.invalid/release",
            "body": "",
            "assets": [],
        },
    )
    checker = UpdateChecker()
    checker.current_version = current

    result = checker.check_sync()

    assert result["update_available"] is expected


def test_update_check_prefers_validated_tag_bound_api_installer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer_url = (
        "https://github.com/GrihmLord/DupeZ/releases/download/"
        "v9.0.0/DupeZ_Setup.exe"
    )
    monkeypatch.setattr(
        secure_http,
        "secure_get_json",
        lambda *_args, **_kwargs: {
            "tag_name": "v9.0.0",
            "html_url": "https://github.com/GrihmLord/DupeZ/releases/tag/v9.0.0",
            "body": "",
            "assets": [
                {
                    "name": "DupeZ_Setup.exe",
                    "browser_download_url": installer_url,
                }
            ],
        },
    )

    checker = UpdateChecker()
    checker.current_version = "8.0.0"
    result = checker.check_sync()

    assert checker.installer_url == installer_url
    assert result["installer_url"] == installer_url


def test_update_check_rejects_query_bearing_api_installer_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "signed-query-secret"
    messages: list[str] = []
    monkeypatch.setattr(
        secure_http,
        "secure_get_json",
        lambda *_args, **_kwargs: {
            "tag_name": "v9.0.0",
            "html_url": "https://github.com/GrihmLord/DupeZ/releases/tag/v9.0.0",
            "body": "",
            "assets": [
                {
                    "name": "DupeZ_Setup.exe",
                    "browser_download_url": (
                        "https://github.com/GrihmLord/DupeZ/releases/download/"
                        f"v9.0.0/DupeZ_Setup.exe?token={secret}"
                    ),
                }
            ],
        },
    )
    monkeypatch.setattr(updater_module, "log_warning", messages.append)

    checker = UpdateChecker()
    checker.current_version = "8.0.0"
    checker.check_sync()

    assert checker.installer_url == updater_module.LATEST_INSTALLER_URL
    assert messages
    assert secret not in "\n".join(messages)


class _FakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.closed = False
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.body) - self._offset
        chunk = self.body[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _TrackedRedirectError(HTTPError):
    def __init__(self, url: str, location: str) -> None:
        super().__init__(url, 302, "Found", {"Location": location}, None)
        self.was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


def _request_headers(request) -> dict[str, str]:
    return {key.casefold(): value for key, value in request.header_items()}


def test_updater_asset_follows_relative_and_cross_origin_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = updater_module.LATEST_INSTALLER_URL
    first = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "/GrihmLord/DupeZ/releases/download/v9.0.0/DupeZ_Setup.exe"
            )
        },
    )
    second = _TrackedRedirectError(
        start,
        "https://release-assets.githubusercontent.com/github-production-release-asset/1",
    )
    final = _FakeResponse(b"signed release bytes")
    requests = []
    outcomes = iter((first, second, final))

    def fake_open(request, **_kwargs):
        requests.append(request)
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(updater_module, "_open_no_redirect", fake_open)

    body = updater_module._read_updater_asset(
        start,
        headers={
            "User-Agent": "DupeZ/test",
            "Authorization": "Bearer secret",
            "X-Api-Key": "also-secret",
        },
        timeout=5,
    )

    assert body == b"signed release bytes"
    assert [request.full_url for request in requests] == [
        start,
        "https://github.com/GrihmLord/DupeZ/releases/download/v9.0.0/"
        "DupeZ_Setup.exe",
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1",
    ]
    assert _request_headers(requests[1])["authorization"] == "Bearer secret"
    final_headers = _request_headers(requests[2])
    assert final_headers["user-agent"] == "DupeZ/test"
    assert "authorization" not in final_headers
    assert "x-api-key" not in final_headers
    assert first.closed
    assert second.was_closed
    assert final.closed


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "https://127.0.0.1/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "http://github.com/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "https://github.com/Other/Repo/releases/download/v1/Setup.exe",
        "https://GITHUB.COM/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "https://github.com:444/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "https://user@github.com/GrihmLord/DupeZ/releases/download/v1/Setup.exe",
        "https://github.com/GrihmLord/DupeZ/releases/download/v1/Setup.exe?token=x",
        "https://github.com/GrihmLord/DupeZ/releases/download/v1/Setup.exe#part",
        "https://github.com/GrihmLord/DupeZ/releases/arbitrary/Setup.exe",
        "https://github.com/GrihmLord/DupeZ/releases/download/v1%2Fbad/Setup.exe",
        "https://github.com/GrihmLord/DupeZ/releases/download/v1/Bad%2FSetup.exe",
    ],
)
def test_updater_asset_rejects_untrusted_initial_url(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    opened = False

    def fake_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("untrusted URL reached the network")

    monkeypatch.setattr(updater_module, "_open_no_redirect", fake_open)

    with pytest.raises(ValueError):
        updater_module._open_updater_asset(url, timeout=5)

    assert not opened


@pytest.mark.parametrize(
    "location",
    [
        None,
        "",
        "https://attacker.example/asset",
        "https://release-assets.githubusercontent.com.evil.example/asset",
        "http://release-assets.githubusercontent.com/asset",
        "https://127.0.0.1/asset",
        "https://127.1/asset",
        "https://2130706433/asset",
        "https://localhost./asset",
        "https://user:secret@example.com/asset",
        "https://[malformed",
        "/asset\nInjected: header",
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1",
        "/GrihmLord/DupeZ/releases/download/v9.0.0/Other_Setup.exe",
        "/Other/Repo/releases/download/v9.0.0/DupeZ_Setup.exe",
    ],
)
def test_updater_asset_closes_and_rejects_unsafe_redirect(
    monkeypatch: pytest.MonkeyPatch,
    location: str | None,
) -> None:
    response = _FakeResponse(
        status=302,
        headers={} if location is None else {"Location": location},
    )
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(ValueError):
        updater_module._open_updater_asset(
            updater_module.LATEST_INSTALLER_URL,
            timeout=5,
        )

    assert response.closed


def test_updater_asset_rejects_loop_and_redirect_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = updater_module.LATEST_INSTALLER_URL
    loop = _FakeResponse(status=302, headers={"Location": start})
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: loop,
    )
    with pytest.raises(ValueError, match="identity"):
        updater_module._open_updater_asset(start, timeout=5)
    assert loop.closed

    first = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "/GrihmLord/DupeZ/releases/download/v9.0.0/"
                "DupeZ_Setup.exe"
            )
        },
    )
    second = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "https://release-assets.githubusercontent.com/"
                "github-production-release-asset/1"
            )
        },
    )
    responses = iter((first, second))
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(ValueError, match="exceeded 1 redirects"):
        updater_module._open_updater_asset(start, timeout=5, max_redirects=1)
    assert first.closed and second.closed


def test_tag_bound_asset_allows_only_one_exact_cdn_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = (
        "https://github.com/GrihmLord/DupeZ/releases/download/"
        "v9.0.0/DupeZ_Setup.exe"
    )
    cdn = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1?sig=test-only"
    )
    redirect = _FakeResponse(status=302, headers={"Location": cdn})
    final = _FakeResponse(b"installer", status=206)
    requests = []
    outcomes = iter((redirect, final))

    def fake_open(request, **_kwargs):
        requests.append(request)
        return next(outcomes)

    monkeypatch.setattr(updater_module, "_open_no_redirect", fake_open)

    response, final_url = updater_module._open_updater_asset(
        start,
        headers={
            "User-Agent": "DupeZ/test",
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
        },
        timeout=5,
        expected_release_version="9.0.0",
    )

    assert response is final
    assert final_url == cdn
    assert len(requests) == 2
    final_headers = _request_headers(requests[1])
    assert final_headers["user-agent"] == "DupeZ/test"
    assert "authorization" not in final_headers
    assert "cookie" not in final_headers
    assert redirect.closed


def test_release_cdn_is_terminal_at_production_redirect_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert updater_module._UPDATER_MAX_REDIRECTS == 2
    start = updater_module.LATEST_INSTALLER_URL
    tagged = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "/GrihmLord/DupeZ/releases/download/v9.0.0/"
                "DupeZ_Setup.exe"
            )
        },
    )
    cdn = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "https://release-assets.githubusercontent.com/"
                "github-production-release-asset/1?sig=first"
            )
        },
    )
    forbidden = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "https://release-assets.githubusercontent.com/"
                "github-production-release-asset/2?sig=second"
            )
        },
    )
    responses = iter((tagged, cdn, forbidden))
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(ValueError, match="CDN redirect"):
        updater_module._open_updater_asset(
            start,
            timeout=5,
            expected_release_version="9.0.0",
        )

    assert tagged.closed and cdn.closed and forbidden.closed


def test_updater_asset_rejects_wrong_tag_before_or_during_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tagged = (
        "https://github.com/GrihmLord/DupeZ/releases/download/"
        "v8.0.0/DupeZ_Setup.exe"
    )
    opened = False

    def fail_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("wrong tag reached the network")

    monkeypatch.setattr(updater_module, "_open_no_redirect", fail_open)
    with pytest.raises(ValueError, match="tag does not match"):
        updater_module._open_updater_asset(
            tagged,
            timeout=5,
            expected_release_version="9.0.0",
        )
    assert not opened

    alias_redirect = _FakeResponse(status=302, headers={"Location": tagged})
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: alias_redirect,
    )
    with pytest.raises(ValueError, match="identity"):
        updater_module._open_updater_asset(
            updater_module.LATEST_INSTALLER_URL,
            timeout=5,
            expected_release_version="9.0.0",
        )
    assert alias_redirect.closed


@pytest.mark.parametrize("status", [200, 204, 206, 299])
def test_updater_asset_allows_terminal_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    response = _FakeResponse(status=status)
    monkeypatch.setattr(
        updater_module,
        "_open_no_redirect",
        lambda *_args, **_kwargs: response,
    )

    actual, final_url = updater_module._open_updater_asset(
        updater_module.LATEST_INSTALLER_URL,
        timeout=5,
    )

    assert actual is response
    assert final_url == updater_module.LATEST_INSTALLER_URL


def test_updater_asset_transport_error_does_not_expose_signed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "cdn-signed-query-secret"
    start = (
        "https://github.com/GrihmLord/DupeZ/releases/download/"
        "v9.0.0/DupeZ_Setup.exe"
    )
    redirect = _FakeResponse(
        status=302,
        headers={
            "Location": (
                "https://release-assets.githubusercontent.com/"
                f"github-production-release-asset/1?sig={secret}"
            )
        },
    )
    outcomes = iter((redirect, None))

    def fake_open(request, **_kwargs):
        outcome = next(outcomes)
        if outcome is None:
            raise URLError(RuntimeError(f"network failure for {request.full_url}"))
        return outcome

    monkeypatch.setattr(updater_module, "_open_no_redirect", fake_open)

    with pytest.raises(ValueError) as captured:
        updater_module._open_updater_asset(start, timeout=5)

    assert secret not in str(captured.value)
    assert "release-assets.githubusercontent.com" not in str(captured.value)
    assert redirect.closed


def test_updater_response_close_error_cannot_leak_signed_query() -> None:
    secret = "close-signed-query-secret"

    class ResponseWithUnsafeClose:
        def close(self) -> None:
            raise URLError(
                "close failed for https://release-assets.githubusercontent.com/"
                f"github-production-release-asset/1?sig={secret}"
            )

    updater_module._close_updater_response(ResponseWithUnsafeClose())


def test_download_rejects_initial_query_without_logging_or_callback_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "initial-query-secret"
    logs: list[str] = []
    completed: list[tuple[bool, str]] = []
    checker = UpdateChecker()
    checker.latest_version = "9.0.0"
    checker.installer_url = updater_module.LATEST_INSTALLER_URL + f"?token={secret}"
    monkeypatch.setattr(updater_module, "log_error", logs.append)

    checker.download_and_install(
        on_done=lambda ok, message: completed.append((ok, message))
    )

    rendered = "\n".join(logs + [message for _ok, message in completed])
    assert completed == [(False, "Update refused: invalid installer URL")]
    assert secret not in rendered


def test_download_and_install_uses_redirect_aware_asset_fetchers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    payload = b"MZ redirect-aware installer"
    manifest = UpdateManifest(
        version="9.0.0",
        released_at="2026-08-27T00:00:00Z",
        installer_filename="DupeZ_Setup.exe",
        installer_sha256=hashlib.sha256(payload).hexdigest(),
        installer_size=len(payload),
        authenticode_signer_sha256="a" * 64,
    )
    metadata_calls: list[str] = []
    installer_calls: list[str] = []
    launched: list[list[str]] = []
    done: list[tuple[bool, str]] = []

    def read_asset(url: str, **_kwargs) -> bytes:
        metadata_calls.append(url)
        return b"manifest" if url.endswith(".manifest.json") else b"signature"

    def open_asset(url: str, **_kwargs):
        installer_calls.append(url)
        return _FakeResponse(
            payload,
            headers={"Content-Length": str(len(payload))},
        ), "https://release-assets.githubusercontent.com/final-installer"

    def create_target(filename: str):
        private_dir = tmp_path / "private"
        private_dir.mkdir(mode=0o700)
        target = private_dir / filename
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return str(private_dir), str(target), fd

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    @contextmanager
    def unlocked_verified(*_args, **_kwargs):
        yield

    monkeypatch.setattr(updater_module, "_read_updater_asset", read_asset)
    monkeypatch.setattr(updater_module, "_open_updater_asset", open_asset)
    monkeypatch.setattr(
        updater_module,
        "verify_manifest_and_enforce_monotonic",
        lambda *_args, **_kwargs: manifest,
    )
    monkeypatch.setattr(
        updater_module,
        "verify_installer_authenticode",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        updater_module,
        "_windows_attachment_services_required",
        lambda: False,
    )
    monkeypatch.setattr(updater_module, "_kill_dupez_processes", lambda **_kwargs: None)
    monkeypatch.setattr(updater_module, "_locked_verified_installer", unlocked_verified)
    monkeypatch.setattr(updater_module, "_create_private_installer_target", create_target)
    monkeypatch.setattr(
        updater_module.safe_subprocess,
        "spawn_detached",
        lambda argv, **_kwargs: launched.append(argv),
    )
    monkeypatch.setattr(updater_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(updater_module.os, "_exit", lambda _code: None)

    checker = UpdateChecker()
    checker.latest_version = "9.0.0"
    checker.installer_url = updater_module.LATEST_INSTALLER_URL
    checker.download_and_install(on_done=lambda ok, message: done.append((ok, message)))

    assert metadata_calls == [
        updater_module.LATEST_INSTALLER_URL + ".manifest.json",
        updater_module.LATEST_INSTALLER_URL + ".manifest.sig",
    ]
    assert installer_calls == [updater_module.LATEST_INSTALLER_URL]
    assert launched and launched[0][1:] == ["/SILENT", "/CLOSEAPPLICATIONS"]
    assert done and done[0][0] is True


@pytest.mark.parametrize(
    "url",
    [
        (
            "https://github.com/GrihmLord/DupeZ/releases/download/"
            "v9.0.0/DupeZ-GPU.exe"
        ),
        "https://github.com/GrihmLord/DupeZ/releases/tag/v9.0.0",
    ],
)
def test_open_download_accepts_canonical_dupez_release_urls(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    opened: list[str] = []
    messages: list[str] = []
    checker = UpdateChecker()
    checker.download_url = url
    monkeypatch.setattr(updater_module.webbrowser, "open", opened.append)
    monkeypatch.setattr(updater_module, "log_info", messages.append)

    checker.open_download()

    assert opened == [url]
    assert messages == ["Opened a validated DupeZ GitHub release URL"]


def test_open_download_rejects_private_or_noncanonical_api_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "".join(("browser-", "url-", "canary"))
    checker = UpdateChecker()
    checker.download_url = (
        "https://github.com/GrihmLord/DupeZ/releases/download/"
        f"v9.0.0/DupeZ-GPU.exe?signature={canary}"
    )
    checker.latest_url = (
        f"https://account:{canary}@github.com/"
        "GrihmLord/DupeZ/releases#fragment"
    )
    opened: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(updater_module.webbrowser, "open", opened.append)
    monkeypatch.setattr(updater_module, "log_info", messages.append)

    checker.open_download()

    assert opened == [updater_module.RELEASES_URL]
    assert canary not in "\n".join(messages)
    assert messages == ["Opened a validated DupeZ GitHub release URL"]
