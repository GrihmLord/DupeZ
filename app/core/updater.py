# app/core/updater.py — DupeZ Auto-Updater
"""
Checks GitHub releases for new versions.  Can either open the browser
or download the new installer directly and launch it for a seamless
upgrade-in-place experience.

API: https://api.github.com/repos/GrihmLord/DupeZ/releases/latest
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request

from app.__version__ import __version__
from app.core import safe_subprocess
from app.core.safe_subprocess import SafeSubprocessError
from app.core.secure_http import (
    MAX_RESPONSE_SIZE_BYTES,
    _get_tls_context,
    _open_no_redirect,
)
from app.core.update_state import DowngradeRefusedError, compare_versions
from app.core.update_verify import (
    SigVerifyError,
    UpdateManifest,
    verify_installer_authenticode,
    verify_installer_sha256,
    verify_manifest_and_enforce_monotonic,
)
from app.core.windows_attachment import (
    AttachmentServicesError,
    apply_attachment_services,
    verify_attachment_evidence,
)
from app.core.validation import validate_url
from app.logs.logger import log_error, log_info, log_warning

__all__ = [
    "CURRENT_VERSION",
    "GITHUB_REPO",
    "LATEST_INSTALLER_URL",
    "RELEASES_API",
    "RELEASES_URL",
    "UpdateChecker",
    "PreparedUpdate",
    "updater",
]

# Re-exported from app.__version__ for backwards compatibility with the
# many call sites (dashboard title, About dialog, update checker) that
# already import CURRENT_VERSION from this module. The single source of
# truth is app/__version__.py — do NOT hardcode the version here.
CURRENT_VERSION = __version__
GITHUB_REPO = "GrihmLord/DupeZ"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
# Stable versionless alias — resolves via GitHub 302 redirect to the current
# release's DupeZ_Setup.exe asset. Using this as the install target means the
# updater always pulls the latest setup without needing to rebuild the URL
# for each release. Landing-page CTA and in-app updater share this alias.
LATEST_INSTALLER_URL = (
    f"https://github.com/{GITHUB_REPO}/releases/latest/download/DupeZ_Setup.exe"
)

_UPDATER_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_UPDATER_MAX_REDIRECTS = 2
_UPDATER_INITIAL_HOST = "github.com"
_UPDATER_CDN_HOST = "release-assets.githubusercontent.com"
_UPDATER_SAFE_CROSS_ORIGIN_HEADERS = frozenset(
    {"accept", "accept-encoding", "user-agent"}
)


class _UpdaterAssetError(ValueError):
    """A release asset URL or response failed the updater trust policy."""


class _UpdaterTarget(NamedTuple):
    """Canonical updater URL classification used by the redirect state machine."""

    kind: str
    url: str
    filename: Optional[str] = None
    tag: Optional[str] = None


def _close_updater_response(response: object) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            # A close failure must never replace the already-sanitized updater
            # result with an exception that can reproduce a signed CDN URL.
            pass


def _safe_updater_component(value: str, *, tag: bool = False) -> bool:
    allowed = "._-+" if tag else "._-"
    return bool(
        value
        and value not in {".", ".."}
        and len(value) <= 255
        and value[0].isascii()
        and value[0].isalnum()
        and all(character.isascii() and (character.isalnum() or character in allowed)
                for character in value)
    )


def _parse_updater_target(url: str) -> _UpdaterTarget:
    """Parse one canonical GitHub release or GitHub release-CDN URL."""
    if not isinstance(url, str) or any(
        ord(character) <= 0x20 or ord(character) == 0x7F or character == "\\"
        for character in url
    ):
        raise _UpdaterAssetError("updater asset URL is malformed")

    try:
        validated = validate_url(
            url,
            require_https=True,
            context="updater release asset",
        )
        parsed = urlsplit(validated)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise _UpdaterAssetError(
            f"updater asset URL was refused ({exc.__class__.__name__})"
        ) from exc

    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.hostname
    ):
        raise _UpdaterAssetError(
            "updater asset URLs cannot contain credentials or fragments"
        )
    if port not in {None, 443}:
        raise _UpdaterAssetError("updater asset HTTPS URL uses a non-default port")

    host = parsed.hostname.casefold()
    if host == _UPDATER_INITIAL_HOST:
        if parsed.netloc not in {
            _UPDATER_INITIAL_HOST,
            f"{_UPDATER_INITIAL_HOST}:443",
        }:
            raise _UpdaterAssetError("GitHub updater URL is not canonical")
        if parsed.query:
            raise _UpdaterAssetError("GitHub updater URL cannot contain a query")
        if "%2f" in parsed.path.casefold() or "%5c" in parsed.path.casefold():
            raise _UpdaterAssetError("GitHub updater URL contains encoded separators")

        parts = parsed.path.split("/")
        repo_parts = ["", *GITHUB_REPO.split("/"), "releases"]
        if len(parts) == 7 and parts[:4] == repo_parts:
            if parts[4:6] == ["latest", "download"]:
                filename = parts[6]
                if not _safe_updater_component(filename):
                    raise _UpdaterAssetError(
                        "GitHub updater URL has an unsafe asset filename"
                    )
                return _UpdaterTarget("alias", url, filename=filename)
            if parts[4] == "download":
                tag_name, filename = parts[5:7]
                if (
                    not _safe_updater_component(tag_name, tag=True)
                    or not _safe_updater_component(filename)
                ):
                    raise _UpdaterAssetError(
                        "GitHub updater URL has an unsafe tag or asset filename"
                    )
                return _UpdaterTarget(
                    "tagged",
                    url,
                    filename=filename,
                    tag=tag_name,
                )
        raise _UpdaterAssetError(
            "GitHub updater URL must be an exact release-download path"
        )

    if host == _UPDATER_CDN_HOST:
        if parsed.netloc not in {
            _UPDATER_CDN_HOST,
            f"{_UPDATER_CDN_HOST}:443",
        }:
            raise _UpdaterAssetError("release CDN URL is not canonical")
        if (
            not parsed.path.startswith("/github-production-release-asset/")
            or "%2f" in parsed.path.casefold()
            or "%5c" in parsed.path.casefold()
            or any(part in {"", ".", ".."} for part in parsed.path.split("/")[1:])
        ):
            raise _UpdaterAssetError("release CDN URL has an unexpected path")
        return _UpdaterTarget("cdn", url)

    raise _UpdaterAssetError("updater redirect target host is not allowed")


def _parse_initial_updater_url(url: str) -> _UpdaterTarget:
    target = _parse_updater_target(url)
    if target.kind not in {"alias", "tagged"}:
        raise _UpdaterAssetError(
            "initial updater URL must be an exact GitHub release download"
        )
    return target


def _validated_browser_release_url(url: object) -> str:
    """Accept only canonical, credential-free DupeZ GitHub release URLs."""
    if not isinstance(url, str) or any(
        ord(character) <= 0x20 or ord(character) == 0x7F or character == "\\"
        for character in url
    ):
        raise _UpdaterAssetError("browser release URL is malformed")

    try:
        validated = validate_url(
            url,
            require_https=True,
            context="updater browser release",
        )
        parsed = urlsplit(validated)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise _UpdaterAssetError("browser release URL was refused") from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != _UPDATER_INITIAL_HOST
        or parsed.netloc
        not in {_UPDATER_INITIAL_HOST, f"{_UPDATER_INITIAL_HOST}:443"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or "%2f" in parsed.path.casefold()
        or "%5c" in parsed.path.casefold()
    ):
        raise _UpdaterAssetError("browser release URL is not canonical")

    repo_parts = ["", *GITHUB_REPO.split("/"), "releases"]
    parts = parsed.path.split("/")
    if parts == repo_parts or parts == [*repo_parts, "latest"]:
        return url
    if (
        len(parts) == 6
        and parts[:4] == repo_parts
        and parts[4] == "tag"
        and _safe_updater_component(parts[5], tag=True)
    ):
        return url

    try:
        _parse_initial_updater_url(url)
    except (TypeError, ValueError) as exc:
        raise _UpdaterAssetError("browser release URL has an unexpected path") from exc
    return url


def _normalized_release_version(value: Optional[str]) -> str:
    return str(value or "").lstrip("vV").strip()


def _target_matches_release(target: _UpdaterTarget, expected_version: Optional[str]) -> bool:
    expected = _normalized_release_version(expected_version)
    return bool(
        not expected
        or (
            target.tag is not None
            and _normalized_release_version(target.tag) == expected
        )
    )


def _updater_redirect_target(current_url: str, location: object) -> _UpdaterTarget:
    if not isinstance(location, str) or not location:
        raise _UpdaterAssetError("updater redirect omitted a valid Location header")
    if any(
        ord(character) <= 0x20 or ord(character) == 0x7F or character == "\\"
        for character in location
    ):
        raise _UpdaterAssetError("updater redirect Location is malformed")

    try:
        target = urljoin(current_url, location)
    except (TypeError, ValueError) as exc:
        raise _UpdaterAssetError("updater redirect Location is malformed") from exc
    return _parse_updater_target(target)


def _updater_sidecar_url(asset_url: str, suffix: str) -> str:
    """Append a fixed sidecar suffix to a validated query-free GitHub URL."""
    if suffix not in {".manifest.json", ".manifest.sig"}:
        raise _UpdaterAssetError("unsupported updater sidecar suffix")
    target = _parse_initial_updater_url(asset_url)
    if target.filename is None:
        raise _UpdaterAssetError("updater asset filename is unavailable")
    try:
        parsed = urlsplit(asset_url)
    except ValueError as exc:
        raise _UpdaterAssetError("updater asset URL is malformed") from exc
    return urlunsplit(parsed._replace(path=parsed.path + suffix))


def _open_updater_asset(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: int,
    max_redirects: int = _UPDATER_MAX_REDIRECTS,
    expected_release_version: Optional[str] = None,
):
    """Open a GitHub release asset with bounded, validated redirects.

    The shared secure HTTP client deliberately refuses every redirect. Release
    assets are the narrow exception: GitHub's stable and versioned download
    URLs redirect to an HTTPS object host. Each hop is therefore submitted as
    a fresh no-redirect request after validation, and only innocuous headers
    survive a cross-origin hop.
    """
    if max_redirects < 0 or max_redirects > _UPDATER_MAX_REDIRECTS:
        raise _UpdaterAssetError(
            f"updater redirect limit must be between 0 and {_UPDATER_MAX_REDIRECTS}"
        )

    current_target = _parse_initial_updater_url(url)
    if current_target.kind == "tagged" and not _target_matches_release(
        current_target,
        expected_release_version,
    ):
        raise _UpdaterAssetError("updater asset tag does not match selected release")
    current_url = url
    current_headers = dict(headers or {})
    redirects = 0

    while True:
        try:
            request = Request(
                current_url,
                headers=current_headers,
                method="GET",
            )
            response = _open_no_redirect(
                request,
                timeout=timeout,
                context=_get_tls_context(),
            )
        except HTTPError as exc:
            try:
                status = int(exc.code)
            except (TypeError, ValueError) as status_exc:
                _close_updater_response(exc)
                raise _UpdaterAssetError(
                    "updater asset returned an invalid HTTP status"
                ) from status_exc
            if status not in _UPDATER_REDIRECT_CODES:
                _close_updater_response(exc)
                raise _UpdaterAssetError(
                    f"updater asset request failed with HTTP {status}"
                ) from exc
            location = exc.headers.get("Location") if exc.headers is not None else None
            _close_updater_response(exc)
        except (OSError, TypeError, URLError, ValueError) as exc:
            raise _UpdaterAssetError(
                f"updater asset transport failed ({exc.__class__.__name__})"
            ) from exc
        else:
            raw_status = getattr(response, "status", None)
            if raw_status is None:
                raw_status = getattr(response, "code", None)
            try:
                status = int(raw_status) if raw_status is not None else 200
            except (TypeError, ValueError) as exc:
                _close_updater_response(response)
                raise _UpdaterAssetError(
                    "updater asset returned an invalid HTTP status"
                ) from exc
            if status not in _UPDATER_REDIRECT_CODES:
                if 200 <= status < 300:
                    return response, current_url
                _close_updater_response(response)
                raise _UpdaterAssetError(
                    f"updater asset request failed with HTTP {status}"
                )
            response_headers = getattr(response, "headers", None)
            location = (
                response_headers.get("Location")
                if response_headers is not None
                else None
            )
            _close_updater_response(response)

        if current_target.kind == "cdn":
            raise _UpdaterAssetError("release CDN redirect was refused")
        if redirects >= max_redirects:
            raise _UpdaterAssetError(
                f"updater asset exceeded {max_redirects} redirects"
            )
        target = _updater_redirect_target(current_url, location)

        if current_target.kind == "alias":
            if (
                target.kind != "tagged"
                or target.filename != current_target.filename
                or not _target_matches_release(target, expected_release_version)
            ):
                raise _UpdaterAssetError(
                    "latest-release redirect did not preserve tag and asset identity"
                )
        elif current_target.kind == "tagged":
            if target.kind != "cdn":
                raise _UpdaterAssetError(
                    "tag-bound release redirect did not target the release CDN"
                )
            current_headers = {
                key: value
                for key, value in current_headers.items()
                if key.casefold() in _UPDATER_SAFE_CROSS_ORIGIN_HEADERS
            }
        else:
            raise _UpdaterAssetError("release CDN redirect was refused")

        redirects += 1
        current_target = target
        current_url = target.url


def _read_updater_asset(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: int,
    max_bytes: int = MAX_RESPONSE_SIZE_BYTES,
    expected_release_version: Optional[str] = None,
) -> bytes:
    """Read a small updater sidecar while retaining the secure size cap."""
    response, _final_url = _open_updater_asset(
        url,
        headers=headers,
        timeout=timeout,
        expected_release_version=expected_release_version,
    )
    try:
        try:
            data = response.read(max_bytes + 1)
        except Exception as exc:
            raise _UpdaterAssetError(
                f"updater asset response read failed ({exc.__class__.__name__})"
            ) from exc
        if len(data) > max_bytes:
            raise _UpdaterAssetError(
                f"updater asset exceeds max size ({max_bytes} bytes)"
            )
        return data
    finally:
        _close_updater_response(response)


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse a version string like ``'4.0.0'`` or ``'v4.0.0-beta1'``.

    Returns a comparable tuple of ints.  Non-numeric suffixes (e.g.
    ``'-beta1'``) are stripped from each component.
    """
    v = v.lstrip("vV").strip()
    parts: list[int] = []
    for segment in v.split("."):
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _get_install_dir() -> Optional[Path]:
    """Return the DupeZ install directory from registry, or None."""
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\DupeZ\DupeZ",
            0, winreg.KEY_READ,
        )
        val, _ = winreg.QueryValueEx(key, "InstallPath")
        winreg.CloseKey(key)
        p = Path(val)
        return p if p.is_dir() else None
    except Exception:
        return None


