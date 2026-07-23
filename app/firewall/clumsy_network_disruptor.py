#!/usr/bin/env python3
"""
Clumsy Network Disruptor — packet disruption for DupeZ.

Two engines:
  1. ClumsyEngine (automatic compatibility path) — launches clumsy.exe,
     verifies its layer, controls, values, and Start state via Win32
     SendMessageW, then hides the window. It is preferred whenever the
     request can be represented exactly.

  2. NativeWinDivertEngine — loads WinDivert.dll directly via ctypes and
     implements all public disruption modules with counter telemetry. It is
     selected for native-only behavior or a semantics-preserving fallback.

Architecture (clumsy.exe, from reading main.c):
  main() flow:
    1. ini_parse("presets.ini") × 6 — loads General + Preset1-5 from CWD
    2. init(argc, argv) — builds UI, loadConfig() reads config.txt from
       EXE directory (GetModuleFileName-relative)
    3. preset1_config() — sets module UI toggles from Preset1 struct
    4. startup() → IupShowXY → uiOnDialogShow → tryElevate → IupMainLoop

  GUI automation strategy (ClumsyEngine):
    1. Write presets.ini with [Preset1] module settings → CWD-relative
    2. Write config.txt with filter as FIRST entry → exe-dir-relative
    3. Launch clumsy.exe normally
    4. Find the "Start" button via EnumChildWindows
    5. Click it via SendMessageW(BM_CLICK)
    6. Verify button text changed to "Stop"
    7. Hide window off-screen via SetWindowPos
"""

from __future__ import annotations

import os
import sys
import time
import threading
import traceback
import ctypes
from dataclasses import dataclass

# Route process launches through safe_subprocess for path-pinning,
# audit events, hidden windows, and handle-inheritance policy.
try:
    from app.core import safe_subprocess as _safe_sp
    from app.core.safe_subprocess import SafeSubprocessError as _SafeSpErr
except Exception:
    _safe_sp = None  # type: ignore[assignment]
    _SafeSpErr = Exception  # type: ignore[misc,assignment]
from ctypes import wintypes
from typing import Any, Dict, List, Optional
from app.logs.logger import log_info, log_warning, log_error
from app.utils.helpers import mask_ip, _NO_WINDOW, is_admin

# Native WinDivert engine — primary engine (no GUI, no window)
try:
    from app.firewall.native_divert_engine import NativeWinDivertEngine
    NATIVE_ENGINE_AVAILABLE = True
    log_info("Native WinDivert engine available")
except ImportError as e:
    NATIVE_ENGINE_AVAILABLE = False
    log_info(f"Native WinDivert engine not available: {e} (falling back to clumsy.exe)")

__all__ = [
    "CREATE_NO_WINDOW",
    "GWL_EXSTYLE",
    "WS_EX_TOOLWINDOW",
    "WS_EX_LAYERED",
    "LWA_ALPHA",
    "SW_HIDE",
    "BM_CLICK",
    "BM_GETCHECK",
    "WM_GETTEXT",
    "WM_GETTEXTLENGTH",
    "WM_SETTEXT",
    "WM_CHAR",
    "WM_KEYDOWN",
    "WM_KEYUP",
    "WM_COMMAND",
    "EM_SETSEL",
    "VK_DELETE",
    "BST_CHECKED",
    "CB_GETCOUNT",
    "CB_GETCURSEL",
    "CB_GETLBTEXT",
    "CB_GETLBTEXTLEN",
    "CB_SETCURSEL",
    "CBN_SELCHANGE",
    "ENGINE_AUTO",
    "ENGINE_NATIVE",
    "ENGINE_CLUMSY",
    "ClumsyCompatibilityDecision",
    "assess_clumsy_compatibility",
    "MODULE_CHECKBOX_TEXT",
    "EDIT_INDEX_MAP",
    "WNDENUMPROC",
    "ClumsyEngine",
    "ClumsyNetworkDisruptor",
    "clumsy_network_disruptor",
    "disruption_manager",
]
CREATE_NO_WINDOW   = _NO_WINDOW  # re-exported alias for backward compat

# Window style constants
GWL_EXSTYLE        = -20
WS_EX_TOOLWINDOW   = 0x00000080
WS_EX_LAYERED      = 0x00080000
LWA_ALPHA           = 0x00000002
SW_HIDE             = 0

# Button messages
BM_CLICK            = 0x00F5
BM_GETCHECK         = 0x00F0
WM_GETTEXT          = 0x000D
WM_GETTEXTLENGTH    = 0x000E
WM_SETTEXT          = 0x000C
WM_CHAR             = 0x0102
WM_KEYDOWN          = 0x0100
WM_KEYUP            = 0x0101
WM_COMMAND          = 0x0111
EM_SETSEL            = 0x00B1
VK_DELETE            = 0x2E
BST_CHECKED          = 0x0001

# Combo-box messages used to select Clumsy's WinDivert layer.  Setting the
# selected index alone is insufficient: IUP only updates the C ``NetworkType``
# global when it receives the CBN_SELCHANGE notification.
CB_GETCURSEL         = 0x0147
CB_GETLBTEXT         = 0x0148
CB_GETLBTEXTLEN      = 0x0149
CB_GETCOUNT          = 0x0146
CB_SETCURSEL         = 0x014E
CBN_SELCHANGE        = 1
CB_ERR               = -1

# Public engine-preference values carried in params["_engine_preference"].
ENGINE_AUTO          = "auto"
ENGINE_NATIVE        = "native"
ENGINE_CLUMSY        = "clumsy"
_ENGINE_PREFERENCES  = frozenset({ENGINE_AUTO, ENGINE_NATIVE, ENGINE_CLUMSY})

# These public modules have matching user-facing semantics on the native
# implementation and bundled Clumsy after parameter normalization. Other
# Clumsy modules buffer/reorder/corrupt packets differently, so Auto must not
# silently switch those requests to native if the compatibility engine fails.
_NATIVE_CLUMSY_FALLBACK_METHODS = frozenset({
    "lag",
    "drop",
    "disconnect",
    "duplicate",
    "rst",
})

# Module name → clumsy UI checkbox text (from the screenshot)
MODULE_CHECKBOX_TEXT = {
    "lag":        "Lag",
    "drop":       "Drop",
    "disconnect": "Disconnect",
    "bandwidth":  "Bandwidth Limiter",
    "throttle":   "Throttle",
    "duplicate":  "Duplicate",
    "ood":        "Out of order",
    "corrupt":    "Tamper",
    "rst":        "Set TCP RST",
}

# EDIT control index → param_key
# Clumsy's EDIT controls sorted top-to-bottom by Y position.
# Module order (from main.c line 990): lag, drop, disconnect,
# bandwidth, throttle, duplicate, ood, tamper, reset.
# Each IupText becomes a Windows EDIT control.
#
#   0 = filter text (skip — set via config.txt)
#   1 = Lag Delay(ms)          — timeInput
#   2 = Drop Chance(%)         — chanceInput
#   (disconnect has NO text inputs)
#   3 = Bandwidth QueueSize    — queueSizeInput
#   4 = Bandwidth Limit(KB/s)  — bandwidthInput
#   5 = Throttle Timeframe(ms) — frameInput
#   6 = Throttle Chance(%)     — chanceInput
#   7 = Duplicate Count        — countInput
#   8 = Duplicate Chance(%)    — chanceInput
#   9 = Out of order Chance(%) — chanceInput
#  10 = Tamper Chance(%)       — chanceInput
#  11 = Set TCP RST Chance(%)  — chanceInput
EDIT_INDEX_MAP = {
    1:  "lag_delay",
    2:  "drop_chance",
    3:  "bandwidth_queue",
    4:  "bandwidth_limit",
    5:  "throttle_frame",
    6:  "throttle_chance",
    7:  "duplicate_count",
    8:  "duplicate_chance",
    9:  "ood_chance",
    10: "tamper_chance",
    11: "rst_chance",
}

_EDIT_PARAM_METHOD = {
    "lag_delay": "lag",
    "drop_chance": "drop",
    "bandwidth_queue": "bandwidth",
    "bandwidth_limit": "bandwidth",
    "throttle_frame": "throttle",
    "throttle_chance": "throttle",
    "duplicate_count": "duplicate",
    "duplicate_chance": "duplicate",
    "ood_chance": "ood",
    "tamper_chance": "corrupt",
    "rst_chance": "rst",
}

_EDIT_PARAM_DEFAULTS = {
    "lag_delay": 1500,
    "drop_chance": 95,
    "bandwidth_queue": 0,
    "bandwidth_limit": 1,
    "throttle_frame": 400,
    "throttle_chance": 100,
    "duplicate_count": 10,
    "duplicate_chance": 80,
    "ood_chance": 80,
    "tamper_chance": 60,
    "rst_chance": 90,
}

_MODULE_DIRECTION_KEYS = {
    "lag": ("lag_direction",),
    "drop": ("drop_direction",),
    "disconnect": ("disconnect_direction",),
    "bandwidth": ("bandwidth_direction",),
    "throttle": ("throttle_direction",),
    "duplicate": ("duplicate_direction",),
    "ood": ("ood_direction",),
    # Native currently keys this module as ``tamper``.  Reject the public
    # ``corrupt`` spelling too so a future key-alias fix cannot silently make
    # an explicit Clumsy selection asymmetric.
    "corrupt": ("tamper_direction", "corrupt_direction"),
    "rst": ("rst_direction",),
}

# EnumWindows callback type
#
# v5.7.1: gated on platform — ``ctypes.WINFUNCTYPE`` is a Windows-only
# attribute that doesn't exist on Linux/macOS, so importing this module
# under CI's ``ast-lint`` job (which runs on ubuntu-latest) used to
# crash here at module load. The callback is only invoked by
# ``_find_window_by_pid`` which is itself Windows-only (uses
# ``ctypes.windll.user32``), so making the type a ``None`` shim on
# non-Windows hosts is safe — calls into ``_find_window_by_pid`` are
# already gated by the OS-detection upstream.
if sys.platform.startswith("win"):
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:
    WNDENUMPROC = None  # type: ignore[assignment]
def _find_window_by_pid(pid: int, timeout: float = 5.0) -> Optional[int]:
    """Poll for a visible window belonging to `pid`. Returns HWND or None."""
    user32 = ctypes.windll.user32
    start = time.time()

    while time.time() - start < timeout:
        result = [None]

        def _cb(hwnd, _lparam):
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid and user32.IsWindowVisible(hwnd):
                result[0] = hwnd
                return False  # stop enumerating
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)

        if result[0]:
            return result[0]
        time.sleep(0.010)  # 10 ms poll

    return None

def _get_window_text(hwnd) -> str:
    """Get the text/title of a window handle."""
    try:
        user32 = ctypes.windll.user32
        length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
        return buf.value
    except Exception:
        return ""

def _find_child_by_text(parent_hwnd, target_text: str) -> Optional[int]:
    """Find a child window whose text matches `target_text` (case-insensitive)."""
    user32 = ctypes.windll.user32
    result = [None]
    target_lower = target_text.lower()

    def _cb(hwnd, _lparam):
        text = _get_window_text(hwnd)
        if text.lower() == target_lower:
            result[0] = hwnd
            return False  # stop
        return True

    user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(_cb), 0)
    return result[0]

def _find_children_by_class(parent_hwnd, class_name: str) -> list:
    """Find all child windows matching a window class name."""
    user32 = ctypes.windll.user32
    results = []
    target_lower = class_name.lower()

    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value.lower() == target_lower:
            results.append(hwnd)
        return True

    user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(_cb), 0)
    return results


def _combobox_items(combo_hwnd, user32=None) -> list[str]:
    """Return the visible item strings from a native Win32 combo box."""
    user32 = user32 or ctypes.windll.user32
    count = int(user32.SendMessageW(combo_hwnd, CB_GETCOUNT, 0, 0))
    if count <= 0:
        return []
    items: list[str] = []
    for index in range(count):
        length = int(user32.SendMessageW(
            combo_hwnd, CB_GETLBTEXTLEN, index, 0))
        if length < 0:
            return []
        buf = ctypes.create_unicode_buffer(length + 1)
        result = int(user32.SendMessageW(
            combo_hwnd, CB_GETLBTEXT, index, buf))
        if result == CB_ERR:
            return []
        items.append(buf.value)
    return items


