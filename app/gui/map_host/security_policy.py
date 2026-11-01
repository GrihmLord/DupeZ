"""Fail-closed admission for remote content in the embedded native browser.

Version floors are a reviewed baseline, not a claim of vulnerability freedom.
No environment switch bypasses admission; frozen release validation is separate.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shlex
import sys


# Explicitly reviewed (Qt, WebEngine, Chromium security-backport) combinations.
# Empty on 2026-10-24: available Qt 6.11.2 wheels still lack Qt 6.11.3 fixes,
# and Chromium 151.0.7922.71 is only an installed baseline, not current security
# clearance. Updating Qt alone must never silently re-enable stale WebEngine.
# Add a combination only with exact-artifact/backport and sandbox evidence.
# This is deliberately not configurable through the environment or UI.
REVIEWED_NATIVE_COMBINATIONS: frozenset[tuple[str, str, str]] = frozenset()


@dataclass(frozen=True)
class WebEngineSecurityAssessment:
    allowed: bool
    reason: str


def _runtime_versions() -> tuple[str, str, str]:
    from PyQt6.QtCore import qVersion
    from PyQt6.QtWebEngineCore import (
        qWebEngineChromiumSecurityPatchVersion,
        qWebEngineVersion,
    )

    return qVersion(), qWebEngineVersion(), qWebEngineChromiumSecurityPatchVersion()


def _non_elevated_process() -> bool:
    if sys.platform != "win32":
        # Only the Windows token boundary is reviewed for this product.
        return False
    from app.gui.map_host.launcher import _Win32ShellLaunchApi

    return not _Win32ShellLaunchApi().current_process_is_elevated()


def _version(value: str, parts: int) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){" + str(parts - 1) + "}", value):
        raise ValueError("Unrecognized native runtime version")
    return tuple(int(part) for part in value.split("."))


def assess_webengine_security() -> WebEngineSecurityAssessment:
    """Inspect the current token, startup configuration and loaded native DLLs.

    This does not create a page or renderer. Errors and unknown platforms deny
    admission. Version floors are necessary but insufficient: an exact reviewed
    native combination is also required before embedded content is admitted.
    """
    deny = WebEngineSecurityAssessment
    try:
        if getattr(sys, "frozen", False):
            return deny(False, "This DupeZ build omits the embedded browser runtime; use the manual browser URL.")
        if not _non_elevated_process():
            return deny(False, "Embedded map requires a verified non-administrator Windows process.")
        environment = {key.casefold(): value for key, value in os.environ.items()}
        # Qt checks qEnvironmentVariableIsSet(), not the value's truthiness:
        # even an empty, whitespace-only or "0" value disables its sandbox.
        if "qtwebengine_disable_sandbox" in environment:
            return deny(False, "Embedded map is disabled because Chromium sandbox bypass is configured.")
        if environment.get("qtwebengine_remote_debugging", "").strip():
            return deny(False, "Embedded map is disabled while remote debugging is configured.")
        # These Qt overrides select executable or resource bytes independently
        # of the loaded DLL versions. The pinned PyInstaller Windows hook uses
        # embedded qt.conf instead, so no override is needed by our packaging.
        if any(key in environment for key in (
            "qtwebengineprocess_path",
            "qtwebengine_resources_path",
            "qtwebengine_locales_path",
        )):
            return deny(False, "Embedded map is disabled by an unreviewed browser executable or resource path.")
        from app.gui.map_host.renderer_tier import TIER_FLAGS

        reviewed_flags = {flag for value in TIER_FLAGS.values() for flag in shlex.split(value)}
        configured_flags = shlex.split(environment.get("qtwebengine_chromium_flags", ""))
        if any(flag not in reviewed_flags for flag in configured_flags):
            return deny(False, "Embedded map is disabled by unreviewed Chromium environment flags.")
        arguments = sys.argv[1:]
        # Qt consumes this suffix as Chromium arguments when the environment
        # override is absent. Keep it reviewed even when that override exists,
        # so removing the environment setting cannot enable an unsafe suffix.
        for index, argument in enumerate(arguments):
            if argument.casefold() == "--webengineargs":
                if any(flag not in reviewed_flags for flag in arguments[index + 1:]):
                    return deny(False, "Embedded map is disabled by unreviewed Chromium startup flags.")
                break
        flags = " ".join(arguments)
        if re.search(
            r"(?:--|-|/)(?:no-sandbox|no-zygote-sandbox|disable-sandbox|disable-(?:setuid|gpu|namespace)-sandbox|"
            r"disable-seccomp-filter-sandbox|single-process|in-process-gpu|disable-web-security|"
            r"disable-features|disable-site-isolation-trials|allow-running-insecure-content|"
            r"allow-file-access-from-files|unsafely-treat-insecure-origin-as-secure|"
            r"renderer-cmd-prefix|utility-cmd-prefix|browser-subprocess-path|"
            r"ignore-certificate-errors(?:-spki-list)?|"
            r"remote-debugging(?:-port|-pipe|-address)?)(?=[=\s\"']|$)", flags, re.IGNORECASE,
        ):
            return deny(False, "Embedded map is disabled by unsafe browser startup flags.")
        qt, engine, security = _runtime_versions()
        if not ((6, 11, 3) <= _version(qt, 3) < (6, 12, 0)):
            return deny(False, "Embedded map awaits a reviewed Qt 6.11.3-or-newer patch build.")
        if not ((6, 11, 2) <= _version(engine, 3) < (6, 12, 0)):
            return deny(False, "Embedded map requires a reviewed Qt WebEngine 6.11 patch build.")
        if _version(security, 4) < (151, 0, 7922, 71):
            return deny(False, "Embedded map requires newer Chromium security backports.")
        if (qt, engine, security) not in REVIEWED_NATIVE_COMBINATIONS:
            return deny(False, "Embedded map is disabled: no reviewed patched native-runtime combination is available.")
    except Exception:
        return deny(False, "Embedded map security could not be verified; use your normal browser manually.")
    return WebEngineSecurityAssessment(True, "Reviewed runtime and sandbox prerequisites are present.")
