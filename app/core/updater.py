# app/core/updater.py — DupeZ Auto-Updater
"""
Checks GitHub releases for new versions.  Can either open the browser
or download the new installer directly and launch it for a seamless
upgrade-in-place experience.

API: https://api.github.com/repos/GrihmLord/DupeZ/releases/latest
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen, urlretrieve

from app.__version__ import __version__
from app.logs.logger import log_error, log_info, log_warning

__all__ = [
    "CURRENT_VERSION",
    "GITHUB_REPO",
    "RELEASES_API",
    "RELEASES_URL",
    "UpdateChecker",
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
            self.latest_version = tag.lstrip("vV")
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
            _gpu_url: Optional[str] = None
            _compat_url: Optional[str] = None
            _portable_url: Optional[str] = None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                url = asset.get("browser_download_url", "")
                if not url:
                    continue
                if "setup" in name and name.endswith(".exe"):
                    self.installer_url = url
                elif name.endswith(".exe") or name.endswith(".zip"):
                    if "gpu" in name:
                        _gpu_url = url
                    elif "compat" in name:
                        _compat_url = url
                    else:
                        _portable_url = url

            # Portable preference: GPU > legacy single exe > Compat
            self.download_url = _gpu_url or _portable_url or _compat_url

            # Prefer installer for upgrade-in-place, fall back to
            # portable exe, then release page.
            if not self.download_url:
                self.download_url = self.installer_url or self.latest_url
            if not self.installer_url:
                self.installer_url = self.download_url

            is_newer = _parse_version(self.latest_version) > _parse_version(self.current_version)

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
        """
        # Only auto-install from the Setup installer. Standalone exes
        # (DupeZ-GPU.exe, DupeZ-Compat.exe, dupez.exe) can't be
        # launched with /SILENT and don't do in-place upgrades.
        url = self.installer_url
        if not url or "setup" not in url.rsplit("/", 1)[-1].lower():
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
            try:
                # Determine filename from URL
                fname = url.rsplit("/", 1)[-1]
                if not fname.lower().endswith(".exe"):
                    fname = f"DupeZ_Update_{self.latest_version}.exe"

                dest = os.path.join(tempfile.gettempdir(), fname)

                log_info(f"Downloading update: {url} → {dest}")

                # Download with progress
                req = Request(url, headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"})
                resp = urlopen(req, timeout=60)
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1024 * 64  # 64 KB chunks

                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)

                log_info(f"Download complete: {dest} ({downloaded} bytes)")

                # Strip MOTW from the downloaded installer
                try:
                    motw_path = dest + ":Zone.Identifier"
                    if os.path.exists(motw_path):
                        os.remove(motw_path)
                except Exception:
                    pass  # ADS removal is best-effort

                # Launch the installer (it will upgrade in-place thanks to
                # same AppId and UsePreviousAppDir=yes in installer.iss)
                log_info(f"Launching installer: {dest}")
                subprocess.Popen(
                    [dest, "/SILENT", "/CLOSEAPPLICATIONS"],
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                )

                if on_done:
                    on_done(True, dest)

            except Exception as exc:
                log_error(f"Update download failed: {exc}")
                if on_done:
                    on_done(False, str(exc))
            finally:
                self._downloading = False

        threading.Thread(target=_worker, daemon=True, name="UpdateDownload").start()

    # ── Browser helpers ───────────────────────────────────────────

    def open_download(self) -> None:
        """Open the download URL in the default browser."""
        url = self.download_url or self.latest_url or RELEASES_URL
        webbrowser.open(url)
        log_info(f"Opened download URL: {url}")

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