def _select_combobox_item(combo_hwnd, index: int, user32=None) -> bool:
    """Select *index* and emit the notification consumed by IUP.

    ``CB_SETCURSEL`` changes only the widget's visual selection.  Clumsy's
    layer choice lives in a separate C global updated by its ACTION callback,
    so we explicitly send ``WM_COMMAND / CBN_SELCHANGE`` to the combo's real
    notification parent and verify the resulting index.
    """
    user32 = user32 or ctypes.windll.user32
    try:
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
    except (AttributeError, TypeError):
        # Lightweight fakes used by unit tests expose plain callables.
        pass
    selected = int(user32.SendMessageW(
        combo_hwnd, CB_SETCURSEL, int(index), 0))
    if selected == CB_ERR:
        return False

    parent_hwnd = user32.GetParent(combo_hwnd)
    control_id = int(user32.GetDlgCtrlID(combo_hwnd)) & 0xFFFF
    wparam = (CBN_SELCHANGE << 16) | control_id
    user32.SendMessageW(
        parent_hwnd, WM_COMMAND, wparam, combo_hwnd)
    actual = int(user32.SendMessageW(
        combo_hwnd, CB_GETCURSEL, 0, 0))
    return actual == int(index)


@dataclass(frozen=True)
class ClumsyCompatibilityDecision:
    """Pure result describing whether Clumsy can preserve a request."""

    representable: bool
    methods: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        """Return all incompatibilities as one operator-facing message."""
        return "; ".join(self.reasons)


def assess_clumsy_compatibility(
    methods: Any,
    params: Any,
) -> ClumsyCompatibilityDecision:
    """Return whether a native request has an equivalent Clumsy form.

    This function performs no I/O, logging, or mutation.  The returned method
    tuple is de-duplicated in caller order so both Auto fallback and explicit
    Clumsy startup use one deterministic module set.
    """
    reasons: list[str] = []
    deduplicated: list[str] = []

    if not isinstance(methods, (list, tuple)):
        reasons.append("methods must be a list or tuple")
    else:
        seen: set[str] = set()
        for method in methods:
            if not isinstance(method, str):
                reasons.append(f"non-string method is unsupported: {method!r}")
                continue
            if method not in seen:
                seen.add(method)
                deduplicated.append(method)

    if not deduplicated:
        reasons.append("at least one disruption method is required")

    unsupported = [
        method for method in deduplicated
        if method not in MODULE_CHECKBOX_TEXT
    ]
    if unsupported:
        reasons.append(
            "Clumsy has no equivalent core module for "
            + ", ".join(repr(method) for method in unsupported)
        )

    if not isinstance(params, dict):
        reasons.append("params must be a dictionary")
        return ClumsyCompatibilityDecision(
            representable=False,
            methods=tuple(deduplicated),
            reasons=tuple(reasons),
        )

    if params.get("direction", "both") != "both":
        reasons.append("Clumsy compatibility requires direction='both'")

    method_set = set(deduplicated)
    for method in deduplicated:
        for key in _MODULE_DIRECTION_KEYS.get(method, ()):
            if key in params and params[key] != "both":
                reasons.append(
                    f"Clumsy cannot preserve per-module direction {key}="
                    f"{params[key]!r}"
                )

    if "disconnect" in method_set:
        chance = params.get("disconnect_chance", 100)
        try:
            chance_is_full = int(chance) == 100
        except (TypeError, ValueError, OverflowError):
            chance_is_full = False
        if not chance_is_full:
            reasons.append(
                "Clumsy Disconnect is fixed at 100%; "
                f"disconnect_chance={chance!r} is not equivalent"
            )

        for key in (
            "disconnect_arm_delay_ms",
            "disconnect_duration_ms",
            "disconnect_quiet_after_ms",
        ):
            raw_value = params.get(key, 0) or 0
            try:
                is_zero = float(raw_value) == 0.0
            except (TypeError, ValueError, OverflowError):
                is_zero = False
            if not is_zero:
                reasons.append(
                    f"Clumsy has no equivalent for {key}={raw_value!r}"
                )

        if params.get("_auto_tune_duration"):
            reasons.append(
                "Clumsy has no equivalent for automatic disconnect duration"
            )

    if "lag" in method_set:
        passthrough = bool(params.get("lag_passthrough", False))
        if passthrough:
            reasons.append("Clumsy has no equivalent for lag passthrough")

        raw_delay = params.get("lag_delay", 1500)
        try:
            delay_ms = float(raw_delay)
        except (TypeError, ValueError, OverflowError):
            delay_ms = None
            reasons.append(f"lag_delay={raw_delay!r} is not numeric")

        preserve_connection = bool(
            params.get("lag_preserve_connection", False)
        )
        if preserve_connection:
            reasons.append(
                "Clumsy has no equivalent for lag connection preservation"
            )
        if delay_ms is not None and not 0 <= delay_ms <= 15_000:
            reasons.append(
                "bundled Clumsy supports lag_delay only from 0 to 15000ms; "
                f"got {raw_delay!r}"
            )

    if "duplicate" in method_set:
        raw_count = params.get("duplicate_count", 10)
        try:
            extra_count = int(raw_count)
        except (TypeError, ValueError, OverflowError):
            extra_count = None
            reasons.append(
                f"duplicate_count={raw_count!r} is not an integer"
            )
        if extra_count is not None and not 1 <= extra_count <= 49:
            reasons.append(
                "duplicate_count is defined as extra copies; bundled Clumsy "
                "can represent 1 to 49 extra copies (2 to 50 total); "
                f"got {raw_count!r}"
            )

    if params.get("_process_scope"):
        reasons.append(
            "process-scoped packet filters are unsupported at WinDivert "
            "NETWORK/NETWORK_FORWARD layers"
        )

    return ClumsyCompatibilityDecision(
        representable=not reasons,
        methods=tuple(deduplicated),
        reasons=tuple(reasons),
    )


def _normalize_engine_preference(value: Any) -> str:
    """Return a supported engine preference, defaulting safely to auto."""
    normalized = str(value or ENGINE_AUTO).strip().lower()
    if normalized not in _ENGINE_PREFERENCES:
        log_warning(
            f"Unknown engine preference {value!r}; using {ENGINE_AUTO!r}")
        return ENGINE_AUTO
    return normalized


def _clumsy_numeric_value(param_key: str, value: Any) -> int:
    """Translate DupeZ public numeric semantics to Clumsy UI semantics."""
    parsed = int(value)
    if param_key == "duplicate_count":
        # DupeZ exposes EXTRA copies. Clumsy's count includes the original.
        return parsed + 1
    return parsed


def _checkbox_matches_state(
    hwnd: Any,
    expected_state: int,
    user32: Any = None,
) -> bool:
    """Return whether a checkbox's visible state matches the request."""
    user32 = user32 or ctypes.windll.user32
    try:
        state = int(user32.SendMessageW(hwnd, BM_GETCHECK, 0, 0))
    except Exception:
        return False
    return state == int(expected_state)

def _click_button(hwnd) -> bool:
    """Click a button via SendMessageW(BM_CLICK). Works cross-process."""
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW(hwnd, BM_CLICK, 0, 0)
        return True
    except Exception as e:
        log_error(f"Failed to click button hwnd={hwnd}: {e}")
        return False

def _get_edit_controls_sorted(parent_hwnd) -> list:
    """Find all EDIT-class child windows, sorted by Y position (top to bottom).

    Clumsy's IupText controls become Windows EDIT controls. Sorting by Y
    gives us a consistent order matching the visual layout:
    [0]=filter, [1]=lag delay, [2]=drop chance, [3-5]=bandwidth, etc.
    """
    user32 = ctypes.windll.user32
    edits = _find_children_by_class(parent_hwnd, "EDIT")

    # Get screen rect for each EDIT and sort by top Y coordinate
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                     ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    edit_rects = []
    for hwnd in edits:
        rc = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        edit_rects.append((hwnd, rc.top, rc.left))

    # Sort by Y (top), then X (left) for same-row controls
    edit_rects.sort(key=lambda x: (x[1], x[2]))
    return [hwnd for hwnd, _y, _x in edit_rects]

def _type_into_edit(hwnd, value_str: str) -> str:
    """Clear an EDIT control and type a new value character by character.

    This triggers IUP's VALUECHANGED_CB on each keystroke, which syncs
    the C variable (lagTime, dropChance, etc.) via the SYNCED_VALUE mechanism.
    IupSetAttribute does NOT trigger this callback — only keyboard input does.
    """
    user32 = ctypes.windll.user32

    # Select all existing text
    user32.SendMessageW(hwnd, EM_SETSEL, 0, -1)
    # Delete selection
    user32.SendMessageW(hwnd, WM_KEYDOWN, VK_DELETE, 0)
    user32.SendMessageW(hwnd, WM_KEYUP, VK_DELETE, 0)

    # Type each character — this fires VALUECHANGED_CB per keystroke
    for ch in str(value_str):
        user32.SendMessageW(hwnd, WM_CHAR, ord(ch), 0)

    final = _get_window_text(hwnd)
    return final

def _hide_window(hwnd) -> bool:
    """Make a window completely invisible: transparent + no taskbar + hidden."""
    try:
        user32 = ctypes.windll.user32

        # 1. Add WS_EX_TOOLWINDOW (removes from taskbar / Alt+Tab)
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex_style | WS_EX_TOOLWINDOW | WS_EX_LAYERED)

        # 2. Set alpha to 0 — fully transparent (still processes messages)
        user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)

        # 3. Move window off-screen as extra insurance
        user32.SetWindowPos(hwnd, None, -32000, -32000, 0, 0, 0x0001 | 0x0015)

        # 4. Finally hide it
        user32.ShowWindow(hwnd, SW_HIDE)

        log_info(f"Window hwnd={hwnd} hidden successfully")
        return True
    except Exception as e:
        log_error(f"Failed to hide window hwnd={hwnd}: {e}")
        return False

def _kill_all_clumsy() -> None:
    """Kill every running clumsy.exe — only one can hold the WinDivert handle."""
    try:
        if _safe_sp is None:
            log_info("safe_subprocess unavailable — skipping taskkill sweep")
            return
        taskkill_path = _safe_sp.resolve_system_binary("taskkill")
        res = _safe_sp.run(
            [taskkill_path, "/F", "/IM", "clumsy.exe"],
            timeout=3.0,
            expect_returncode=None,  # rc=128 when no match — fine
            intent="clumsy.kill_all_preexisting",
        )
        out = (res.stdout or "").strip()
        if "SUCCESS" in out.upper():
            log_info(f"Killed existing clumsy.exe: {out}")
            time.sleep(0.05)  # Minimal pause — handle releases fast
        else:
            log_info("No existing clumsy.exe to kill")
    except _SafeSpErr as e:
        log_info(f"taskkill clumsy.exe: {e} (probably not running)")
    except Exception as e:
        log_info(f"taskkill clumsy.exe: {e} (probably not running)")
