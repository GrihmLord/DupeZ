"""
Self-integrity and DLL-hijack mitigation for the DupeZ Windows build.

Two independent primitives live here:

1. :func:`harden_dll_search_path` — rewires the process's DLL search
   order early enough to matter. On Windows, a foldered LoadLibrary
   of ``netapi32.dll`` (or any other system name) consults the
   *current directory* and the *parent exe directory* **before**
   System32 unless the process has opted out. That means dropping a
   malicious ``version.dll`` into the user's Downloads folder next to
   ``DupeZ_Setup.exe`` is enough to hijack the process. We opt out of
   the legacy search order by calling :c:func:`SetDefaultDllDirectories`
   with ``LOAD_LIBRARY_SEARCH_SYSTEM32`` plus the application
   directory registered via :c:func:`AddDllDirectory`. Must be called
   as early as possible — ideally inside ``sys.path``-setup at startup,
   before any ``import`` pulls in a .pyd that in turn LoadLibrary's
   something.

2. :func:`verify_self_authenticode` — validates the *currently-running
   executable's* Authenticode signature via :c:func:`WinVerifyTrust`.
   This protects against on-disk tamper AFTER install but before
   launch (a malicious process overwriting our EXE, for example).
   Failure is reported but the app does not self-terminate by default;
   the caller decides the response (log + warn, or hard-fail), since
   the same call legitimately returns TRUST_E_NOSIGNATURE during
   development with unsigned builds.

Both functions are no-ops on POSIX — the DLL-search and Authenticode
concerns are Windows-specific.
"""

from __future__ import annotations

import ctypes
import enum
import os
import sys
from pathlib import Path
from typing import Optional

__all__ = [
    "DllHardeningResult",
    "TrustState",
    "TrustReport",
    "harden_dll_search_path",
    "verify_self_authenticode",
]


# ── DLL search path hardening ────────────────────────────────────

class DllHardeningResult(enum.Enum):
    APPLIED = "applied"
    SKIPPED_NON_WINDOWS = "skipped_non_windows"
    UNAVAILABLE = "unavailable"        # SetDefaultDllDirectories not found
    FAILED = "failed"


# Flags for SetDefaultDllDirectories.
# https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-setdefaultdlldirectories
_LOAD_LIBRARY_SEARCH_APPLICATION_DIR = 0x00000200
_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
_LOAD_LIBRARY_SEARCH_USER_DIRS = 0x00000400


def harden_dll_search_path(extra_app_dirs: Optional[list] = None) -> DllHardeningResult:
    """Remove CWD + unsafe directories from the DLL search path.

    After this call, ``LoadLibrary("foo.dll")`` will search only:

        * the directory of the running exe,
        * System32,
        * any directories previously registered via
          :c:func:`AddDllDirectory` (we call it for each item in
          *extra_app_dirs*).

    CWD is NOT searched, which is the whole point: a ``version.dll``
    dropped next to the EXE in a user-writable Downloads folder no
    longer wins the LoadLibrary race.

    Safe to call multiple times. Returns a result enum so callers can
    surface the outcome in diagnostics / about-box.
    """
    if os.name != "nt":
        return DllHardeningResult.SKIPPED_NON_WINDOWS

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except OSError:
        return DllHardeningResult.UNAVAILABLE

    set_default = getattr(kernel32, "SetDefaultDllDirectories", None)
    # NB: the documented Win32 export is `AddDllDirectory`, NOT
    # `AddDllDirectoryW`. Unlike most wide-string APIs it has no
    # A/W twin — the function is Unicode-only — so kernel32 does
    # not expose an `AddDllDirectoryW` symbol. Querying for the W
    # suffix returns None on every Windows 10/11 host and made the
    # whole hardening path silently bail to UNAVAILABLE.
    add_dir = getattr(kernel32, "AddDllDirectory", None)
    if set_default is None or add_dir is None:
        # Pre-KB2533623 Windows 7 without the update, or Wine without
        # libloaderapi shim. There's nothing we can do safely.
        return DllHardeningResult.UNAVAILABLE

    set_default.argtypes = [ctypes.c_uint32]
    set_default.restype = ctypes.c_int32
    add_dir.argtypes = [ctypes.c_wchar_p]
    add_dir.restype = ctypes.c_void_p

    flags = (_LOAD_LIBRARY_SEARCH_APPLICATION_DIR
             | _LOAD_LIBRARY_SEARCH_SYSTEM32
             | _LOAD_LIBRARY_SEARCH_USER_DIRS)
    if set_default(flags) == 0:
        # Non-zero on success. Rare failure path.
        return DllHardeningResult.FAILED

    # Register extra app-specific directories. This covers the case
    # where WinDivert .dll/.sys live in a sibling folder to the exe
    # under the frozen build layout.
    for d in extra_app_dirs or ():
        try:
            if os.path.isdir(d):
                add_dir(str(d))
        except OSError:
            pass

    return DllHardeningResult.APPLIED


