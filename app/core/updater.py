# app/core/updater.py — DupeZ Auto-Updater
"""
Checks GitHub releases for new versions and offers one-click download.

API: https://api.github.com/repos/GrihmLord/DupeZ/releases/latest
"""

import json
import threading
import webbrowser
from typing import Dict, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError
from app.logs.logger import log_info, log_error, log_warning

CURRENT_VERSION = "4.0.0"
GITHUB_REPO = "GrihmLord/DupeZ"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse version string like '4.0.0' or 'v4.0.0' into a comparable tuple."""
    v = v.lstrip("vV").strip()
    parts = []
    for p in v.split("."):
        # Handle pre-release suffixes like '4.0.0-beta1'
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)

class UpdateChecker:
    """Checks GitHub for new DupeZ releases."""

    def __init__(self):
        self.current_version = CURRENT_VERSION
        self.latest_version: Optional[str] = None
        self.latest_url: Optional[str] = None
        self.release_notes: Optional[str] = None
        self.download_url: Optional[str] = None
        self._checking = False
        self._result: Optional[Dict] = None

    def check_sync(self) -> Dict:
        """Check for updates synchronously. Returns result dict."""
        self._checking = True
        try:
            req = Request(RELEASES_API, headers={"User-Agent": f"DupeZ/{CURRENT_VERSION}"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag = data.get("tag_name", "")
            self.latest_version = tag.lstrip("vV")
            self.latest_url = data.get("html_url", RELEASES_URL)
            self.release_notes = data.get("body", "")

            # Find exe asset for download
            assets = data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe") or name.endswith(".zip"):
                    self.download_url = asset.get("browser_download_url")
                    break

            if not self.download_url:
                self.download_url = self.latest_url

            is_newer = _parse_version(self.latest_version) > _parse_version(self.current_version)

            self._result = {
                "update_available": is_newer,
                "current_version": self.current_version,
                "latest_version": self.latest_version,
                "release_url": self.latest_url,
                "download_url": self.download_url,
                "release_notes": self.release_notes,
            }
            log_info(f"Update check: current={self.current_version}, latest={self.latest_version}, update={'yes' if is_newer else 'no'}")
            return self._result

        except URLError as e:
            log_warning(f"Update check failed (network): {e}")
            return {"update_available": False, "error": f"Network error: {e}"}
        except Exception as e:
            log_error(f"Update check failed: {e}")
            return {"update_available": False, "error": str(e)}
        finally:
            self._checking = False

    def check_async(self, callback=None):
        """Check for updates in a background thread. Calls callback(result) when done."""
        def _worker():
            result = self.check_sync()
            if callback:
                callback(result)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def open_download(self):
        """Open the download URL in the default browser."""
        url = self.download_url or self.latest_url or RELEASES_URL
        webbrowser.open(url)
        log_info(f"Opened download URL: {url}")

    def open_releases(self):
        """Open the GitHub releases page."""
        webbrowser.open(RELEASES_URL)

    @property
    def is_checking(self) -> bool:
        return self._checking

    @property
    def last_result(self) -> Optional[Dict]:
        return self._result

# Module-level singleton
updater = UpdateChecker()