class ClumsyEngine:
    """Launch clumsy.exe and click its Start button via Win32 GUI automation.

    Automatic compatibility engine for exactly representable requests. The
    Clumsy window may flash briefly before DupeZ verifies and hides it.

    Strategy:
      1. Write presets.ini + config.txt
      2. Launch clumsy.exe (no CLI args)
      3. Find window, click checkboxes, click Start
      4. Hide the window
    """

    def __init__(self, clumsy_exe: str, clumsy_dir: str,
                 filter_str: str, methods: list, params: dict) -> None:
        self.clumsy_exe = clumsy_exe
        self.clumsy_dir = clumsy_dir
        self.filter_str = filter_str
        self.methods = methods
        self.params = params
        self._proc = None
        self._hwnd = None
        self._startup_verified = False
        self._runtime_verified = False

    # ---- helpers ----

    def _click_and_verify(self, cb_hwnd, cb_text: str,
                          expected_state=BST_CHECKED) -> bool:
        """Click a checkbox and verify it reached expected_state.
        Retries once on failure. Returns True if verified."""
        user32 = ctypes.windll.user32
        _click_button(cb_hwnd)
        time.sleep(0.05)
        state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
        if state == expected_state:
            log_info(f"  '{cb_text}': CONFIRMED "
                     f"{'checked' if expected_state == BST_CHECKED else 'unchecked'}")
            return True
        # Retry once
        log_error(f"  '{cb_text}': state={state}, expected={expected_state} — retrying")
        _click_button(cb_hwnd)
        time.sleep(0.05)
        state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
        if state == expected_state:
            log_info(f"  '{cb_text}': CONFIRMED on retry")
            return True
        log_error(f"  '{cb_text}': STILL wrong after retry (state={state})")
        return False

    def _find_checkbox(self, text: str) -> Any:
        """Find a checkbox by text, with fallback class search."""
        cb_hwnd = _find_child_by_text(self._hwnd, text)
        if not cb_hwnd:
            for btn in _find_children_by_class(self._hwnd, "BUTTON"):
                if _get_window_text(btn).lower() == text.lower():
                    return btn
        return cb_hwnd

    # ---- lifecycle ----

    def start(self) -> bool:
        """Kill old clumsy, write config, launch, click Start, hide."""
        self._startup_verified = False
        self._runtime_verified = False
        try:
            compatibility = assess_clumsy_compatibility(
                self.methods,
                self.params,
            )
            if not compatibility.representable:
                log_error(
                    "ClumsyEngine: request is not safely representable: "
                    f"{compatibility.reason}"
                )
                return False
            self.methods = list(compatibility.methods)

            # Step 0: Kill ANY existing clumsy.exe
            _kill_all_clumsy()

            # Step 1: Write config files BEFORE launching
            self._write_config()
            self._write_presets()

            # Verify both files exist and have content
            for fname, min_size in [("presets.ini", 100), ("config.txt", 10)]:
                fpath = os.path.join(self.clumsy_dir, fname)
                if not os.path.isfile(fpath):
                    log_error(f"FATAL: {fname} NOT FOUND at {fpath}")
                    return False
                fsize = os.path.getsize(fpath)
                log_info(f"{fname}: {fpath} ({fsize} bytes)")
                if fsize < min_size:
                    log_error(f"FATAL: {fname} too small ({fsize} bytes)")
                    return False

            # Step 2: Launch clumsy.exe
            exe = os.path.abspath(self.clumsy_exe)

            # Check if this is the modified clumsy with --silent support
            # by looking for a marker file or just trying it
            use_silent = self._detect_silent_support(exe)

            if use_silent:
                cmd_list = [exe, "--silent"]
                log_info(f"ClumsyEngine CMD (silent): {cmd_list}")
            else:
                cmd_list = [exe]
                log_info(f"ClumsyEngine CMD (GUI): {cmd_list}")

            log_info(f"ClumsyEngine CWD: {self.clumsy_dir}")
            log_info(f"ClumsyEngine FILTER (via config.txt): {self.filter_str}")

            # Step 3: Launch through safe_subprocess.spawn_managed so
            # the long-running child still has pid/poll/kill while all
            # central subprocess policy and audit hooks apply.
            if _safe_sp is None:
                log_error("ClumsyEngine: safe_subprocess unavailable")
                return False
            self._proc = _safe_sp.spawn_managed(
                cmd_list,
                cwd=self.clumsy_dir,
                trusted_executable=False,
                intent="clumsy.launch_long_running",
            )
            log_info(f"ClumsyEngine launched: PID={self._proc.pid}")

            if use_silent:
                # Quick check if process survived launch
                time.sleep(0.15)
                rc = self._proc.poll()
                if rc is not None:
                    log_info(f"ClumsyEngine: --silent mode failed (rc={rc}), "
                             f"falling back to GUI automation")
                    self._proc = None
                    cmd_list = [exe]
                    self._proc = _safe_sp.spawn_managed(
                        cmd_list,
                        cwd=self.clumsy_dir,
                        trusted_executable=False,
                        intent="clumsy.relaunch_gui_fallback",
                    )
                    log_info(f"ClumsyEngine relaunched (GUI): PID={self._proc.pid}")
                    return self._start_gui_automation()

                # --silent mode is running — no GUI automation needed
                log_info(f"ClumsyEngine: --silent mode active, no window visible")
            else:
                # No --silent support, use GUI automation
                return self._start_gui_automation()

            log_info(f"ClumsyEngine RUNNING: PID={self._proc.pid}, "
                     f"methods={self.methods}, filter={self.filter_str}")
            return True

        except Exception as e:
            log_error(f"ClumsyEngine start failed: {e}")
            log_error(traceback.format_exc())
            self._cleanup()
            return False

    def _detect_silent_support(self, exe_path: str) -> bool:
        """Return whether silent mode can honor the requested layer.

        Current Clumsy builds have no command-line contract for selecting
        Local versus Remote.  Compatibility mode therefore deliberately uses
        the GUI automation path, where the selection and callback can be
        verified before filtering starts.  Keep the binary probe for an
        actionable log if a future bundled binary reintroduces ``--silent``.
        """
        try:
            with open(exe_path, 'rb') as f:
                content = f.read()
            if b'--silent' in content:
                log_info(
                    "ClumsyEngine: --silent detected but disabled because "
                    "its Local/Remote layer cannot be verified"
                )
            else:
                log_info(
                    "ClumsyEngine: --silent NOT found in binary "
                    "(using verified GUI automation)"
                )
            return False
        except Exception as e:
            log_info(f"ClumsyEngine: could not check binary for --silent: {e}")
            return False

    def _start_gui_automation(self) -> bool:
        """Fallback: find clumsy window, click checkboxes, click Start, hide.

        Used when --silent mode is not supported by the clumsy.exe binary.
        """
        self._startup_verified = False
        try:
            # Find the clumsy window
            self._hwnd = _find_window_by_pid(self._proc.pid, timeout=2.0)
            if not self._hwnd:
                rc = self._proc.poll()
                if rc is not None:
                    log_error(f"ClumsyEngine GUI: process died (rc={rc})")
                    if rc == 1:
                        log_error("  rc=1 → presets.ini not found or parse error")
                    self._proc = None
                    return False
                self._hwnd = _find_window_by_pid(self._proc.pid, timeout=1.5)

            if not self._hwnd:
                log_error("ClumsyEngine GUI: could not find clumsy window")
                self._cleanup()
                return False

            title = _get_window_text(self._hwnd)
            log_info(f"ClumsyEngine GUI: found window hwnd={self._hwnd} title='{title}'")

            # The Clumsy source sets the network combo's visible value but
            # IUP does not invoke its ACTION callback for programmatic VALUE
            # changes.  Without this verified notification NetworkType stays
            # at zero (NETWORK_FORWARD), even when the UI says Local.
            if not self._select_network_layer():
                requested = (
                    "Local / NETWORK"
                    if self.params.get("_network_local")
                    else "Remote / NETWORK_FORWARD"
                )
                log_error(
                    "ClumsyEngine GUI: could not apply requested network "
                    f"layer ({requested}); refusing to start a silent no-op"
                )
                self._cleanup()
                return False

            # Every advertised control must be confirmed before filtering.
            try:
                modules_enabled = self._enable_modules()
            except Exception as exc:
                log_error(f"ClumsyEngine GUI: _enable_modules error: {exc}")
                modules_enabled = False
            if not modules_enabled:
                log_error(
                    "ClumsyEngine GUI: not every requested module was confirmed; "
                    "refusing to advertise an inactive disruption"
                )
                self._cleanup()
                return False

            for step, label in (
                (self._click_sub_checkboxes, "sub-checkboxes"),
                (self._set_input_values, "numeric inputs"),
            ):
                try:
                    verified = step()
                except Exception as exc:
                    log_error(
                        f"ClumsyEngine GUI: {step.__name__} error: {exc}"
                    )
                    verified = False
                if not verified:
                    log_error(
                        "ClumsyEngine GUI: requested "
                        f"{label} could not be confirmed; refusing to start"
                    )
                    self._cleanup()
                    return False

            # Click the Start button
            started = self._click_start_button()
            if not started:
                started = self._try_keybind_fallback()

            if not started:
                log_error("ClumsyEngine GUI: could not start filtering")
                self._cleanup()
                return False

            time.sleep(0.1)
            if self._proc.poll() is not None:
                log_error(f"ClumsyEngine GUI: process died (rc={self._proc.returncode})")
                self._proc = None
                self._startup_verified = False
                return False

            self._startup_verified = True

            # Hide the window
            _hide_window(self._hwnd)
            log_info(f"ClumsyEngine GUI: window hidden (hwnd={self._hwnd})")
            log_info(f"ClumsyEngine RUNNING: PID={self._proc.pid}, "
                     f"methods={self.methods}, filter={self.filter_str}")
            return True

        except Exception as e:
            log_error(f"ClumsyEngine GUI automation failed: {e}")
            log_error(traceback.format_exc())
            self._cleanup()
            return False

    def _select_network_layer(self) -> bool:
        """Select and verify Clumsy's Local or Remote WinDivert layer."""
        want_local = bool(self.params.get("_network_local", False))
        desired_word = "local" if want_local else "remote"

        combos = _find_children_by_class(self._hwnd, "COMBOBOX")
        for combo_hwnd in combos:
            items = _combobox_items(combo_hwnd)
            lowered = [item.lower() for item in items]
            local_indices = [
                i for i, item in enumerate(lowered) if "(local)" in item
            ]
            remote_indices = [
                i for i, item in enumerate(lowered) if "(remote)" in item
            ]
            # Requiring both labels avoids accidentally changing the preset,
            # trigger-mode, or timer combo boxes in this modified build.
            if not local_indices or not remote_indices:
                continue
            index = local_indices[0] if want_local else remote_indices[0]
            if not _select_combobox_item(combo_hwnd, index):
                log_error(
                    f"ClumsyEngine: network combo rejected {desired_word} "
                    f"selection (index={index}, items={items})"
                )
                return False
            actual_text = _get_window_text(combo_hwnd).lower()
            if desired_word not in actual_text:
                log_error(
                    "ClumsyEngine: network combo index changed but label "
                    f"verification failed (wanted={desired_word}, "
                    f"actual={actual_text!r})"
                )
                return False
            log_info(
                "ClumsyEngine: network layer CONFIRMED "
                f"{'NETWORK (Local)' if want_local else 'NETWORK_FORWARD (Remote)'}"
            )
            return True

        log_error(
            "ClumsyEngine: Local/Remote network COMBOBOX not found; "
            f"found {len(combos)} combo control(s)"
        )
        return False

    def _click_start_button(self) -> bool:
        """Find the 'Start' button in clumsy's window and click it.

        Returns True if the button was found, clicked, AND its text
        changed to 'Stop' (confirming filtering started).
        """
        user32 = ctypes.windll.user32

        # Enumerate ALL child windows and log them for diagnostics
        all_buttons = _find_children_by_class(self._hwnd, "BUTTON")
        log_info(f"ClumsyEngine: found {len(all_buttons)} BUTTON children")
        for btn in all_buttons:
            text = _get_window_text(btn)
            log_info(f"  BUTTON hwnd={btn} text='{text}'")

        # Find the Start button by text
        start_btn = _find_child_by_text(self._hwnd, "Start")
        if not start_btn:
            # Try "Start" with different casing or IUP formatting
            start_btn = _find_child_by_text(self._hwnd, "start")
        if not start_btn:
            # Search through all buttons for one containing "Start"
            for btn in all_buttons:
                text = _get_window_text(btn)
                if "start" in text.lower():
                    start_btn = btn
                    break

        if not start_btn:
            log_error("ClumsyEngine: 'Start' button NOT FOUND in window")
            return False

        log_info(f"ClumsyEngine: found Start button hwnd={start_btn}")

        # Click it
        _click_button(start_btn)
        log_info("ClumsyEngine: clicked Start button via BM_CLICK")

        # Brief pause for divertStart to execute
        time.sleep(0.15)

        # Verify: button text should now be "Stop"
        new_text = _get_window_text(start_btn)
        log_info(f"ClumsyEngine: button text after click = '{new_text}'")

        if new_text.lower() == "stop":
            log_info("ClumsyEngine: CONFIRMED — filtering started "
                     "(button changed to 'Stop')")
            return True

        # Button didn't change — maybe divertStart failed
        log_error(f"ClumsyEngine: button text is '{new_text}' (expected 'Stop') "
                  "— divertStart may have failed. Check filter syntax and admin.")
        return False

    def _enable_modules(self) -> bool:
        """Click module checkboxes to PROPERLY enable them via IUP callbacks.

        presets.ini sets ALL module inbound/outbound to FALSE, so all
        checkboxes start UNCHECKED after preset1_config() runs. We then
        click each needed checkbox ONCE → fires ACTION callback with ON
        → properly sets the C enabledFlag = 1.
        """
        enabled_count = 0
        for module_name in self.methods:
            cb_text = MODULE_CHECKBOX_TEXT.get(module_name)
            if not cb_text:
                log_info(f"  Module '{module_name}' has no checkbox mapping — skip")
                continue
            cb_hwnd = self._find_checkbox(cb_text)
            if not cb_hwnd:
                log_error(f"  Could not find '{cb_text}' checkbox in window")
                continue
            log_info(f"  Clicking '{cb_text}' checkbox (hwnd={cb_hwnd})")
            if self._click_and_verify(cb_hwnd, cb_text):
                enabled_count += 1

        log_info(f"_enable_modules: {enabled_count}/{len(self.methods)} "
                 "modules physically enabled")
        return bool(self.methods) and enabled_count == len(self.methods)

    def _click_sub_checkboxes(self) -> bool:
        """Apply and verify active-module sub-checkbox state.

        ``preset1_config`` updates visible state without firing the callbacks
        that synchronize Clumsy's C variables.  Active non-default requests
        therefore need a verified click; default requests still need their
        visible state confirmed.
        """
        p = self.params
        sub_checks = [
            ("throttle", "throttle_drop", "Drop Throttled", 0),
            ("corrupt", "tamper_checksum", "Redo Checksum", 1),
        ]
        all_verified = True

        for method, param_key, cb_text, c_default in sub_checks:
            if method not in self.methods:
                continue
            desired = bool(p.get(param_key, False))
            need_click = (c_default == 0 and desired) or (c_default == 1 and not desired)
            cb_hwnd = self._find_checkbox(cb_text)
            if not cb_hwnd:
                log_error(
                    f"  Sub-checkbox '{cb_text}' NOT FOUND; "
                    "requested state cannot be verified"
                )
                all_verified = False
                continue

            expected = BST_CHECKED if desired else 0
            if need_click:
                log_info(
                    f"  Clicking sub-checkbox '{cb_text}' "
                    f"(hwnd={cb_hwnd}, default={c_default}, desired={desired})"
                )
                verified = self._click_and_verify(
                    cb_hwnd,
                    cb_text,
                    expected_state=expected,
                )
            else:
                verified = _checkbox_matches_state(cb_hwnd, expected)
                log_info(
                    f"  Sub-checkbox '{cb_text}': default-state "
                    f"verification={'CONFIRMED' if verified else 'FAILED'} "
                    f"(default={c_default}, desired={desired})"
                )

            if not verified:
                all_verified = False

        return all_verified

    def _set_input_values(self) -> bool:
        """Type and verify active-module numeric values via WM_CHAR.

        CRITICAL: IupSetAttribute (used by preset1_config) changes the
        VISUAL text but does NOT fire VALUECHANGED_CB. The callback is
        what syncs the C variable (lagTime, dropChance, etc.) that the
        module actually reads during packet processing.

        By typing via WM_CHAR, each keystroke triggers VALUECHANGED_CB
        → uiSyncInteger/uiSyncChance → C variable gets updated.
        """
        p = self.params

        # Find all EDIT controls sorted by Y position
        edits = _get_edit_controls_sorted(self._hwnd)
        log_info(f"_set_input_values: found {len(edits)} EDIT controls")
        for i, hwnd in enumerate(edits):
            text = _get_window_text(hwnd)
            log_info(f"  EDIT[{i}] hwnd={hwnd} current='{text}'")

        # Inactive modules commonly retain saved GUI values.  Only controls
        # belonging to requested effects must be present and synchronized.
        values_set = 0
        values_requested = 0
        all_verified = True
        for idx, param_key in EDIT_INDEX_MAP.items():
            method = _EDIT_PARAM_METHOD[param_key]
            if method not in self.methods:
                continue

            values_requested += 1
            if idx >= len(edits):
                log_error(f"  EDIT[{idx}] ({param_key}): index out of range "
                          f"(only {len(edits)} EDITs found)")
                all_verified = False
                continue

            value = p.get(param_key, _EDIT_PARAM_DEFAULTS[param_key])
            try:
                value_str = str(_clumsy_numeric_value(param_key, value))
            except (TypeError, ValueError, OverflowError):
                log_error(
                    f"  EDIT[{idx}] ({param_key}): invalid numeric value "
                    f"{value!r}"
                )
                all_verified = False
                continue

            hwnd = edits[idx]
            old_text = _get_window_text(hwnd)

            # Type the value
            result = _type_into_edit(hwnd, value_str)
            log_info(f"  EDIT[{idx}] ({param_key}): '{old_text}' → "
                     f"'{result}' (wanted '{value_str}')")
            if result == value_str:
                values_set += 1
            else:
                log_error(f"  EDIT[{idx}] ({param_key}): MISMATCH — "
                          f"typed '{value_str}' but got '{result}'")
                all_verified = False

        log_info(
            "_set_input_values: "
            f"{values_set}/{values_requested} requested values verified"
        )
        return all_verified and values_set == values_requested

    def _try_keybind_fallback(self) -> bool:
        """Fallback: simulate '[' key multiple times via SendInput."""
        try:
            user32 = ctypes.windll.user32

            # Use SendInput for more reliable key simulation
            VK_OEM_4 = 0xDB
            KEYEVENTF_KEYUP = 0x0002

            # Try multiple times with increasing delays
            for attempt in range(3):
                log_info(f"ClumsyEngine: keybind fallback attempt {attempt + 1}/3")

                # Press '[' key
                user32.keybd_event(VK_OEM_4, 0x1A, 0, 0)  # 0x1A = scan code for '['
                time.sleep(0.050)  # Hold 50ms (thread polls every 10ms)
                # Release '[' key
                user32.keybd_event(VK_OEM_4, 0x1A, KEYEVENTF_KEYUP, 0)

                time.sleep(0.3)  # Wait for divertStart

                # Check if it worked by reading button text
                if self._hwnd:
                    all_buttons = _find_children_by_class(self._hwnd, "BUTTON")
                    for btn in all_buttons:
                        text = _get_window_text(btn)
                        if text.lower() == "stop":
                            log_info(f"ClumsyEngine: keybind fallback SUCCESS "
                                     f"on attempt {attempt + 1}")
                            return True

            log_error("ClumsyEngine: keybind fallback FAILED after 3 attempts")
            return False

        except Exception as e:
            log_error(f"ClumsyEngine: keybind fallback error: {e}")
            return False

    def stop(self) -> None:
        """Kill clumsy.exe and clean up."""
        if self._proc:
            try:
                if _safe_sp is None:
                    raise RuntimeError("safe_subprocess unavailable")
                taskkill_path = _safe_sp.resolve_system_binary("taskkill")
                _safe_sp.run(
                    [taskkill_path, "/F", "/T", "/PID", str(self._proc.pid)],
                    timeout=5.0,
                    expect_returncode=None,  # rc=128 if already gone
                    intent="clumsy.taskkill_child_pid",
                )
            except Exception as exc:
                log_error(f"ClumsyEngine: taskkill failed: {exc}")
                try:
                    self._proc.kill()
                except Exception as kill_exc:
                    log_error(f"ClumsyEngine: kill fallback failed: {kill_exc}")
            self._proc = None
        self._hwnd = None
        self._startup_verified = False
        self._runtime_verified = False
        log_info("ClumsyEngine stopped")

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def get_stats(self) -> Dict[str, Any]:
        """Return honest compatibility-engine metadata.

        The bundled Clumsy process does not expose packet or per-module
        counters.  Returning explicit zero counters keeps it visible in the
        manager while ``telemetry_available=False`` prevents the GUI from
        presenting configured modules as verified effects.
        """
        alive = self.alive
        return {
            "packets_processed": 0,
            "packets_dropped": 0,
            "packets_inbound": 0,
            "packets_outbound": 0,
            "packets_passed": 0,
            "alive": alive,
            "target_ip": self.params.get("_target_ip", "unknown"),
            "engine": "clumsy_compatibility",
            "telemetry_available": False,
            "startup_verified": bool(self._startup_verified and alive),
            "runtime_verified": bool(self._runtime_verified),
            "runtime_verification_available": False,
            "local_effect_verified": False,
            "verification_state": (
                "runtime_unobservable" if alive else "inactive"
            ),
            "methods": list(self.methods),
            "configured_methods": list(self.methods),
            "effective_methods": [],
            "shadowed_methods": [],
        }

    # ---- cleanup ----

    def _cleanup(self) -> None:
        self._startup_verified = False
        self._runtime_verified = False
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        self._hwnd = None

    # ---- config file writers ----

    def _write_config(self) -> None:
        """Write config.txt next to clumsy.exe with filter expression.

        loadConfig() in clumsy uses GetModuleFileName() to find config.txt
        relative to the EXE path (NOT CWD). Format is:
            filter_name: filter_expression
        where ':' is the delimiter. First entry becomes the default filter
        in the text field (line 1263: filterText VALUE = filters[0].filterValue).
        """
        path = os.path.join(self.clumsy_dir, "config.txt")
        content = f"DupeZ: {self.filter_str}\n"

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log_info(f"config.txt written: {path}")
        log_info(f"  filter entry: DupeZ: {self.filter_str}")

    def _write_presets(self) -> None:
        """Write presets.ini with numeric values ONLY — all modules DISABLED.

        CRITICAL IUP BEHAVIOR:
        preset1_config() uses IupSetAttribute to set UI state. This changes
        the VISUAL state of checkboxes but does NOT fire ACTION callbacks.
        The ACTION callback is what sets the C enabledFlag variable that
        actually controls whether a module processes packets.

        Strategy:
        - Set ALL inbound/outbound to FALSE → checkboxes start UNCHECKED
        - Set numeric values (delay, chance, etc.) → these DO work via
          IupSetAttribute because the C code reads them from IUP at runtime
        - After launch, _enable_modules() will CLICK each needed checkbox
          once → fires ACTION callback → properly sets enabledFlag = 1

        Format rules (from handler1 in main.c):
        - Section names: [General], [Preset1] through [Preset5]
        - Booleans: "true" or "false" (lowercase, exact strcmp match)
        - Numbers: string int
        - ALL sections must be present or ini_parse returns error → exit(1)
        """
        p = self.params
        methods = self.methods
        direction = p.get("direction", "both")

        # Pull GUI slider/checkbox values (these get set in the UI text fields
        # and ARE properly read by the C code via IupGetAttribute at runtime)
        lag_del  = int(p.get("lag_delay", 1500))    if "lag"        in methods else 0
        drop_ch  = int(p.get("drop_chance", 95))   if "drop"       in methods else 0
        thr_ch   = int(p.get("throttle_chance", 100)) if "throttle" in methods else 0
        thr_fr   = int(p.get("throttle_frame", 400))  if "throttle" in methods else 0
        thr_dr   = str(p.get("throttle_drop", False)).lower()
        dup_ch   = int(p.get("duplicate_chance", 80)) if "duplicate" in methods else 0
        dup_extra = (
            int(p.get("duplicate_count", 10))
            if "duplicate" in methods
            else 0
        )
        dup_ct   = dup_extra + 1 if "duplicate" in methods else 0
        ood_ch   = int(p.get("ood_chance", 80))        if "ood"       in methods else 0
        tam_ch   = int(p.get("tamper_chance", 60))     if ("corrupt" in methods or "tamper" in methods) else 0
        tam_cs   = str(p.get("tamper_checksum", False)).lower()
        bw_lim   = int(p.get("bandwidth_limit", 1))   if "bandwidth" in methods else 0
        bw_q     = int(p.get("bandwidth_queue", 0))
        bw_sz    = str(p.get("bandwidth_size", "kb"))
        rst_ch   = int(p.get("rst_chance", 90))        if "rst"       in methods else 0

        # Compute inbound/outbound flags based on direction and active methods
        want_in  = direction in ("both", "inbound")
        want_out = direction in ("both", "outbound")

        def flag(method_name):
            """Return 'true'/'false' for inbound and outbound for a module."""
            active = method_name in methods
            inb  = "true" if (active and want_in) else "false"
            outb = "true" if (active and want_out) else "false"
            return inb, outb

        _f = {k: flag(k) for k in ("lag","drop","disconnect","bandwidth","throttle","duplicate","ood","rst")}
        _f["tamper"] = flag("corrupt") if "corrupt" in methods else flag("tamper")

        log_info(f"presets.ini Preset1: methods={methods}, dir={direction}, "
                 f"lag={lag_del}, drop={drop_ch}%, rst={rst_ch}%, "
                 f"thr={thr_ch}%/{thr_fr}ms, "
                 f"dup={dup_extra} extra ({dup_ct} total)/{dup_ch}%, "
                 f"ood={ood_ch}%")

        content = (f"[General]\nKeybind = [\n\n[Preset1]\nPresetName = DupeZ\n"
                   f"Lag_Inbound = {_f['lag'][0]}\nLag_Outbound = {_f['lag'][1]}\nLag_Delay = {lag_del}\n"
                   f"Drop_Inbound = {_f['drop'][0]}\nDrop_Outbound = {_f['drop'][1]}\nDrop_Chance = {drop_ch}\n"
                   f"Disconnect_Inbound = {_f['disconnect'][0]}\nDisconnect_Outbound = {_f['disconnect'][1]}\n"
                   f"BandwidthLimiter_QueueSize = {bw_q}\nBandwidthLimiter_Size = {bw_sz}\n"
                   f"BandwidthLimiter_Inbound = {_f['bandwidth'][0]}\nBandwidthLimiter_Outbound = {_f['bandwidth'][1]}\n"
                   f"BandwidthLimiter_Limit = {bw_lim}\nThrottle_DropThrottled = {thr_dr}\n"
                   f"Throttle_Timeframe = {thr_fr}\nThrottle_Inbound = {_f['throttle'][0]}\n"
                   f"Throttle_Outbound = {_f['throttle'][1]}\nThrottle_Chance = {thr_ch}\n"
                   f"Duplicate_Count = {dup_ct}\nDuplicate_Inbound = {_f['duplicate'][0]}\n"
                   f"Duplicate_Outbound = {_f['duplicate'][1]}\nDuplicate_Chance = {dup_ch}\n"
                   f"OutOfOrder_Inbound = {_f['ood'][0]}\nOutOfOrder_Outbound = {_f['ood'][1]}\n"
                   f"OutOfOrder_Chance = {ood_ch}\nTamper_RedoChecksum = {tam_cs}\n"
                   f"Tamper_Inbound = {_f['tamper'][0]}\nTamper_Outbound = {_f['tamper'][1]}\n"
                   f"Tamper_Chance = {tam_ch}\nSetTCPRST_Inbound = {_f['rst'][0]}\n"
                   f"SetTCPRST_Outbound = {_f['rst'][1]}\nSetTCPRST_Chance = {rst_ch}\n")
        # Empty presets 2-5 (ALL must be present or ini_parse → exit 1)
        _EMPTY = ("Lag_Inbound = false\nLag_Outbound = false\nLag_Delay = 0\n"
                  "Drop_Inbound = false\nDrop_Outbound = false\nDrop_Chance = 0\n"
                  "Disconnect_Inbound = false\nDisconnect_Outbound = false\n"
                  "BandwidthLimiter_QueueSize = 0\nBandwidthLimiter_Size = kb\n"
                  "BandwidthLimiter_Inbound = false\nBandwidthLimiter_Outbound = false\n"
                  "BandwidthLimiter_Limit = 0\nThrottle_DropThrottled = false\n"
                  "Throttle_Timeframe = 0\nThrottle_Inbound = false\n"
                  "Throttle_Outbound = false\nThrottle_Chance = 0\n"
                  "Duplicate_Count = 0\nDuplicate_Inbound = false\n"
                  "Duplicate_Outbound = false\nDuplicate_Chance = 0\n"
                  "OutOfOrder_Inbound = false\nOutOfOrder_Outbound = false\n"
                  "OutOfOrder_Chance = 0\nTamper_RedoChecksum = false\n"
                  "Tamper_Inbound = false\nTamper_Outbound = false\nTamper_Chance = 0\n"
                  "SetTCPRST_Inbound = false\nSetTCPRST_Outbound = false\n"
                  "SetTCPRST_Chance = 0\n")
        for i in range(2, 6):
            content += f"\n[Preset{i}]\nPresetName = Preset_{i}\n{_EMPTY}"
        path = os.path.join(self.clumsy_dir, "presets.ini")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log_info(f"presets.ini written: {path} ({len(content)} chars)")