def _is_reparse_point(st: os.stat_result) -> bool:
    """Return whether *st* describes a Windows reparse-point target."""
    attributes = int(getattr(st, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _installer_identity(st: os.stat_result) -> Tuple[int, int, int, int]:
    """Return the stable fields used to detect replacement during hashing."""
    return (
        int(st.st_dev),
        int(st.st_ino),
        int(st.st_size),
        int(st.st_mtime_ns),
    )


def _assert_safe_installer_target(
    installer_path: str,
    private_dir: str,
) -> os.stat_result:
    """Validate that an installer is our private, non-reparse regular file.

    The checks are intentionally repeated around each hash and immediately
    before launch. They reject symlink/junction/reparse substitution, hard
    links, path escape, and unexpectedly broad POSIX permissions.
    """
    root = os.path.abspath(private_dir)
    target = os.path.abspath(installer_path)
    if os.path.normcase(os.path.dirname(target)) != os.path.normcase(root):
        raise SigVerifyError("installer target escaped its private directory")

    try:
        root_st = os.lstat(root)
        target_st = os.lstat(target)
    except OSError as exc:
        raise SigVerifyError(f"installer target is unavailable: {exc}") from exc

    if (
        not stat.S_ISDIR(root_st.st_mode)
        or stat.S_ISLNK(root_st.st_mode)
        or _is_reparse_point(root_st)
    ):
        raise SigVerifyError("installer private directory is unsafe or reparse-backed")
    if (
        not stat.S_ISREG(target_st.st_mode)
        or stat.S_ISLNK(target_st.st_mode)
        or _is_reparse_point(target_st)
    ):
        raise SigVerifyError("installer target is not a safe regular file")
    if int(getattr(target_st, "st_nlink", 1)) != 1:
        raise SigVerifyError("installer target has unexpected hard links")

    if os.name != "nt":
        if stat.S_IMODE(root_st.st_mode) & 0o077:
            raise SigVerifyError("installer private directory permissions are too broad")
        if stat.S_IMODE(target_st.st_mode) & 0o077:
            raise SigVerifyError("installer file permissions are too broad")
        if hasattr(os, "geteuid"):
            owner = os.geteuid()
            if root_st.st_uid != owner or target_st.st_uid != owner:
                raise SigVerifyError("installer target ownership is unexpected")

    return target_st


def _create_private_installer_target(filename: str) -> Tuple[str, str, int]:
    """Create a random directory and exclusive installer file.

    Returns ``(directory, path, fd)``. The descriptor is opened with
    no-inherit semantics where the platform exposes them; the caller writes
    the HTTP response through that descriptor so a pre-created global temp
    pathname can never be followed or truncated. POSIX permissions are
    restricted here; the Windows launch handoff additionally holds a native
    no-write/no-delete sharing lock from the final hash through CreateProcess.
    """
    if (
        not filename
        or filename in {".", ".."}
        or os.path.basename(filename) != filename
        or "\x00" in filename
    ):
        raise SigVerifyError(f"unsafe installer filename: {filename!r}")

    private_dir = tempfile.mkdtemp(prefix="DupeZ-Update-")
    installer_path = os.path.join(private_dir, filename)
    fd: Optional[int] = None
    try:
        os.chmod(private_dir, 0o700)
        root_st = os.lstat(private_dir)
        if (
            not stat.S_ISDIR(root_st.st_mode)
            or stat.S_ISLNK(root_st.st_mode)
            or _is_reparse_point(root_st)
        ):
            raise SigVerifyError("new installer directory is unsafe")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOINHERIT", 0))
        flags |= int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        fd = os.open(installer_path, flags, 0o600)
        os.chmod(installer_path, 0o600)
        _assert_safe_installer_target(installer_path, private_dir)
        return private_dir, installer_path, fd
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if os.path.lexists(installer_path):
                os.unlink(installer_path)
        except OSError:
            pass
        try:
            os.rmdir(private_dir)
        except OSError:
            pass
        raise


def _verify_safe_installer(
    installer_path: str,
    private_dir: str,
    manifest: UpdateManifest,
) -> None:
    """Hash a safe target and prove its identity did not change mid-hash."""
    before = _assert_safe_installer_target(installer_path, private_dir)
    verify_installer_sha256(installer_path, manifest)
    after = _assert_safe_installer_target(installer_path, private_dir)
    if _installer_identity(before) != _installer_identity(after):
        raise SigVerifyError("installer target changed while it was being verified")


def _windows_attachment_services_required() -> bool:
    """Return whether this launch must cross Windows Attachment Services."""
    return sys.platform == "win32"


def _apply_windows_attachment_evidence(
    installer_path: str,
    source_url: str,
) -> None:
    """Establish Windows origin evidence or convert failure to a closed gate."""
    try:
        evidence = apply_attachment_services(installer_path, source_url)
    except AttachmentServicesError as exc:
        raise SigVerifyError(
            "Windows attachment evidence could not be established "
            f"({exc.reason})"
        ) from exc
    log_info(
        "Windows Attachment Services accepted the installer "
        f"with Internet-zone evidence (zone {evidence.zone_id})."
    )


def _verify_windows_attachment_evidence(installer_path: str) -> None:
    """Fail closed if established attachment evidence is no longer present."""
    try:
        verify_attachment_evidence(installer_path)
    except AttachmentServicesError as exc:
        raise SigVerifyError(
            "Windows attachment evidence was not preserved "
            f"({exc.reason})"
        ) from exc


@contextmanager
def _locked_verified_installer(
    installer_path: str,
    private_dir: str,
    manifest: UpdateManifest,
) -> Iterator[None]:
    """Keep the verified Windows file immutable through process creation.

    Rehashing a pathname immediately before launch still leaves a small race:
    another process running as the same user can replace that pathname after
    the hash completes but before ``CreateProcess`` opens it. On Windows we
    therefore open the target with ``FILE_SHARE_READ`` only. The resulting
    handle denies writers, renames, and deletion until the caller has spawned
    the installer. Existing write/delete handles also make this open fail.

    The non-Windows fallback keeps a read descriptor open and retains the
    identity checks for tests and source-mode use. DupeZ release installers
    are Windows-only, so the Win32 sharing contract is the security boundary.
    """
    before = _assert_safe_installer_target(installer_path, private_dir)
    lock_handle: Optional[int] = None
    lock_fd: Optional[int] = None

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create_file.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int

        generic_read = 0x80000000
        file_share_read = 0x00000001
        open_existing = 3
        file_attribute_normal = 0x00000080
        raw_handle = create_file(
            os.path.abspath(installer_path),
            generic_read,
            file_share_read,
            None,
            open_existing,
            file_attribute_normal,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if raw_handle in {None, invalid_handle}:
            error_code = ctypes.get_last_error()
            raise SigVerifyError(
                "installer could not be locked against replacement "
                f"(Win32 error {error_code})"
            )
        lock_handle = int(raw_handle)
    else:
        flags = os.O_RDONLY
        flags |= int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            lock_fd = os.open(installer_path, flags)
        except OSError as exc:
            raise SigVerifyError(f"installer could not be locked: {exc}") from exc

    try:
        locked = _assert_safe_installer_target(installer_path, private_dir)
        if _installer_identity(before) != _installer_identity(locked):
            raise SigVerifyError("installer target changed before its launch lock")

        _verify_safe_installer(installer_path, private_dir, manifest)
        final = _assert_safe_installer_target(installer_path, private_dir)
        if _installer_identity(locked) != _installer_identity(final):
            raise SigVerifyError("installer target changed under its launch lock")
        yield
    finally:
        if lock_handle is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                ctypes.c_void_p(lock_handle)
            )
        if lock_fd is not None:
            os.close(lock_fd)


def _cleanup_private_installer_target(
    installer_path: Optional[str],
    private_dir: Optional[str],
) -> None:
    """Best-effort cleanup without recursively traversing an unsafe target."""
    if installer_path is not None:
        try:
            if os.path.lexists(installer_path):
                os.unlink(installer_path)
        except OSError:
            pass
    if private_dir is not None:
        try:
            os.rmdir(private_dir)
        except OSError:
            pass


class _ProcessIdentity(NamedTuple):
    """Stable identity captured for one updater cleanup target."""

    pid: int
    image_path: str
    creation_time: int


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", wintypes.HANDLE),
    ]


# A timed-out elevated taskkill may still be running. Retaining the already
# verified target handle keeps its process object alive and prevents Windows
# from reusing that PID until this updater exits. This list is expected to stay
# empty in normal operation and contain at most the few DupeZ processes found
# during a single update handoff.
_RETAINED_PROCESS_HANDLES: List[Tuple[object, int]] = []


def _normalize_windows_image_path(path: str) -> str:
    normalized = ntpath.normcase(ntpath.normpath(path))
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return normalized


def _trusted_dupez_image_paths(recognized_names: set[str]) -> set[str]:
    """Return exact executable paths that this DupeZ instance may stop.

    A basename alone is not identity: an unrelated application can also be
    named ``dupez.exe``. Portable sibling variants are trusted only beside the
    running frozen executable; installed variants are trusted only beneath the
    HKLM install directory.
    """
    roots: set[str] = set()
    current_image = _normalize_windows_image_path(sys.executable)
    if ntpath.basename(current_image).casefold() in recognized_names:
        roots.add(ntpath.dirname(current_image))
    install_dir = _get_install_dir()
    if install_dir is not None:
        roots.add(_normalize_windows_image_path(str(install_dir)))
    return {
        _normalize_windows_image_path(ntpath.join(root, name))
        for root in roots
        for name in recognized_names
    }


def _close_process_handle(kernel32, handle: int) -> None:
    if not handle:
        return
    try:
        close_handle = kernel32.CloseHandle
        try:
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
        except (AttributeError, TypeError):
            pass
        close_handle(handle)
    except AttributeError:
        pass


def _open_process(kernel32, pid: int, access: int) -> int:
    try:
        open_process = kernel32.OpenProcess
    except AttributeError:
        return 0
    try:
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
    except (AttributeError, TypeError):
        pass
    return int(open_process(access, False, pid) or 0)


def _identity_from_handle(
    kernel32,
    handle: int,
    pid: int,
) -> Optional[_ProcessIdentity]:
    """Read full image path and creation time from one held process handle."""
    try:
        query_image = kernel32.QueryFullProcessImageNameW
        get_process_times = kernel32.GetProcessTimes
    except AttributeError:
        return None
    try:
        query_image.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query_image.restype = wintypes.BOOL
        get_process_times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        get_process_times.restype = wintypes.BOOL
    except (AttributeError, TypeError):
        pass

    capacity = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(capacity.value)
    if not query_image(handle, 0, buffer, ctypes.byref(capacity)):
        return None
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not get_process_times(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    creation_time = (
        int(created.dwHighDateTime) << 32
    ) | int(created.dwLowDateTime)
    return _ProcessIdentity(
        pid=pid,
        image_path=_normalize_windows_image_path(buffer.value),
        creation_time=creation_time,
    )


def _snapshot_process_identity(
    kernel32,
    pid: int,
    trusted_image_paths: set[str],
) -> Optional[_ProcessIdentity]:
    """Capture a candidate only if its exact image path is trusted."""
    process_query_limited_information = 0x1000
    handle = _open_process(kernel32, pid, process_query_limited_information)
    if not handle:
        return None
    try:
        identity = _identity_from_handle(kernel32, handle, pid)
        if identity is None or identity.image_path not in trusted_image_paths:
            log_warning(
                "Refused updater cleanup candidate outside trusted DupeZ paths"
            )
            return None
        return identity
    finally:
        _close_process_handle(kernel32, handle)


def _open_matching_process(
    kernel32,
    expected: _ProcessIdentity,
    access: int,
) -> int:
    """Open and revalidate the exact path/creation identity for *expected*."""
    process_query_limited_information = 0x1000
    handle = _open_process(
        kernel32,
        expected.pid,
        access | process_query_limited_information,
    )
    if not handle:
        return 0
    actual = _identity_from_handle(kernel32, handle, expected.pid)
    if actual != expected:
        log_warning(
            "Refused updater cleanup because the captured PID identity changed"
        )
        _close_process_handle(kernel32, handle)
        return 0
    return handle


def _terminate_process_identity(kernel32, expected: _ProcessIdentity) -> bool:
    """Terminate only the process represented by an exact captured identity."""
    process_terminate = 0x0001
    handle = _open_matching_process(kernel32, expected, process_terminate)
    if not handle:
        return False
    try:
        terminate_process = kernel32.TerminateProcess
        try:
            terminate_process.argtypes = [wintypes.HANDLE, wintypes.UINT]
            terminate_process.restype = wintypes.BOOL
        except (AttributeError, TypeError):
            pass
        return bool(terminate_process(handle, 1))
    except AttributeError:
        return False
    finally:
        _close_process_handle(kernel32, handle)


def _dispatch_elevated_taskkill(
    kernel32,
    shell32,
    taskkill_path: str,
    expected: _ProcessIdentity,
) -> bool:
    """Elevate one PID while pinning its verified process object by handle."""
    process_query_limited_information = 0x1000
    target_handle = _open_matching_process(
        kernel32,
        expected,
        process_query_limited_information,
    )
    if not target_handle:
        return False

    taskkill_handle = 0
    retain_target = False
    try:
        parameters = subprocess.list2cmdline(
            ["/PID", str(expected.pid), "/T", "/F"]
        )
        info = _ShellExecuteInfoW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x00000040 | 0x00000100 | 0x00000400
        info.lpVerb = "runas"
        info.lpFile = taskkill_path
        info.lpParameters = parameters
        info.lpDirectory = os.path.dirname(taskkill_path)
        info.nShow = 0

        shell_execute_ex = shell32.ShellExecuteExW
        try:
            shell_execute_ex.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
            shell_execute_ex.restype = wintypes.BOOL
        except (AttributeError, TypeError):
            pass
        if not shell_execute_ex(ctypes.byref(info)) or not info.hProcess:
            return False
        taskkill_handle = int(info.hProcess)

        wait_for_single_object = kernel32.WaitForSingleObject
        try:
            wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait_for_single_object.restype = wintypes.DWORD
        except (AttributeError, TypeError):
            pass
        wait_result = int(wait_for_single_object(taskkill_handle, 30_000))
        if wait_result != 0:  # WAIT_OBJECT_0
            # PID reuse remains impossible while this retained handle keeps the
            # original process object alive. The OS closes it at updater exit.
            _RETAINED_PROCESS_HANDLES.append((kernel32, target_handle))
            retain_target = True
            log_warning(
                "Elevated taskkill did not finish promptly; retained target "
                "identity handle until updater exit"
            )
            return False
        return True
    except (AttributeError, OSError) as exc:
        log_warning(f"Elevated PID termination failed safely: {exc}")
        return False
    finally:
        _close_process_handle(kernel32, taskkill_handle)
        if not retain_target:
            _close_process_handle(kernel32, target_handle)


def _kill_dupez_processes(exclude_pid: Optional[int] = None) -> None:
    """Kill all running DupeZ processes except *exclude_pid* (us).

    DupeZ may be running elevated (High-IL) from the Compat variant or
    the helper process.  A Medium-IL ``taskkill`` can't touch those, so
    we first try a direct ``TerminateProcess`` via the Win32 API (which
    works for same-elevation peers), then fall back to one elevated,
    PID-scoped ``taskkill /PID ... /T /F`` as a last resort.

    This is intentionally best-effort: if a stray process can't be
    killed, the Inno installer's ``/CLOSEAPPLICATIONS`` or a reboot
    will mop it up.
    """
    if os.name != "nt":
        return

    my_pid = exclude_pid or os.getpid()
    recognized_names = {
        "dupez.exe",
        "dupez-gpu.exe",
        "dupez-compat.exe",
        "dupez_helper.exe",
    }
    trusted_image_paths = _trusted_dupez_image_paths(recognized_names)
    if not trusted_image_paths:
        log_warning("No trusted DupeZ executable roots; skipping process cleanup")
        return

    # ── Collect target PIDs via tasklist ──────────────────────────
    # Routed through safe_subprocess so we get audit-logging and an
    # absolute System32 path (no PATH hijack surface).
    try:
        tasklist_path = safe_subprocess.resolve_system_binary("tasklist")
    except SafeSubprocessError as e:
        log_warning(f"tasklist unavailable; skipping pid collection: {e}")
        return

    candidate_pids: set[int] = set()
    for exe in recognized_names:
        try:
            result = safe_subprocess.run(
                [tasklist_path, "/FI", f"IMAGENAME eq {exe}",
                 "/FO", "CSV", "/NH"],
                timeout=5.0,
                expect_returncode=None,  # rc=1 if no matches — fine
                intent="updater.tasklist_scan",
            )
            for line in result.stdout.strip().splitlines():
                parts = line.replace('"', "").split(",")
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        if pid != my_pid:
                            candidate_pids.add(pid)
                    except ValueError:
                        continue
        except SafeSubprocessError:
            continue

    if not candidate_pids:
        log_info("No other DupeZ processes found to kill before update.")
        return

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    targets = [
        identity
        for pid in sorted(candidate_pids)
        if (
            identity := _snapshot_process_identity(
                kernel32,
                pid,
                trusted_image_paths,
            )
        ) is not None
    ]
    if not targets:
        log_info("No verified DupeZ process identities found before update.")
        return

    log_info(
        f"Stopping {len(targets)} verified DupeZ process(es) before update"
    )

    # ── Phase 1: direct TerminateProcess (works for same-IL peers) ─
    remaining: List[_ProcessIdentity] = []
    for identity in targets:
        if _terminate_process_identity(kernel32, identity):
            log_info("  Terminated a verified DupeZ process")
            continue
        remaining.append(identity)

    if not remaining:
        return

    # ── Phase 2: elevated taskkill for High-IL processes ──────────
    # Use ShellExecuteExW(runas) so the UAC prompt fires only if needed and we
    # can wait on the exact taskkill process. The executable remains pinned to
    # the OS-reported System32; the shell must never PATH-search an elevation
    # target.
    try:
        taskkill_path = safe_subprocess.resolve_system_binary("taskkill")
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        for identity in remaining:
            if _dispatch_elevated_taskkill(
                kernel32,
                shell32,
                taskkill_path,
                identity,
            ):
                log_info(
                    "  Elevated taskkill completed for one verified DupeZ PID"
                )
    except Exception as exc:
        log_warning(f"  Elevated taskkill failed: {exc} — installer will retry")


class PreparedUpdate:
    """Own verified download files until the caller approves launch or cancels.

    Preparation never launches processes. Launch repeats trust checks after
    the caller's cleanup boundary and leaves process exit to that caller.
    """

    def __init__(
        self, dest: str, private_dir: str, manifest: UpdateManifest,
        manifest_bytes: bytes, sig_bytes: bytes, expected_version: Optional[str],
        on_done: Optional[Callable[[bool, str], None]],
    ) -> None:
        self._dest = dest
        self._private_dir = private_dir
        self._manifest = manifest
        self._manifest_bytes = manifest_bytes
        self._sig_bytes = sig_bytes
        self._expected_version = expected_version
        self._on_done = on_done
        self._lock = threading.Lock()
        self._state = "prepared"

    def cancel(self) -> bool:
        """Remove only our unlaunched temporary files; never interrupt launch."""
        with self._lock:
            if self._state != "prepared":
                return False
            self._state = "cancelled"
        _cleanup_private_installer_target(self._dest, self._private_dir)
        return True

    def __del__(self) -> None:
        # Qt may discard an undelivered signal when its receiver is deleted.
        # Retaining ownership here prevents that from orphaning the download.
        try:
            self.cancel()
        except Exception:
            pass

    def _complete(self, success: bool, message: str) -> None:
        if self._on_done is not None:
            try:
                self._on_done(success, message)
            except Exception as exc:
                log_error(f"Prepared update completion callback failed: {exc}")

    def launch(self) -> bool:
        """Begin one asynchronous launch after the owner confirms cleanup."""
        with self._lock:
            if self._state != "prepared":
                return False
            self._state = "launching"
        try:
            threading.Thread(
                target=self._launch_worker, daemon=True, name="UpdateLaunch",
            ).start()
        except Exception as exc:
            with self._lock:
                self._state = "failed"
            _cleanup_private_installer_target(self._dest, self._private_dir)
            self._complete(False, str(exc))
        return True

    def _launch_worker(self) -> None:
        try:
            manifest = verify_manifest_and_enforce_monotonic(
                self._manifest_bytes, self._sig_bytes,
                installed_version=CURRENT_VERSION,
                expected_release_version=self._expected_version,
                expected_installer_filename=self._manifest.installer_filename,
            )
            if manifest != self._manifest:
                raise SigVerifyError("signed update manifest changed after preparation")
            # Recheck before touching other processes, then again under the
            # native launch lock after process cleanup.
            _verify_safe_installer(self._dest, self._private_dir, manifest)
            verify_installer_authenticode(self._dest, manifest)
            _kill_dupez_processes(exclude_pid=os.getpid())
            with _locked_verified_installer(self._dest, self._private_dir, manifest):
                if _windows_attachment_services_required():
                    _verify_windows_attachment_evidence(self._dest)
                verify_installer_authenticode(self._dest, manifest)
                safe_subprocess.spawn_detached(
                    [self._dest, "/SILENT", "/CLOSEAPPLICATIONS"],
                    trusted_executable=False,
                    intent="updater.launch_verified_installer",
                )
        except Exception as exc:
            with self._lock:
                self._state = "failed"
            _cleanup_private_installer_target(self._dest, self._private_dir)
            log_error(f"Prepared update launch failed: {exc}")
            self._complete(False, str(exc))
            return
        with self._lock:
            self._state = "launched"
        # The installer owns its live image now; do not remove it or bypass
        # the GUI's cleanup and event-loop shutdown with os._exit.
        self._complete(True, self._dest)


class UpdateChecker:
    """Checks GitHub for new DupeZ releases and can download + launch
    the new installer for seamless upgrade."""

    def __init__(self) -> None:
        self.current_version: str = CURRENT_VERSION
        self.latest_version: Optional[str] = None
        self.latest_url: Optional[str] = None
        self.release_notes: Optional[str] = None
        self.download_url: Optional[str] = None
        self.installer_url: Optional[str] = None  # .exe Setup asset
        self._checking: bool = False
        self._downloading: bool = False
        self._result: Optional[Dict] = None

    # ── Synchronous check ─────────────────────────────────────────

    def check_sync(self) -> Dict:
        """Query GitHub releases API.  Returns a result dict."""
        self._checking = True
        try:
            from app.core.secure_http import secure_get_json
            data = secure_get_json(
                RELEASES_API,
                headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"},
                timeout=10,
            )
            if not data:
                return {"update_available": False, "error": "Empty API response"}

            tag = data.get("tag_name", "")
            self.latest_version = (
                tag[1:]
                if isinstance(tag, str) and tag.startswith(("v", "V"))
                else tag
            )
            self.latest_url = data.get("html_url", RELEASES_URL)
            self.release_notes = data.get("body", "")

            # Find installer and portable assets.
            # v5.3.0+ ships three assets:
            #   DupeZ-GPU.exe          (recommended standalone)
            #   DupeZ-Compat.exe       (fallback standalone)
            #   DupeZ_v5.3.0_Setup.exe (installer, bundles both)
            # Older releases shipped:
            #   DupeZ_Setup.exe  or  DupeZ_v5.2.4_Setup.exe
            #   dupez.exe        (single portable binary)
            # The logic below handles both naming conventions so that
            # v5.2.x clients checking against a v5.3.0+ release still
            # find valid download URLs.
            self.download_url = None
            self.installer_url = None
            _api_installer: Optional[str] = None
            _gpu_url: Optional[str] = None
            _compat_url: Optional[str] = None
            _portable_url: Optional[str] = None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                url = asset.get("browser_download_url", "")
                if not url:
                    continue
                if "setup" in name and name.endswith(".exe"):
                    if name == "dupez_setup.exe" and isinstance(tag, str):
                        try:
                            candidate = _parse_initial_updater_url(url)
                            if (
                                candidate.kind != "tagged"
                                or candidate.filename != "DupeZ_Setup.exe"
                                or candidate.tag != tag
                            ):
                                raise _UpdaterAssetError(
                                    "release API installer identity mismatch"
                                )
                        except (TypeError, ValueError):
                            log_warning(
                                "Ignoring release API installer with invalid "
                                "origin, tag, or filename"
                            )
                        else:
                            _api_installer = url
                elif name.endswith(".exe") or name.endswith(".zip"):
                    if "gpu" in name:
                        _gpu_url = url
                    elif "compat" in name:
                        _compat_url = url
                    else:
                        _portable_url = url

            # Portable preference: GPU > legacy single exe > Compat
            self.download_url = _gpu_url or _portable_url or _compat_url

            # Prefer the exact tag-bound URL from this authenticated HTTPS API
            # response. The stable latest alias remains a compatibility
            # fallback when an older release omits the canonical asset entry.
            # Using one version-bound base keeps installer + sidecar fetches on
            # a single release even if a newer release appears mid-download.
            self.installer_url = _api_installer or LATEST_INSTALLER_URL

            # Prefer installer for upgrade-in-place, fall back to portable
            # exe, then release page.
            if not self.download_url:
                self.download_url = self.installer_url or _api_installer or self.latest_url

            # GitHub release tags conventionally carry a leading ``v``;
            # remove only that transport-level decoration, then delegate
            # ordering to the same strict SemVer comparator used by the
            # authenticated installer/version ledger.  In particular, a
            # pre-release sorts below its corresponding stable release and
            # malformed release tags can never win the ordering.
            cur_norm = self.current_version or ""
            lat_norm = self.latest_version or ""
            is_newer = compare_versions(lat_norm, cur_norm) > 0

            self._result = {
                "update_available": is_newer,
                "current_version": self.current_version,
                "latest_version": self.latest_version,
                "release_url": self.latest_url,
                "download_url": self.download_url,
                "installer_url": self.installer_url,
                "release_notes": self.release_notes,
            }
            log_info(
                f"Update check: current={self.current_version}, "
                f"latest={self.latest_version}, "
                f"update={'yes' if is_newer else 'no'}"
            )
            return self._result

        except URLError as e:
            log_warning(f"Update check failed (network): {e}")
            return {"update_available": False, "error": f"Network error: {e}"}
        except Exception as e:
            log_error(f"Update check failed: {e}")
            return {"update_available": False, "error": str(e)}
        finally:
            self._checking = False

    # ── Async wrapper ─────────────────────────────────────────────

    def check_async(self, callback: Optional[Callable] = None) -> None:
        """Check in a background thread.  Calls ``callback(result)`` when done."""
        def _worker() -> None:
            result = self.check_sync()
            if callback:
                callback(result)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Download & launch installer ──────────────────────────────

    def download_and_install(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
        *,
        on_prepared: Optional[Callable[[PreparedUpdate], None]] = None,
    ) -> None:
        """Download the new installer to temp and launch it.

        Always prefers the installer asset (``*Setup*.exe``) because it
        supports ``/SILENT /CLOSEAPPLICATIONS`` flags and upgrades in
        place via the stable Inno Setup AppId. If only a standalone exe
        is available (no installer in the release), fall back to opening
        the release page in the browser so the user can choose manually.

        Parameters
        ----------
        on_progress : callable(bytes_done, bytes_total)
            Progress callback (called from background thread).
        on_done : callable(success, message)
            Completion callback (called from background thread).
        on_prepared : callable(prepared_update), optional
            Receive a verified download without launching it. The caller
            must cancel or launch it after releasing owned resources. In
            this mode the updater never exits the current process.
        """
        # Only auto-install from the Setup installer. Standalone exes
        # (DupeZ-GPU.exe, DupeZ-Compat.exe, dupez.exe) can't be
        # launched with /SILENT and don't do in-place upgrades.
        url = self.installer_url
        expected_version = self.latest_version
        try:
            initial_target = _parse_initial_updater_url(url) if url else None
        except (TypeError, ValueError):
            log_error("Auto-update refused an invalid installer URL")
            if on_done:
                on_done(False, "Update refused: invalid installer URL")
            return
        installer_name = initial_target.filename if initial_target is not None else ""
        if (
            not url
            or not installer_name
            or "setup" not in installer_name.lower()
            or not installer_name.lower().endswith(".exe")
        ):
            # No installer asset found — open release page instead
            log_warning(
                "Auto-update: no installer asset found in release. "
                "Opening release page for manual download."
            )
            self.open_download()
            if on_done:
                on_done(False, "No installer found — opened release page")
            return

        def _worker() -> None:
            self._downloading = True
            dest: Optional[str] = None
            private_dir: Optional[str] = None
            download_fd: Optional[int] = None
            try:
                # Determine filename from URL
                fname = installer_name

                # ── Phase 1: fetch + verify signed manifest ───────────
                # The installer cannot be trusted until its SHA-256 has
                # been verified against a manifest signed by a pinned
                # Ed25519 key. Fetch the two sidecar artifacts first
                # (both are small — the updater's bounded reader enforces
                # hardened TLS and a response cap). Any failure here means we refuse
                # to download the installer at all.
                manifest_url = _updater_sidecar_url(url, ".manifest.json")
                sig_url = _updater_sidecar_url(url, ".manifest.sig")
                log_info(f"Fetching signed update metadata for {fname}")
                try:
                    manifest_bytes = _read_updater_asset(
                        manifest_url,
                        headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"},
                        timeout=30,
                        expected_release_version=expected_version,
                    )
                    sig_bytes = _read_updater_asset(
                        sig_url,
                        headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"},
                        timeout=30,
                        expected_release_version=expected_version,
                    )
                except Exception as e:
                    log_error(
                        f"Update refused: manifest/sig fetch failed: {e}. "
                        "Release must ship signed manifest artifacts."
                    )
                    if on_done:
                        on_done(
                            False,
                            "Update refused: signed manifest not available. "
                            "Please update manually from the release page.",
                        )
                    return

                try:
                    # v5.7.6: signature + downgrade-replay gate. If the
                    # incoming manifest version is strictly older than
                    # the highest version this install has ever accepted
                    # (HMAC'd ledger under app/data/update_state.json),
                    # we refuse — even with a valid signature. Closes
                    # the one-time-signing-key-compromise replay attack.
                    manifest = verify_manifest_and_enforce_monotonic(
                        manifest_bytes,
                        sig_bytes,
                        installed_version=CURRENT_VERSION,
                        expected_release_version=expected_version,
                        expected_installer_filename=fname,
                    )
                except SigVerifyError as e:
                    log_error(f"Update refused: manifest signature invalid: {e}")
                    if on_done:
                        on_done(False, f"Update refused (signature): {e}")
                    return
                except DowngradeRefusedError as e:
                    # Distinct branch — loud audit event, distinct user
                    # message. A downgrade attempt is qualitatively
                    # different from a bad signature: it means an
                    # authentic-but-stale manifest was offered.
                    log_error(
                        f"Update refused: DOWNGRADE-REPLAY suspected — {e}"
                    )
                    try:
                        from app.logs.audit import audit_event
                        audit_event("update_downgrade_refused", {
                            "reason": str(e),
                        })
                    except Exception:
                        pass
                    if on_done:
                        on_done(
                            False,
                            "Update refused: downgrade-replay protection "
                            "tripped. The server offered an older release "
                            "than this client has already accepted. "
                            "Please report this — it may indicate a "
                            "compromised mirror.",
                        )
                    return

                # Manifest-stated filename must match the URL we were
                # told to download. Prevents a manifest that authorises
                # A from being swapped onto a download of B.
                if manifest.installer_filename.lower() != fname.lower():
                    log_error(
                        f"Update refused: manifest filename {manifest.installer_filename!r} "
                        f"does not match download target {fname!r}"
                    )
                    if on_done:
                        on_done(False, "Update refused: installer filename mismatch")
                    return

                log_info(
                    f"Manifest verified: version={manifest.version}, "
                    f"installer={manifest.installer_filename}, "
                    f"sha256={manifest.installer_sha256[:16]}…, "
                    f"size={manifest.installer_size}"
                )

                # Create an unpredictable, owner-only directory and an
                # exclusive file only after all signed metadata bindings
                # pass. The download is written through the original fd,
                # never by reopening a predictable global temp pathname.
                private_dir, dest, download_fd = _create_private_installer_target(
                    fname
                )

                # ── Phase 2: stream-download the installer ────────────
                log_info(f"Downloading verified release asset {fname} → {dest}")

                # Follow only bounded, independently validated HTTPS redirects;
                # the shared HTTP client remains fail-closed for redirects.
                resp, _final_installer_url = _open_updater_asset(
                    url,
                    headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"},
                    timeout=60,
                    expected_release_version=expected_version,
                )
                try:
                    try:
                        total = (
                            int(resp.headers.get("Content-Length", 0))
                            or manifest.installer_size
                        )
                    except (TypeError, ValueError) as exc:
                        raise _UpdaterAssetError(
                            "updater asset returned invalid Content-Length"
                        ) from exc
                    # Hard cap: refuse to write more than the manifest says.
                    # Prevents an over-long response from filling disk before
                    # the hash check runs.
                    size_cap = manifest.installer_size
                    downloaded = 0
                    chunk_size = 1024 * 64  # 64 KB chunks

                    with os.fdopen(download_fd, "wb") as f:
                        download_fd = None  # fdopen owns and closes it from here.
                        while True:
                            try:
                                chunk = resp.read(chunk_size)
                            except Exception as exc:
                                raise _UpdaterAssetError(
                                    "updater asset response read failed "
                                    f"({exc.__class__.__name__})"
                                ) from exc
                            if not chunk:
                                break
                            if downloaded + len(chunk) > size_cap:
                                raise SigVerifyError(
                                    f"installer stream exceeded signed size "
                                    f"{size_cap} at {downloaded + len(chunk)}"
                                )
                            f.write(chunk)
                            downloaded += len(chunk)
                            if on_progress:
                                on_progress(downloaded, total)
                finally:
                    _close_updater_response(resp)

                log_info(f"Download complete: {dest} ({downloaded} bytes)")

                # ── Phase 3: verify installer bytes against manifest ──
                try:
                    _verify_safe_installer(dest, private_dir, manifest)
                except SigVerifyError as e:
                    log_error(f"Update refused: installer hash mismatch: {e}")
                    if on_done:
                        on_done(False, f"Update refused (hash): {e}")
                    return

                log_info(
                    "Installer hash verified against signed manifest — "
                    "verifying Windows publisher identity."
                )
                verify_installer_authenticode(dest, manifest)
                log_info(
                    "Installer Authenticode trust and signer certificate "
                    "match the signed update manifest."
                )

                if _windows_attachment_services_required():
                    # Attachment Services records the download source and runs
                    # the host's attachment/security providers. Save is a
                    # mutation boundary: providers may rewrite, quarantine, or
                    # delete the installer. Nothing verified above remains
                    # trusted until every signed binding is reopened and
                    # verified again below.
                    _apply_windows_attachment_evidence(dest, url)

                    try:
                        rescanned_manifest = verify_manifest_and_enforce_monotonic(
                            manifest_bytes,
                            sig_bytes,
                            installed_version=CURRENT_VERSION,
                            expected_release_version=expected_version,
                            expected_installer_filename=fname,
                        )
                    except (SigVerifyError, DowngradeRefusedError) as exc:
                        raise SigVerifyError(
                            "signed update manifest could not be reverified "
                            "after Windows attachment scanning"
                        ) from exc
                    if rescanned_manifest != manifest:
                        raise SigVerifyError(
                            "signed update manifest changed across Windows "
                            "attachment scanning"
                        )

                    _verify_safe_installer(dest, private_dir, manifest)
                    verify_installer_authenticode(dest, manifest)
                    log_info(
                        "Installer size, hash, signed manifest, and publisher "
                        "were reverified after Windows attachment scanning."
                    )

                if on_prepared is not None:
                    prepared = PreparedUpdate(
                        dest, private_dir, manifest, manifest_bytes, sig_bytes,
                        expected_version, on_done,
                    )
                    # Transfer ownership before invoking the caller. The
                    # prepared object also cleans up a discarded Qt signal.
                    dest = None
                    private_dir = None
                    try:
                        on_prepared(prepared)
                    except Exception:
                        prepared.cancel()
                        raise
                    return

                # Kill all other DupeZ processes so the installer can
                # overwrite files without "Access is denied" errors.
                _kill_dupez_processes(exclude_pid=os.getpid())

                # Launch the installer (it will upgrade in-place thanks to
                # same AppId and UsePreviousAppDir=yes in installer.iss).
                #
                # Revalidate and rehash after process cleanup while holding a
                # native Windows handle that denies writes, rename, and delete
                # until CreateProcess has opened the verified image.
                log_info(f"Final verification before installer launch: {dest}")
                launched_path = dest
                with _locked_verified_installer(dest, private_dir, manifest):
                    # Re-run both content and Windows publisher checks under
                    # the no-write/no-delete launch lock. Attachment evidence
                    # remains attached for Windows policy and provenance UI.
                    if _windows_attachment_services_required():
                        _verify_windows_attachment_evidence(dest)
                    verify_installer_authenticode(dest, manifest)
                    safe_subprocess.spawn_detached(
                        [dest, "/SILENT", "/CLOSEAPPLICATIONS"],
                        trusted_executable=False,
                        intent="updater.launch_verified_installer",
                    )
                # Handoff completed — do NOT delete `dest` in the finally
                # block: the installer we just launched is still reading it.
                dest = None
                private_dir = None

                if on_done:
                    on_done(True, launched_path)

                # Give the callback a moment to fire (e.g. update UI),
                # then exit this process so our own exe is unlocked for
                # the installer to overwrite.
                log_info("Exiting current process to release exe lock.")
                time.sleep(0.5)
                os._exit(0)

            except SigVerifyError as exc:
                log_error(f"Update signature verification failed: {exc}")
                if on_done:
                    on_done(False, f"Update refused (signature): {exc}")
            except Exception as exc:
                log_error(f"Update download failed: {exc}")
                if on_done:
                    on_done(False, str(exc))
            finally:
                if download_fd is not None:
                    try:
                        os.close(download_fd)
                    except OSError:
                        pass
                # If we bailed out before launch, remove only the exact file
                # and then the now-empty directory. Never recursively follow
                # anything an attacker may have inserted.
                _cleanup_private_installer_target(dest, private_dir)
                self._downloading = False

        threading.Thread(target=_worker, daemon=True, name="UpdateDownload").start()

    # ── Browser helpers ───────────────────────────────────────────

    def open_download(self) -> None:
        """Open a canonical DupeZ release URL in the default browser."""
        selected_url = RELEASES_URL
        for candidate in (self.download_url, self.latest_url, RELEASES_URL):
            if not candidate:
                continue
            try:
                selected_url = _validated_browser_release_url(candidate)
            except (TypeError, ValueError):
                continue
            break
        webbrowser.open(selected_url)
        log_info("Opened a validated DupeZ GitHub release URL")

    def open_releases(self) -> None:
        """Open the GitHub releases page."""
        webbrowser.open(RELEASES_URL)

    # ── Properties ────────────────────────────────────────────────

    @property
    def is_checking(self) -> bool:
        return self._checking

    @property
    def is_downloading(self) -> bool:
        return self._downloading

    @property
    def last_result(self) -> Optional[Dict]:
        return self._result

    @property
    def install_dir(self) -> Optional[Path]:
        """Return the installed DupeZ path from registry, or None."""
        return _get_install_dir()


# Module-level singleton
updater = UpdateChecker()