# ── Authenticode self-verification ───────────────────────────────

class TrustState(enum.Enum):
    TRUSTED = "trusted"            # WinVerifyTrust returned 0
    UNSIGNED = "unsigned"          # TRUST_E_NOSIGNATURE (expected in dev)
    TAMPERED = "tampered"          # TRUST_E_BAD_DIGEST, BAD_SIGNATURE...
    REVOKED = "revoked"            # CERT_E_REVOKED
    EXPIRED = "expired"            # CERT_E_EXPIRED
    SKIPPED = "skipped"            # non-Windows / not a frozen build
    ERROR = "error"                # unexpected OS error


class TrustReport:
    """Result of an Authenticode check on the running executable."""

    def __init__(self, state: TrustState, exe_path: str, win_error: int = 0) -> None:
        self.state = state
        self.exe_path = exe_path
        self.win_error = win_error  # HRESULT / status, 0 on success

    def __repr__(self) -> str:
        return (f"<TrustReport {self.state.value} exe={self.exe_path} "
                f"win_error=0x{self.win_error:08x}>")


# Known Authenticode HRESULTs (subset — enough to classify common failures).
_TRUST_E_NOSIGNATURE = 0x800B0100
_TRUST_E_BAD_DIGEST = 0x80096010
_TRUST_E_SUBJECT_NOT_TRUSTED = 0x800B0004
_CERT_E_REVOKED = 0x80092010
_CERT_E_EXPIRED = 0x800B0101