class ClumsyNetworkDisruptor:
    """Disruption manager that orchestrates NativeWinDivert and ClumsyEngine.

    Implements the DisruptionManagerBase interface with clean method names.
    Legacy ``_clumsy`` suffixed methods are preserved as aliases for backward
    compatibility but new code should use the clean names.

    Note: We don't formally inherit from DisruptionManagerBase at class
    definition time to avoid an import-time circular dependency (engine_base
    is lightweight but ClumsyNetworkDisruptor is imported very early). The
    class satisfies the interface structurally (duck typing).
    """

    def __init__(self) -> None:
        self.is_running = False
        self.disrupted_devices: Dict[str, dict] = {}
        self._device_lock = threading.Lock()
        # Registry incarnations are monotonic so asynchronous watchdog
        # callbacks can prove they still belong to the engine they observed.
        self._disruption_generation = 0
        self.clumsy_exe = None
        self.windivert_dll = None
        self.windivert_sys = None
        self._initialized = False
        self._init_paths()

    def _init_paths(self) -> None:
        try:
            if getattr(sys, 'frozen', False):
                base = os.path.join(sys._MEIPASS, "app", "firewall")
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            self.clumsy_exe = os.path.join(base, "clumsy.exe")
            self.windivert_dll = os.path.join(base, "WinDivert.dll")
            self.windivert_sys = os.path.join(base, "WinDivert64.sys")
            for lbl, p in [("clumsy.exe", self.clumsy_exe),
                           ("WinDivert.dll", self.windivert_dll),
                           ("WinDivert64.sys", self.windivert_sys)]:
                exists = os.path.exists(p)
                (log_info if exists else log_error)(
                    f"{'FOUND' if exists else 'MISSING'}: {lbl} @ {p}")
        except Exception as e:
            log_error(f"Path init failed: {e}")

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self._is_admin():
            log_error("NOT running as Administrator — WinDivert requires admin")
            return False
        if not (self.windivert_dll and os.path.exists(self.windivert_dll)):
            log_error("FATAL: WinDivert.dll not found")
            return False
        # clumsy.exe is optional when native engine is available
        if NATIVE_ENGINE_AVAILABLE:
            log_info(f"Disruptor initialized (native WinDivert engine, "
                     f"DLL @ {self.windivert_dll})")
        elif not (self.clumsy_exe and os.path.exists(self.clumsy_exe)):
            log_error("FATAL: clumsy.exe not found and native engine unavailable")
            return False
        else:
            log_info(f"Disruptor initialized (clumsy.exe @ {self.clumsy_exe})")
        self._initialized = True
        return True

    @staticmethod
    def _is_admin() -> bool:
        return is_admin()

    def _get_clumsy_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.clumsy_exe))

    def _start_selected_engine(
        self,
        *,
        filter_str: str,
        methods: List[str],
        params: Dict[str, Any],
    ) -> tuple[Optional[Any], str, str]:
        """Start the requested engine and return ``(engine, actual, requested)``.

        Auto prefers the bundled Clumsy engine whenever the request can be
        represented exactly. That makes normal Lag/Disconnect/Duplicate
        behavior match standalone Clumsy without an operator-facing engine
        switch. Native remains the primary implementation for extensions
        Clumsy cannot represent. Explicit choices never switch engines.
        """
        preference = _normalize_engine_preference(
            params.get("_engine_preference", ENGINE_AUTO))
        compatibility = assess_clumsy_compatibility(methods, params)

        def _try_native() -> Optional[Any]:
            if NATIVE_ENGINE_AVAILABLE:
                log_info(
                    "Trying native WinDivert engine "
                    f"(preference={preference})..."
                )
                native_engine = None
                try:
                    native_engine = NativeWinDivertEngine(
                        dll_path=self.windivert_dll,
                        filter_str=filter_str,
                        methods=methods,
                        params=params,
                    )
                    if native_engine.start():
                        log_info("Native WinDivert engine started successfully")
                        return native_engine
                    log_error("Native engine start returned False")
                except Exception as exc:
                    log_error(f"Native engine start failed: {exc}")
                if native_engine is not None:
                    try:
                        native_engine.stop()
                    except Exception:
                        pass
            else:
                log_error("Native engine requested but unavailable")
            return None

        def _try_clumsy() -> Optional[Any]:
            if not compatibility.representable:
                log_error(
                    "Clumsy compatibility refused this request because it "
                    "would change packet semantics: "
                    f"{compatibility.reason}"
                )
                return None
            if not self.clumsy_exe or not os.path.isfile(self.clumsy_exe):
                log_error(
                    "Clumsy compatibility requested but clumsy.exe is missing: "
                    f"{self.clumsy_exe}"
                )
                return None
            log_info(
                "Using Clumsy compatibility engine "
                f"(preference={preference}, standalone module order)..."
            )
            clumsy_engine = ClumsyEngine(
                clumsy_exe=self.clumsy_exe,
                clumsy_dir=self._get_clumsy_dir(),
                filter_str=filter_str,
                methods=list(compatibility.methods),
                params=params,
            )
            if clumsy_engine.start():
                return clumsy_engine
            log_error("Clumsy compatibility engine start FAILED")
            try:
                clumsy_engine.stop()
            except Exception:
                pass
            return None

        if preference == ENGINE_CLUMSY:
            engine = _try_clumsy()
            return engine, ENGINE_CLUMSY if engine else "", preference

        if preference == ENGINE_NATIVE:
            engine = _try_native()
            if engine is None:
                log_error(
                    "Explicit Native WinDivert selection failed; "
                    "Clumsy fallback is disabled for explicit choices"
                )
            return engine, ENGINE_NATIVE if engine else "", preference

        # Automatic policy: exact standalone behavior first.
        if compatibility.representable:
            engine = _try_clumsy()
            if engine is not None:
                return engine, ENGINE_CLUMSY, preference

            requested_methods = set(compatibility.methods)
            if not requested_methods.issubset(
                _NATIVE_CLUMSY_FALLBACK_METHODS
            ):
                log_error(
                    "Automatic Clumsy startup failed and native fallback was "
                    "refused because it would change semantics for: "
                    + ", ".join(sorted(
                        requested_methods
                        - _NATIVE_CLUMSY_FALLBACK_METHODS
                    ))
                )
                return None, "", preference
            log_warning(
                "Automatic Clumsy startup failed; trying the bounded native "
                "equivalent"
            )
        else:
            log_info(
                "Request uses native-only behavior; selecting native engine "
                f"({compatibility.reason})"
            )

        engine = _try_native()
        if engine is not None:
            return engine, ENGINE_NATIVE, preference

        return None, "", preference

    # Core disruption
    def disconnect_device_clumsy(self, target_ip: str,
                                  methods: Optional[List[str]] = None,
                                  params: Optional[Dict] = None,
                                  preset: Optional[str] = None,
                                  target_mac: Optional[str] = None,
                                  target_hostname: Optional[str] = None,
                                  target_device_type: Optional[str] = None
                                  ) -> bool:
        """Start disruption against a target IP.

        Args:
            target_ip: Game server IP (PC-local) or device IP (FORWARD).
            methods: Disruption methods to activate. If ``None``, the
                default list is derived from ``preset`` (if given) or
                falls back to the PC-local/FORWARD default method set.
            params: Disruption parameter dict. If ``None``, built from
                ``get_disruption_defaults("dayz")`` and — if ``preset``
                is set — merged with that preset's values.
            preset: Named preset from ``disruption_presets`` in the game
                profile (``pc_local``, ``ps5_hotspot``, ``xbox_hotspot``).
                If ``None`` and ``params`` is also ``None``, the profile
                is auto-detected from ``target_ip`` + ``target_mac`` +
                ``target_hostname`` + ``target_device_type`` via
                ``target_profile.resolve_target_profile``. Explicit
                values override everything.
            target_mac: Optional MAC for auto-detection platform lookup.
            target_hostname: Optional hostname fallback for detection.
            target_device_type: Optional pre-tagged device type from
                the network scanner (e.g. ``"PlayStation"``).
        """
        # ── Auto-detect profile if caller didn't pick one explicitly ───
        # Runs whenever ``preset`` was not supplied. The detection result
        # drives the layer (NETWORK vs NETWORK_FORWARD) decision and any
        # preset-level tuning the user did not override via ``params``.
        _detection = None
        if preset is None:
            try:
                from app.firewall.target_profile import resolve_target_profile
                _detection = resolve_target_profile(
                    target_ip=target_ip,
                    mac=target_mac,
                    hostname=target_hostname,
                    device_type=target_device_type,
                )
                preset = _detection.profile
                log_info(
                    f"[auto-detect] profile={_detection.profile} "
                    f"layer={_detection.layer} platform={_detection.platform}"
                )
                for reason in _detection.reasons:
                    log_info(f"[auto-detect]   {reason}")
            except Exception as det_err:
                log_error(
                    f"[auto-detect] failed: {det_err} — "
                    f"falling back to profile defaults"
                )

        # If caller already supplied params (GUI slider path), merge the
        # detected preset's tunings in as *base* values — caller keys
        # always win, so user slider overrides remain authoritative.
        if params is not None and preset is not None:
            try:
                from app.config.game_profiles import get_disruption_preset
                _preset_base = get_disruption_preset("dayz", preset)
                if isinstance(_preset_base, dict):
                    # Only fill keys the caller did NOT specify
                    merged = dict(_preset_base)
                    merged.update(params)
                    params = merged
                    # Stash detection metadata so the engine can attach it
                    # to the engine_start event for the learning loop.
                    if _detection is not None:
                        params.setdefault("_target_profile", _detection.profile)
                        params.setdefault(
                            "_network_class",
                            getattr(_detection, "connection_mode", "unknown"),
                        )
                        params.setdefault("_platform", _detection.platform)
                    # Ensure layer flag reflects detection regardless of
                    # stale GUI checkbox state — the auto-detect whole
                    # point is to remove manual layer decisions.
                    if _detection is not None:
                        params["_network_local"] = (_detection.layer == "local")
                    log_info(
                        f"[auto-detect] merged preset '{preset}' "
                        f"into caller params (layer={'local' if params.get('_network_local') else 'forward'})"
                    )
            except Exception as merge_err:
                log_error(f"[auto-detect] preset merge failed: {merge_err}")

        # ── Resolve params from preset/defaults ─────────────────────────
        if params is None:
            try:
                from app.config.game_profiles import (
                    get_disruption_defaults, get_disruption_preset,
                )
                _profile = get_disruption_defaults("dayz")
                params = {
                    "lag_delay": _profile.get("lag_delay_ms", 1500),
                    "drop_chance": _profile.get("drop_chance_pct", 95),
                    "disconnect_chance": _profile.get("disconnect_chance_pct", 100),
                    "bandwidth_limit": _profile.get("bandwidth_limit_kbps", 1),
                    "bandwidth_queue": _profile.get("bandwidth_queue", 0),
                    "throttle_chance": _profile.get("throttle_chance_pct", 100),
                    "throttle_frame": _profile.get("throttle_frame_ms", 400),
                    "throttle_drop": _profile.get("throttle_drop", True),
                    "direction": _profile.get("direction", "both"),
                }
                if preset:
                    try:
                        preset_params = get_disruption_preset("dayz", preset)
                        params.update(preset_params)
                        log_info(f"Applied disruption preset '{preset}' "
                                 f"({len(preset_params)} keys)")
                    except Exception as pe:
                        log_error(f"Preset '{preset}' load failed: {pe} — "
                                  f"using profile defaults")
            except Exception:
                params = {
                    "lag_delay": 2000, "drop_chance": 95,
                    "disconnect_chance": 100,
                    "bandwidth_limit": 1, "bandwidth_queue": 0,
                    "throttle_chance": 100, "throttle_frame": 350,
                    "throttle_drop": True, "direction": "both",
                }

        # ── Resolve methods list ───────────────────────────────────────
        # Preset-supplied methods win if the caller didn't pass any.
        if methods is None:
            preset_methods = params.get("methods")
            if isinstance(preset_methods, list) and preset_methods:
                methods = list(preset_methods)
            else:
                methods = ["drop", "lag", "bandwidth", "throttle"]

        from app.core.validation import validate_methods

        safe_methods = validate_methods(list(methods or []))
        if not safe_methods:
            log_error(
                "No public diagnostic methods remained after validation; "
                "falling back to bounded temporary disconnect"
            )
            safe_methods = ["disconnect"]
        methods = safe_methods

        # processId is unavailable at WinDivert NETWORK/NETWORK_FORWARD.
        # Reject this obsolete preset flag before touching engines or ARP.
        if params.get("_process_scope"):
            log_error(
                "Process-scoped disruption is unavailable: WinDivert does "
                "not expose processId at packet interception layers. Remove "
                "_process_scope from the preset; no disruption was started."
            )
            return False

        try:
            if target_ip in self.disrupted_devices:
                log_info(f"{mask_ip(target_ip)} already disrupted — restarting")
                self.reconnect_device_clumsy(target_ip)

            if not self._initialized:
                if not self.initialize():
                    log_error("Cannot disrupt: initialization failed")
                    return False

            # Guard: "true" filter + WinDivert only allows one handle per
            # layer/priority — warn and stop existing engine before starting new one.
            with self._device_lock:
                existing = list(self.disrupted_devices.keys())
            if existing:
                log_info(f"Active disruption on {[mask_ip(ip) for ip in existing]} — stopping before new target "
                         f"(single-handle WinDivert limitation)")
                for ip in existing:
                    self.reconnect_device_clumsy(ip)

            # ── Platform detection & layer selection ────────────────
            # PC-local mode: DayZ running on the SAME machine as DupeZ.
            #   - Uses NETWORK layer (not NETWORK_FORWARD)
            #   - addr.Outbound works correctly on NETWORK layer
            #   - Filter by game server IP (target_ip IS the server)
            # Console/remote-PC mode (PS5, Xbox, PC-over-hotspot):
            #   - Uses NETWORK_FORWARD layer (ICS/hotspot forwarding)
            #   - addr.Outbound is always TRUE — use IP header parsing
            #   - Filter by device IP (target_ip IS the console/PC)
            # WiFi same-network mode (v5.7.2):
            #   - Target is on same WiFi LAN. Default routes through ARP
            #     local forwarding + NETWORK_FORWARD layer so the TARGET DEVICE is
            #     disrupted (this is the primary "pick a device, hit
            #     DISRUPT" workflow). The isolation watchdog auto-falls-
            #     back to self-disrupt if the AP drops the local forwarding.
            #   - Operators who specifically want to lag only their OWN
            #     traffic can pass params["_force_self_disrupt"] = True.
            is_local = params.get("_network_local", False)

            # v5.7.2: honor an explicit self-disrupt opt-in. When set,
            # it overrides detection: NETWORK layer, no local forwarding. This
            # is the documented escape hatch for "lag only my own
            # connection to the target" (e.g. a shared game server).
            _force_self_disrupt = bool(params.get("_force_self_disrupt"))
            if _force_self_disrupt:
                is_local = True
                params["_network_local"] = True
                log_info(
                    "[WiFi] _force_self_disrupt set — NETWORK layer, "
                    "local forwarding skipped (operator opt-in)"
                )

            # Map _detection.layer → engine layer so the auto-detected
            # FORWARD vs local layer actually takes effect. is_local is
            # otherwise only sourced from params, which the controller
            # doesn't populate from detection. Caller can still override
            # by passing _network_local explicitly; _force_self_disrupt
            # (handled above) also wins over detection.
            if (
                _detection is not None
                and "_network_local" not in params
                and not _force_self_disrupt
            ):
                detected_layer = getattr(_detection, "layer", None)
                if detected_layer == "local":
                    is_local = True
                    params["_network_local"] = True
                elif detected_layer == "forward":
                    is_local = False
                    params["_network_local"] = False

            # ── local forwarding for WiFi same-network ────────────────
            # If auto-detection says we need local forwarding, start it
            # BEFORE opening WinDivert so traffic is already flowing
            # through us when the FORWARD layer opens. Suppressed when
            # the operator forced self-disrupt mode.
            _arp_spoofer = None
            needs_arp = (
                _detection is not None
                and getattr(_detection, "needs_arp_spoof", False)
                and not _force_self_disrupt
            )
            if needs_arp:
                # ARP-local forwarding capture is asymmetric: only one leg of the
                # target↔gateway flow lands through us (gateway caches on
                # consumer routers are harder to forwarding setup than endpoint caches,
                # so OUTBOUND target→gateway typically wins). Presets like
                # ps5_hotspot default all module directions to "inbound" —
                # correct for NETWORK_FORWARD on the ICS host, wrong here.
                # Force "both" so public diagnostic modules consume whatever
                # we actually capture (OUT, IN, or both).
                _arp_dir_keys = (
                    "direction",
                )
                for _k in _arp_dir_keys:
                    if params.get(_k) != "both":
                        log_info(
                            f"[WiFi] ARP-local forwarding path: forcing {_k}="
                            f"'both' (was {params.get(_k)!r})"
                        )
                        params[_k] = "both"
                try:
                    from app.network.arp_spoof import ArpSpoofer
                    from app.network.npcap_check import check_npcap
                    from app.logs.gui_notify import gui_toast

                    _npcap = check_npcap()
                    if not _npcap.available:
                        # v5.6.4: Bail honestly instead of silently opening a
                        # NETWORK_FORWARD WinDivert handle that will never see
                        # a packet. Without ARP forwarding setup, no traffic is routed
                        # through us; the engine would report "active" while
                        # doing nothing. Surface the failure to the GUI so the
                        # "Partial Failure" dialog tells the operator to
                        # install Npcap or switch to wired.
                        log_error(
                            f"[WiFi] Cannot ARP-local forwarding: {_npcap.reason}. "
                            f"Install Npcap: {_npcap.install_url}. "
                            f"Aborting disruption — would be a silent no-op."
                        )
                        gui_toast(
                            "error",
                            f"WiFi target needs local forwarding, but "
                            f"{_npcap.reason}. Install Npcap or use wired.",
                        )
                        return False
                    log_info(
                        f"[WiFi] Target {mask_ip(target_ip)} is on same "
                        f"WiFi network — activating local forwarding to "
                        f"redirect traffic through this machine"
                    )
                    gui_toast(
                        "info",
                        f"WiFi same-net target — starting local forwarding "
                        f"({mask_ip(target_ip)})",
                    )
                    _arp_spoofer = ArpSpoofer(target_ip=target_ip)
                    if _arp_spoofer.start():
                        log_info("[WiFi] local forwarding active -- traffic "
                                 "redirected, using NETWORK_FORWARD layer")
                        # v5.7.5 (M1 fix): best-effort ARP restore on
                        # process termination. Covers kill -9 / SIGTERM /
                        # operator-closes-window-uncleanly paths. Without
                        # this, the target stays on the stale forwarding path and its traffic
                        # black-holes for 30-60s after we die (or longer
                        # on endpoints that pin ARP under load). atexit
                        # runs on the SAME interpreter death; it does NOT
                        # run on SIGSEGV or kill -9, but it does run on
                        # sys.exit(), uncaught exceptions, and Ctrl+C
                        # (after the signal handler converts to KeyboardInterrupt).
                        try:
                            import atexit as _atexit
                            _atexit.register(_arp_spoofer.stop)
                        except Exception:
                            pass
                        # Force FORWARD layer -- traffic now routes through us
                        is_local = False
                        params["_network_local"] = False
                    else:
                        # v5.6.4: Previously this branch logged "falling back
                        # to NETWORK layer" but did NOT actually change
                        # is_local / _network_local — so it stayed on
                        # NETWORK_FORWARD with no spoofer, which sees zero
                        # traffic and is a silent no-op. ArpSpoofer.start()
                        # returning False means Npcap opened but injection or
                        # gateway resolution failed; the local NETWORK layer
                        # cannot help target a remote device either. Abort.
                        log_error(
                            "[WiFi] local forwarding failed to start. "
                            "Aborting disruption — NETWORK_FORWARD without "
                            "a working spoofer would be a silent no-op, and "
                            "NETWORK layer cannot affect remote targets."
                        )
                        gui_toast(
                            "error",
                            "local forwarding failed to start. Check Npcap install "
                            "or AP client isolation; consider wired.",
                        )
                        _arp_spoofer = None
                        return False
                except ImportError:
                    log_error("[WiFi] arp_spoof module not available — "
                              "aborting (would be silent no-op).")
                    try:
                        from app.logs.gui_notify import gui_toast as _t
                        _t("error", "ARP-local forwarding module unavailable — aborting.")
                    except Exception:
                        pass
                    return False
                except Exception as arp_err:
                    log_error(f"[WiFi] local forwarding error: {arp_err} — "
                              f"aborting (would be silent no-op).")
                    try:
                        from app.logs.gui_notify import gui_toast as _t
                        _t("error", f"local forwarding error: {arp_err}")
                    except Exception:
                        pass
                    _arp_spoofer = None
                    return False

            if target_ip and target_ip != "unknown":
                filt_expr = (
                    f"ip.SrcAddr == {target_ip} or "
                    f"ip.DstAddr == {target_ip}"
                )
            else:
                filt_expr = "true"

            # v5.6.9 #3: per-port targeting. When the preset declares
            # ``_ports`` as a list of int (or {proto,port} dicts), AND a
            # port clause onto the existing filter so disruption only
            # touches game traffic and leaves Discord/voice/browser
            # untouched. Empty / missing _ports preserves prior
            # behavior (target ALL of the target's traffic).
            _ports = params.get("_ports") or []
            if _ports:
                port_atoms: List[str] = []
                for entry in _ports:
                    if isinstance(entry, int) and 1 <= entry <= 65535:
                        port_atoms.append(
                            f"(tcp.DstPort == {entry} or "
                            f"tcp.SrcPort == {entry} or "
                            f"udp.DstPort == {entry} or "
                            f"udp.SrcPort == {entry})"
                        )
                    elif isinstance(entry, dict):
                        proto = str(entry.get("proto", "")).lower()
                        port = entry.get("port")
                        if proto in ("tcp", "udp") and isinstance(port, int) \
                                and 1 <= port <= 65535:
                            port_atoms.append(
                                f"({proto}.DstPort == {port} or "
                                f"{proto}.SrcPort == {port})"
                            )
                if port_atoms:
                    ports_clause = " or ".join(port_atoms)
                    filt_expr = f"({filt_expr}) and ({ports_clause})"
                    log_info(
                        f"[PRESET] per-port scope applied: "
                        f"{len(port_atoms)} port atom(s)"
                    )

            mode_label = "PC-LOCAL (NETWORK)" if is_local else "REMOTE (NETWORK_FORWARD)"
            if _arp_spoofer:
                mode_label += " + LOCAL FORWARDING"
            log_info(f"{'='*50}\nDISRUPTION START: {mask_ip(target_ip)}\n"
                     f"  mode={mode_label}  methods={methods}"
                     f"  direction={params.get('direction', 'both')}"
                     f"  filter={filt_expr}\n{'='*50}")

            # Pass the fully resolved target and capture layer to whichever
            # engine the operator selected.
            eng_params = dict(params)
            eng_params["_target_ip"] = target_ip
            eng_params["_network_local"] = is_local

            engine, actual_engine, requested_engine = self._start_selected_engine(
                filter_str=filt_expr,
                methods=methods,
                params=eng_params,
            )

            if engine is None:
                if _arp_spoofer is not None:
                    try:
                        _arp_spoofer.stop()
                    except Exception as cleanup_exc:
                        log_error(
                            "Engine startup failed and local-forwarding "
                            f"cleanup also failed: {cleanup_exc}"
                        )
                return False

            # Native telemetry can correlate a live local-forwarding path.
            # The compatibility process has no corresponding counter hook.
            if actual_engine == ENGINE_NATIVE:
                try:
                    engine._arp_spoofer = _arp_spoofer
                except Exception:
                    pass

            with self._device_lock:
                self._disruption_generation += 1
                self.disrupted_devices[target_ip] = {
                    "engine": engine,
                    "generation": self._disruption_generation,
                    "engine_name": actual_engine,
                    "engine_preference": requested_engine,
                    "methods": methods,
                    "params": params,
                    "start_time": time.time(),
                    "arp_spoofer": _arp_spoofer,
                    # Auto-detect result — kept for GUI surfacing
                    # (layer, platform, profile, needs_arp_spoof, reasons)
                    "detection": ({
                        "profile": _detection.profile,
                        "layer": _detection.layer,
                        "platform": _detection.platform,
                        "connection_mode": getattr(
                            _detection, "connection_mode", "unknown"),
                        "needs_arp_spoof": getattr(
                            _detection, "needs_arp_spoof", False),
                        "reasons": list(_detection.reasons),
                    } if _detection is not None else None),
                }

            # v5.6.5: Arm the WiFi isolation watchdog when the wifi_same_net
            # path is active and the auto-fallback flag is set (default on).
            # Watchdog observes (spoofer.packets_sent, engine.packets_processed)
            # after a grace period and auto-falls-back to self-disrupt mode
            # (NETWORK layer, operator's own traffic only) when isolation is
            # detected. Skips clumsy.exe fallback engines — they lack the
            # packet-counter telemetry the watchdog reads.
            if (
                _arp_spoofer is not None
                and NATIVE_ENGINE_AVAILABLE
                and isinstance(engine, NativeWinDivertEngine)
                and params.get("_wifi_auto_fallback", True)
            ):
                self._arm_wifi_isolation_watchdog(
                    target_ip, engine, _arp_spoofer, methods, params,
                )

            _pid = getattr(getattr(engine, '_proc', None), 'pid', 'N/A')
            log_info(f"DISRUPTION ACTIVE: {mask_ip(target_ip)} (PID={_pid})")
            return True

        except Exception as e:
            log_error(f"DISRUPTION FAILED for {mask_ip(target_ip)}: {e}")
            log_error(traceback.format_exc())
            return False

    def reconnect_device_clumsy(self, target_ip: str) -> bool:
        try:
            with self._device_lock:
                if target_ip not in self.disrupted_devices:
                    return True
                info = self.disrupted_devices.pop(target_ip)

            # v5.6.5: Cancel pending isolation watchdog BEFORE stopping the
            # engine. Otherwise the watchdog might fire its callback into a
            # half-torn-down state and try to restart an engine for a target
            # the operator already released.
            wd = info.get("wifi_watchdog")
            if wd is not None:
                try:
                    wd.cancel()
                except Exception:
                    pass

            engine = info.get("engine")
            if engine:
                engine.stop()

            # Stop local forwarding if active — restore real ARP entries
            # and disable IP forwarding (if we enabled it).
            arp_spoofer = info.get("arp_spoofer")
            if arp_spoofer is not None:
                try:
                    arp_spoofer.stop()
                    log_info(f"[WiFi] local forwarding stopped for "
                             f"{mask_ip(target_ip)}")
                except Exception as arp_err:
                    log_error(f"[WiFi] local forwarding cleanup error: {arp_err}")

            log_info(f"Disruption stopped: {mask_ip(target_ip)}")
            return True
        except Exception as e:
            log_error(f"Error stopping {mask_ip(target_ip)}: {e}")
            with self._device_lock:
                self.disrupted_devices.pop(target_ip, None)
            return False

    # ── v5.6.5: WiFi isolation watchdog + self-disrupt fallback ─────
    #
    # See app/network/wifi_probe.py for the watchdog implementation and a
    # full design rationale. The flow is:
    #
    #   1. _arm_wifi_isolation_watchdog spawns a daemon thread that, after
    #      a short grace window, samples (spoofer.packets_sent,
    #      engine.packets_processed). If sent > 0 and processed == 0, the
    #      AP is silently dropping our local forwarding — classic client-isolation
    #      signature on Eero / Google Nest / ISP gateways / public WiFi.
    #
    #   2. The watchdog invokes its on_result callback with the verdict.
    #      For ISOLATION_DETECTED, the callback calls
    #      _fallback_to_self_disrupt, which tears down the FORWARD-layer
    #      engine + ArpSpoofer and restarts a NETWORK-layer engine on
    #      the same filter. NETWORK layer captures the operator's OWN
    #      traffic to/from the target — useful for "lag my own game" or
    #      "drop my own connection to this peer" use cases. It cannot
    #      affect the target's traffic to third parties.
    #
    #   3. Operator-initiated stop (reconnect_device_clumsy) cancels the
    #      watchdog so stale callbacks don't try to restart a released
    #      engine.
    #
    # Opt-out: pass params["_wifi_auto_fallback"] = False to the original
    # disrupt_device call. Defaults to True. The fallback engine itself
    # is started with _wifi_auto_fallback=False to prevent re-fallback
    # loops (NETWORK layer has no ArpSpoofer anyway, so the predicate
    # in _arm_wifi_isolation_watchdog wouldn't match — but belt-and-
    # suspenders).

    def _arm_wifi_isolation_watchdog(
        self,
        target_ip: str,
        engine,
        spoofer,
        methods: List[str],
        params: Dict,
    ) -> None:
        """Spawn the WiFi isolation watchdog for an active disruption.

        Args:
            target_ip: target the watchdog is observing.
            engine: live NativeWinDivertEngine instance.
            spoofer: live ArpSpoofer instance.
            methods: original method list, forwarded to the fallback restart.
            params: original params dict, forwarded to the fallback restart.
        """
        with self._device_lock:
            active = self.disrupted_devices.get(target_ip)
            if active is None or active.get("engine") is not engine:
                log_info(
                    f"[WiFi] skipped stale watchdog for {mask_ip(target_ip)}"
                )
                return
            expected_generation = active.get("generation")

        try:
            from app.network.wifi_probe import (
                IsolationResult,
                IsolationWatchdog,
            )
        except Exception as exc:
            log_warning(
                f"[WiFi] wifi_probe import failed: {exc} — "
                f"auto-fallback to self-disrupt disabled this session"
            )
            return

        def _on_result(result: str) -> None:
            if result != IsolationResult.ISOLATION_DETECTED:
                # WORKING / INCONCLUSIVE / ABORTED — no action. The
                # engine's own _flow_health_check already logs the
                # INCONCLUSIVE case loudly enough.
                return
            try:
                self._fallback_to_self_disrupt(
                    target_ip,
                    methods,
                    params,
                    expected_generation=expected_generation,
                    expected_engine=engine,
                )
            except Exception as exc:
                log_error(
                    f"[WiFi-FALLBACK] {mask_ip(target_ip)} self-disrupt "
                    f"raised: {exc}\n{traceback.format_exc()}"
                )

        try:
            grace_s = float(params.get("_wifi_isolation_grace_s", 8.0))
        except (TypeError, ValueError):
            grace_s = 8.0

        watchdog = IsolationWatchdog(
            spoofer=spoofer,
            engine=engine,
            on_result=_on_result,
            grace_s=grace_s,
            target_ip=target_ip,
        )
        armed = False
        with self._device_lock:
            active = self.disrupted_devices.get(target_ip)
            if (
                active is not None
                and active.get("generation") == expected_generation
                and active.get("engine") is engine
            ):
                active["wifi_watchdog"] = watchdog
                armed = True
        if not armed:
            try:
                watchdog.cancel()
            except Exception:
                pass
            log_info(
                f"[WiFi] discarded stale watchdog for {mask_ip(target_ip)}"
            )
            return
        watchdog.start()
        log_info(
            f"[WiFi] isolation watchdog armed for {mask_ip(target_ip)} "
            f"(grace={grace_s:.1f}s)"
        )

    def _fallback_to_self_disrupt(
        self,
        target_ip: str,
        methods: List[str],
        params: Dict,
        *,
        expected_generation: int,
        expected_engine: Any,
    ) -> None:
        """Swap the active FORWARD+ARP engine for a NETWORK-layer self-disrupt engine.

        Invoked exclusively by the isolation watchdog callback on
        ISOLATION_DETECTED. The user-visible effect: a one-shot toast
        explaining the mode change, followed by continued disruption
        that only affects the operator's own traffic to/from
        ``target_ip`` (because NETWORK layer cannot reach the target's
        other flows). This is intentionally a degraded mode — the only
        thing client-side that can possibly still work behind AP
        client isolation.
        """
        with self._device_lock:
            info = self.disrupted_devices.get(target_ip)
            is_current = (
                info is not None
                and info.get("generation") == expected_generation
                and info.get("engine") is expected_engine
                and not info.get("wifi_fallback_transition")
            )
            if is_current:
                # A reconnect or newer start may replace this entry while the
                # fallback engine starts. This marker rejects duplicate
                # callbacks before either one tears down the active engine.
                info["wifi_fallback_transition"] = True
        if not is_current:
            log_info(
                f"[WiFi-FALLBACK] {mask_ip(target_ip)} callback is stale — "
                f"aborting self-disrupt restart"
            )
            return

        # 1. Surface the mode change to the operator BEFORE tearing down
        # the current engine, so the toast lands while the badge is
        # still red. Otherwise a brief "disrupted → off → disrupted"
        # flicker confuses people.
        try:
            from app.logs.gui_notify import gui_toast
            gui_toast(
                "warning",
                f"WiFi: AP isolation detected for {mask_ip(target_ip)}. "
                f"Switching to SELF-DISRUPT mode — only your machine's "
                f"traffic to/from the target will be affected. The "
                f"target's other connections are not reachable through "
                f"this AP without managed-switch access.",
            )
        except Exception:
            pass

        old_engine = info.get("engine")
        old_arp_spoofer = info.get("arp_spoofer")

        # 2. Stop the current engine + spoofer. Use exception guards on
        # both — we want to attempt the restart even if cleanup hiccups.
        if old_engine is not None:
            try:
                old_engine.stop()
            except Exception as exc:
                log_warning(
                    f"[WiFi-FALLBACK] old engine stop raised: {exc}"
                )
        if old_arp_spoofer is not None:
            try:
                old_arp_spoofer.stop()
            except Exception as exc:
                log_warning(
                    f"[WiFi-FALLBACK] ArpSpoofer stop raised: {exc}"
                )

        # 3. Build new engine on NETWORK layer.
        new_params = dict(params)
        new_params["_network_local"] = True       # NETWORK layer
        new_params["_wifi_self_disrupt"] = True   # telemetry / GUI tag
        new_params["_wifi_auto_fallback"] = False  # no re-fallback loop
        new_params["_target_ip"] = target_ip

        if target_ip and target_ip != "unknown":
            filt_expr = (
                f"ip.SrcAddr == {target_ip} or "
                f"ip.DstAddr == {target_ip}"
            )
        else:
            filt_expr = "true"

        new_engine = None
        if NATIVE_ENGINE_AVAILABLE:
            try:
                new_engine = NativeWinDivertEngine(
                    dll_path=self.windivert_dll,
                    filter_str=filt_expr,
                    methods=methods,
                    params=new_params,
                )
                if not new_engine.start():
                    new_engine = None
            except Exception as exc:
                log_error(
                    f"[WiFi-FALLBACK] native engine restart failed: {exc}"
                )
                new_engine = None

        if new_engine is None:
            log_error(
                f"[WiFi-FALLBACK] {mask_ip(target_ip)} could not restart "
                f"in self-disrupt mode — disruption is now inactive."
            )
            try:
                from app.logs.gui_notify import gui_toast
                gui_toast(
                    "error",
                    f"Self-disrupt restart FAILED for "
                    f"{mask_ip(target_ip)}. Check logs.",
                )
            except Exception:
                pass
            with self._device_lock:
                current = self.disrupted_devices.get(target_ip)
                if (
                    current is info
                    and current.get("generation") == expected_generation
                    and current.get("engine") is expected_engine
                    and current.get("wifi_fallback_transition")
                ):
                    self.disrupted_devices.pop(target_ip, None)
            return

        # 4. Swap in the new engine. Preserve detection info so the GUI
        # still has context; drop arp_spoofer + watchdog refs since
        # neither applies to self-disrupt mode.
        committed = False
        with self._device_lock:
            current = self.disrupted_devices.get(target_ip)
            if (
                current is info
                and current.get("generation") == expected_generation
                and current.get("engine") is expected_engine
                and current.get("wifi_fallback_transition")
            ):
                self._disruption_generation += 1
                current.update({
                    "engine": new_engine,
                    "generation": self._disruption_generation,
                    "engine_name": ENGINE_NATIVE,
                    "params": new_params,
                    "arp_spoofer": None,
                    "wifi_watchdog": None,
                    "wifi_self_disrupt": True,
                    "wifi_fallback_transition": False,
                })
                committed = True

        if not committed:
            # A release/restart won the race while the replacement was
            # starting. Do not overwrite its entry or leak this engine.
            try:
                new_engine.stop()
            except Exception as exc:
                log_warning(
                    f"[WiFi-FALLBACK] stale replacement stop raised: {exc}"
                )
            log_info(
                f"[WiFi-FALLBACK] {mask_ip(target_ip)} changed during "
                f"restart — discarded stale replacement"
            )
            return

        log_info(
            f"[WiFi-FALLBACK] {mask_ip(target_ip)} now in SELF-DISRUPT "
            f"mode (NETWORK layer, spoofer stopped). Operator's own "
            f"egress / ingress to target IS disrupted; target's other "
            f"flows are unaffected (no L2 redirect through us)."
        )

    def clear_all_disruptions_clumsy(self) -> bool:
        with self._device_lock:
            ips = list(self.disrupted_devices.keys())
        all_stopped = True
        for ip in ips:
            try:
                if not self.reconnect_device_clumsy(ip):
                    all_stopped = False
            except Exception as exc:
                all_stopped = False
                log_error(
                    f"Unexpected error clearing disruption for "
                    f"{mask_ip(ip)}: {exc}"
                )

        with self._device_lock:
            remaining = list(self.disrupted_devices)
        if remaining:
            all_stopped = False
            log_error(
                f"Disruption cleanup incomplete: "
                f"{len(remaining)} active registry entr"
                f"{'y remains' if len(remaining) == 1 else 'ies remain'}"
            )

        return all_stopped

    def get_disrupted_devices_clumsy(self) -> List[str]:
        with self._device_lock:
            dead = [ip for ip, info in self.disrupted_devices.items()
                    if info.get("engine") and not info["engine"].alive]
            dead_infos = {ip: self.disrupted_devices.pop(ip) for ip in dead}
        for ip, info in dead_infos.items():
            watchdog = info.get("wifi_watchdog")
            if watchdog is not None:
                try:
                    watchdog.cancel()
                except Exception as exc:
                    log_warning(
                        f"Dead disruption watchdog cleanup failed for "
                        f"{mask_ip(ip)}: {exc}"
                    )
            engine = info.get("engine")
            if engine is not None:
                try:
                    engine.stop()
                except Exception as exc:
                    log_warning(
                        f"Dead disruption engine cleanup failed for "
                        f"{mask_ip(ip)}: {exc}"
                    )
            arp_spoofer = info.get("arp_spoofer")
            if arp_spoofer is not None:
                try:
                    arp_spoofer.stop()
                except Exception as exc:
                    log_warning(
                        f"Dead disruption ARP cleanup failed for "
                        f"{mask_ip(ip)}: {exc}"
                    )
        with self._device_lock:
            return list(self.disrupted_devices.keys())

    def get_device_status_clumsy(self, target_ip: str) -> Dict:
        with self._device_lock:
            if target_ip not in self.disrupted_devices:
                return {"disrupted": False}
            info = self.disrupted_devices[target_ip]
        eng = info.get("engine")
        return {
            "disrupted": True,
            "engine": info.get("engine_name", "unknown"),
            "engine_preference": info.get("engine_preference", ENGINE_AUTO),
            "methods": info.get("methods", []),
            "params": info.get("params", {}),
            "start_time": info.get("start_time", 0),
            "process_running": eng.alive if eng else False,
            "pid": getattr(getattr(eng, '_proc', None), 'pid', None),
        }

    def get_clumsy_status(self) -> Dict:
        _exists = lambda p: bool(p and os.path.exists(p))
        with self._device_lock:
            dev_count = len(self.disrupted_devices)
            dev_list = list(self.disrupted_devices.keys())
        return {
            "is_running": self.is_running,
            "clumsy_exe_exists": _exists(self.clumsy_exe),
            "windivert_dll_exists": _exists(self.windivert_dll),
            "windivert_sys_exists": _exists(self.windivert_sys),
            "disrupted_devices_count": dev_count,
            "disrupted_devices": dev_list,
            "is_admin": self._is_admin(),
            "initialized": self._initialized,
            "engine_preferences": [ENGINE_AUTO, ENGINE_NATIVE, ENGINE_CLUMSY],
        }

    _STAT_KEYS = ("packets_processed", "packets_dropped", "packets_inbound",
                   "packets_outbound", "packets_passed")

    def get_all_engine_stats(self) -> Dict:
        """Aggregate stats from all active disruption engines."""
        totals = {k: 0 for k in self._STAT_KEYS}
        totals.update(active_engines=0, per_device={})
        with self._device_lock:
            for ip, info in self.disrupted_devices.items():
                eng = info.get("engine")
                if eng and hasattr(eng, 'get_stats'):
                    stats = eng.get_stats()
                    for k in self._STAT_KEYS:
                        totals[k] += stats.get(k, 0)
                    totals["active_engines"] += 1 if stats.get("alive") else 0
                    # Merge in the auto-detect metadata the GUI uses
                    # to render the "profile=ps5_hotspot / layer=forward
                    # / ARP-local forwarding=yes" badge line.
                    _det = info.get("detection")
                    if _det is not None:
                        stats = dict(stats)
                        stats["detection"] = _det
                    stats = dict(stats)
                    stats.setdefault(
                        "engine", info.get("engine_name", "unknown"))
                    stats.setdefault(
                        "engine_preference",
                        info.get("engine_preference", ENGINE_AUTO),
                    )
                    # Also surface spoofer liveness so the GUI can
                    # show a warning if the spoofer dropped but the
                    # engine kept running.
                    _arp = info.get("arp_spoofer")
                    if _arp is not None:
                        stats = dict(stats)
                        stats["arp_spoof_active"] = bool(
                            getattr(_arp, "_running", False))
                        stats["arp_packets_sent"] = int(
                            getattr(_arp, "packets_sent", 0)
                            if not callable(
                                getattr(_arp, "packets_sent", None))
                            else _arp.packets_sent()
                        )
                    totals["per_device"][ip] = stats
        return totals

    def start_clumsy(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        engine_name = "native WinDivert" if NATIVE_ENGINE_AVAILABLE else "clumsy.exe"
        log_info(f"Disruptor started (engine={engine_name})")

    def stop_clumsy(self) -> None:
        self.is_running = False
        self.clear_all_disruptions_clumsy()
        log_info("Disruptor stopped")

    # ── Clean interface (DisruptionManagerBase contract) ─────────────
    # New code should use these names. The _clumsy suffixed methods above
    # are preserved for backward compatibility.

    def start(self) -> None:
        """Activate the manager."""
        self.start_clumsy()

    def stop(self) -> None:
        """Deactivate the manager, stopping all disruptions."""
        self.stop_clumsy()

    def disrupt_device(self, ip: str, methods: Optional[List[str]] = None,
                       params: Optional[Dict] = None, **kwargs) -> bool:
        """Start disruption on *ip*.

        ``**kwargs`` are forwarded to ``disconnect_device_clumsy`` and may
        include ``target_mac``, ``target_hostname``, ``target_device_type``
        for profile auto-detection, or ``preset`` for explicit override.
        """
        return self.disconnect_device_clumsy(ip, methods, params, **kwargs)

    def stop_device(self, ip: str) -> bool:
        """Stop disruption on *ip*."""
        return self.reconnect_device_clumsy(ip)

    def stop_all_devices(self) -> bool:
        """Stop all active disruptions."""
        return self.clear_all_disruptions_clumsy()

    def get_disrupted_devices(self) -> List[str]:
        """Return IPs currently under disruption."""
        return self.get_disrupted_devices_clumsy()

    def mark_cut_outcome(self, persisted: bool, ip: Optional[str] = None) -> int:
        """Tag the currently-open cut with its survival-model label.

        Forwards to every active :class:`NativeWinDivertEngine` (or a
        specific one if *ip* is given) so the next ``cut_end`` event
        carries ``persisted`` into the episode JSONL. Returns the number
        of engines that accepted the label.

        ``persisted=False`` → dupe succeeded (hive did not flush).
        ``persisted=True``  → dupe failed (hive flushed normally).
        """
        count = 0
        with self._device_lock:
            items = (
                [(ip, self.disrupted_devices[ip])]
                if ip and ip in self.disrupted_devices
                else list(self.disrupted_devices.items())
            )
        for _target_ip, entry in items:
            engine = entry.get("engine")
            if engine is not None and hasattr(engine, "mark_last_cut_outcome"):
                try:
                    engine.mark_last_cut_outcome(bool(persisted))
                    count += 1
                except Exception as exc:
                    log_error(f"mark_cut_outcome failed for {mask_ip(_target_ip)}: {exc}")
        return count

    def get_device_status(self, ip: str) -> Dict:
        """Return status for a specific target."""
        return self.get_device_status_clumsy(ip)

    def get_status(self) -> Dict:
        """Return overall manager status."""
        return self.get_clumsy_status()

    def get_engine_stats(self) -> Dict:
        """Return aggregated packet stats from all engines."""
        return self.get_all_engine_stats()


# Global instance — the primary import target for all consumers.
# Legacy name preserved; prefer ``disruption_manager`` in new code.
clumsy_network_disruptor = ClumsyNetworkDisruptor()
disruption_manager = clumsy_network_disruptor