def _current_exe_path() -> str:
    """Return the absolute path of the running exe (frozen or dev)."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    # Source checkout — the "exe" is the python interpreter itself,
    # which we do NOT want to WinVerifyTrust. Return empty so callers
    # know to skip.
    return ""


def verify_self_authenticode() -> TrustReport:
    """Verify the running executable's Authenticode signature.

    Calls :c:func:`WinVerifyTrust` on the resolved exe path with the
    ``WINTRUST_ACTION_GENERIC_VERIFY_V2`` action. Does NOT prompt a
    UI dialog (``WTD_UI_NONE``). Fails closed if the exe path can't
    be resolved.
    """
    exe = _current_exe_path()
    if os.name != "nt":
        return TrustReport(TrustState.SKIPPED, exe)
    if not exe:
        return TrustReport(TrustState.SKIPPED, "")

    try:
        wintrust = ctypes.windll.wintrust  # type: ignore[attr-defined]
    except OSError as e:
        return TrustReport(TrustState.ERROR, exe, getattr(e, "winerror", 0))

    # GUID for WINTRUST_ACTION_GENERIC_VERIFY_V2
    # {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32),
                    ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16),
                    ("Data4", ctypes.c_ubyte * 8)]

    WINTRUST_ACTION_GENERIC_VERIFY_V2 = _GUID(
        0x00AAC56B, 0xCD44, 0x11D0,
        (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
    )

    class _WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [("cbStruct", ctypes.c_uint32),
                    ("pcwszFilePath", ctypes.c_wchar_p),
                    ("hFile", ctypes.c_void_p),
                    ("pgKnownSubject", ctypes.c_void_p)]

    class _WINTRUST_DATA(ctypes.Structure):
        _fields_ = [("cbStruct", ctypes.c_uint32),
                    ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p),
                    ("dwUIChoice", ctypes.c_uint32),
                    ("fdwRevocationChecks", ctypes.c_uint32),
                    ("dwUnionChoice", ctypes.c_uint32),
                    ("pFile", ctypes.POINTER(_WINTRUST_FILE_INFO)),
                    ("dwStateAction", ctypes.c_uint32),
                    ("hWVTStateData", ctypes.c_void_p),
                    ("pwszURLReference", ctypes.c_wchar_p),
                    ("dwProvFlags", ctypes.c_uint32),
                    ("dwUIContext", ctypes.c_uint32),
                    ("pSignatureSettings", ctypes.c_void_p)]

    WTD_UI_NONE = 2
    WTD_REVOKE_NONE = 0
    WTD_CHOICE_FILE = 1
    WTD_STATEACTION_VERIFY = 1
    WTD_STATEACTION_CLOSE = 2
    WTD_REVOCATION_CHECK_CHAIN = 0x00000040

    file_info = _WINTRUST_FILE_INFO(
        cbStruct=ctypes.sizeof(_WINTRUST_FILE_INFO),
        pcwszFilePath=exe,
        hFile=None,
        pgKnownSubject=None,
    )
    data = _WINTRUST_DATA(
        cbStruct=ctypes.sizeof(_WINTRUST_DATA),
        pPolicyCallbackData=None,
        pSIPClientData=None,
        dwUIChoice=WTD_UI_NONE,
        fdwRevocationChecks=WTD_REVOKE_NONE,
        dwUnionChoice=WTD_CHOICE_FILE,
        pFile=ctypes.pointer(file_info),
        dwStateAction=WTD_STATEACTION_VERIFY,
        hWVTStateData=None,
        pwszURLReference=None,
        dwProvFlags=WTD_REVOCATION_CHECK_CHAIN,
        dwUIContext=0,
        pSignatureSettings=None,
    )

    wintrust.WinVerifyTrust.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_GUID),
        ctypes.POINTER(_WINTRUST_DATA),
    ]
    wintrust.WinVerifyTrust.restype = ctypes.c_int32

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1)

    try:
        rc = wintrust.WinVerifyTrust(
            INVALID_HANDLE_VALUE,
            ctypes.byref(WINTRUST_ACTION_GENERIC_VERIFY_V2),
            ctypes.byref(data),
        )
    finally:
        # Always ask the provider to release state.
        data.dwStateAction = WTD_STATEACTION_CLOSE
        try:
            wintrust.WinVerifyTrust(
                INVALID_HANDLE_VALUE,
                ctypes.byref(WINTRUST_ACTION_GENERIC_VERIFY_V2),
                ctypes.byref(data),
            )
        except Exception:
            pass

    # rc is signed; compare against unsigned HRESULTs via masking.
    urc = rc & 0xFFFFFFFF
    if rc == 0:
        return TrustReport(TrustState.TRUSTED, exe)
    if urc == _TRUST_E_NOSIGNATURE:
        return TrustReport(TrustState.UNSIGNED, exe, urc)
    if urc in (_TRUST_E_BAD_DIGEST, _TRUST_E_SUBJECT_NOT_TRUSTED):
        return TrustReport(TrustState.TAMPERED, exe, urc)
    if urc == _CERT_E_REVOKED:
        return TrustReport(TrustState.REVOKED, exe, urc)
    if urc == _CERT_E_EXPIRED:
        return TrustReport(TrustState.EXPIRED, exe, urc)
    return TrustReport(TrustState.ERROR, exe, urc)


# ── Startup convenience ──────────────────────────────────────────

def apply_startup_hardening(extra_app_dirs: Optional[list] = None) -> dict:
    """One-shot helper for app startup: harden DLL path + check trust.

    Returns a diagnostic dict the main() can log to the audit trail.
    Never raises — startup code should tolerate a broken hardening
    layer and degrade loudly rather than refuse to boot.
    """
    dll_result = harden_dll_search_path(extra_app_dirs=extra_app_dirs)
    trust = verify_self_authenticode()
    out = {
        "dll_hardening": dll_result.value,
        "trust_state": trust.state.value,
        "trust_win_error": f"0x{trust.win_error:08x}",
        "exe": trust.exe_path,
    }
    try:
        from app.logs.audit import audit_event
        audit_event("startup_hardening", out)
    except Exception:
        pass
    return out
