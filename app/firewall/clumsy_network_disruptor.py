#!/usr/bin/env python3
"""
Clumsy Network Disruptor — packet disruption for DupeZ.

Two engines:
  1. NativeWinDivertEngine (primary) — loads WinDivert.dll directly via
     ctypes, intercepts packets in Python with zero GUI. No window, no
     flash, completely invisible. Implements all 9 disruption modules.

  2. ClumsyEngine (fallback) — launches clumsy.exe (kalirenegade-dev
     v0.3.4), automates its GUI via Win32 SendMessageW, then hides the
     window off-screen. Used only when the native engine fails to load.

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
import subprocess
import traceback
import ctypes
from ctypes import wintypes
from typing import Any, Dict, List, Optional
from app.logs.logger import log_info, log_error
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
    "EM_SETSEL",
    "VK_DELETE",
    "BST_CHECKED",
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
EM_SETSEL            = 0x00B1
VK_DELETE            = 0x2E
BST_CHECKED          = 0x0001

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

# EnumWindows callback type
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
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
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "clumsy.exe"],
            capture_output=True, timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (result.stdout or b"").decode(errors="ignore").strip()
        if "SUCCESS" in out.upper():
            log_info(f"Killed existing clumsy.exe: {out}")
            time.sleep(0.05)  # Minimal pause — handle releases fast
        else:
            log_info("No existing clumsy.exe to kill")
    except Exception as e:
        log_info(f"taskkill clumsy.exe: {e} (probably not running)")
class ClumsyEngine:
    """Launch clumsy.exe and click its Start button via Win32 GUI automation.

    Fallback engine used when native WinDivert fails. The clumsy window
    will flash briefly on screen before being hidden.

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
        try:
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

            # Step 3: Launch
            self._proc = subprocess.Popen(
                cmd_list, cwd=self.clumsy_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
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
                    self._proc = subprocess.Popen(
                        cmd_list, cwd=self.clumsy_dir,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW,
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
        """Check if clumsy.exe has been rebuilt with --silent support.

        We look for the string '--silent' in the binary. The modified
        clumsy has this string literal in main() for arg detection.
        """
        try:
            with open(exe_path, 'rb') as f:
                content = f.read()
            if b'--silent' in content:
                log_info("ClumsyEngine: --silent flag detected in binary")
                return True
            else:
                log_info("ClumsyEngine: --silent NOT found in binary (original clumsy)")
                return False
        except Exception as e:
            log_info(f"ClumsyEngine: could not check binary for --silent: {e}")
            return False

    def _start_gui_automation(self) -> bool:
        """Fallback: find clumsy window, click checkboxes, click Start, hide.

        Used when --silent mode is not supported by the clumsy.exe binary.
        """
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

            # Enable modules, click sub-checkboxes, type input values
            for step in (self._enable_modules, self._click_sub_checkboxes, self._set_input_values):
                try:
                    step()
                except Exception as e:
                    log_error(f"ClumsyEngine GUI: {step.__name__} error: {e}")

            # Click the Start button
            started = self._click_start_button()
            if not started:
                started = self._try_keybind_fallback()

            if not started:
                log_error("ClumsyEngine GUI: could not start filtering")
                return False

            time.sleep(0.1)
            if self._proc.poll() is not None:
                log_error(f"ClumsyEngine GUI: process died (rc={self._proc.returncode})")
                self._proc = None
                return False

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
        return enabled_count > 0

    def _click_sub_checkboxes(self) -> None:
        """Click sub-checkboxes that need explicit toggling for C variable sync.

        preset1_config() uses IupSetAttribute which does NOT fire ACTION
        callbacks. We must click to fire uiSyncToggle → InterlockedExchange16.

        Sub-checks: (param_key, checkbox_text, c_default)
          - dropThrottled = 0 (OFF) ← click if user wants throttle+drop
          - doChecksum = 1 (ON) ← click only if user wants OFF
        """
        p = self.params
        sub_checks = [
            ("throttle_drop", "Drop Throttled", 0),
            ("tamper_checksum", "Redo Checksum", 1),
        ]

        for param_key, cb_text, c_default in sub_checks:
            desired = bool(p.get(param_key, False))
            need_click = (c_default == 0 and desired) or (c_default == 1 and not desired)
            if not need_click:
                log_info(f"  Sub-checkbox '{cb_text}': no click needed "
                         f"(default={c_default}, desired={desired})")
                continue

            cb_hwnd = self._find_checkbox(cb_text)
            if not cb_hwnd:
                log_error(f"  Sub-checkbox '{cb_text}' NOT FOUND — "
                          f"C variable stays at default ({c_default})")
                continue

            log_info(f"  Clicking sub-checkbox '{cb_text}' "
                     f"(hwnd={cb_hwnd}, default={c_default}→desired={desired})")
            expected = BST_CHECKED if desired else 0
            self._click_and_verify(cb_hwnd, cb_text, expected_state=expected)

    def _set_input_values(self) -> None:
        """Type numeric values into clumsy's EDIT controls via WM_CHAR.

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

        # Map each EDIT index to a param key and type the value
        values_set = 0
        for idx, param_key in EDIT_INDEX_MAP.items():
            if idx >= len(edits):
                log_error(f"  EDIT[{idx}] ({param_key}): index out of range "
                          f"(only {len(edits)} EDITs found)")
                continue

            value = p.get(param_key)
            if value is None:
                continue  # param not set by GUI, leave default

            value_str = str(int(value))
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

        log_info(f"_set_input_values: {values_set} values typed successfully")

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
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    capture_output=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception as exc:
                log_error(f"ClumsyEngine: taskkill failed: {exc}")
                try:
                    self._proc.kill()
                except Exception as kill_exc:
                    log_error(f"ClumsyEngine: kill fallback failed: {kill_exc}")
            self._proc = None
        self._hwnd = None
        log_info("ClumsyEngine stopped")

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---- cleanup ----

    def _cleanup(self) -> None:
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

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
        dup_ct   = int(p.get("duplicate_count", 10))  if "duplicate" in methods else 0
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
                 f"thr={thr_ch}%/{thr_fr}ms, dup={dup_ct}x/{dup_ch}%, ood={ood_ch}%")

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
                    "tick_sync_direction": _profile.get("tick_sync_direction", "inbound"),
                    "pulse_direction": _profile.get("pulse_direction", "inbound"),
                    "stealth_drop_direction": _profile.get("stealth_drop_direction", "inbound"),
                    "stealth_lag_direction": _profile.get("stealth_lag_direction", "inbound"),
                    "godmode_lag_ms": _profile.get("godmode_lag_ms", 3000),
                    "godmode_drop_inbound_pct": _profile.get("godmode_drop_inbound_pct", 0),
                    "godmode_keepalive_interval_ms": _profile.get("godmode_keepalive_interval_ms", 800),
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
                    "tick_sync_direction": "inbound",
                    "pulse_direction": "inbound",
                    "stealth_drop_direction": "inbound",
                    "stealth_lag_direction": "inbound",
                    "godmode_lag_ms": 3500,
                    "godmode_drop_inbound_pct": 0,
                    "godmode_keepalive_interval_ms": 800,
                }

        # ── Resolve methods list ───────────────────────────────────────
        # Preset-supplied methods win if the caller didn't pass any.
        if methods is None:
            preset_methods = params.get("methods")
            if isinstance(preset_methods, list) and preset_methods:
                methods = list(preset_methods)
            else:
                # Default method set depends on whether we're running
                # PC-local or on the FORWARD layer. FORWARD-layer (PS5/Xbox
                # over ICS hotspot) benefits from pulse+tick_sync+stealth
                # because the 32-packet ack-redundancy ceiling means the
                # original drop/lag/bandwidth/throttle combo can't reliably
                # desync state without triggering the 1.27+ freeze system.
                is_local_default = bool(params.get("_network_local", False))
                if is_local_default:
                    methods = ["drop", "lag", "bandwidth", "throttle"]
                else:
                    methods = ["pulse", "tick_sync", "stealth_drop", "lag"]

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
            # WiFi same-network mode:
            #   - Target is on same WiFi LAN but traffic doesn't route
            #     through us. ARP spoof redirects traffic through us,
            #     then NETWORK_FORWARD layer intercepts it.
            is_local = params.get("_network_local", False)

            # ── ARP spoofing for WiFi same-network ────────────────
            # If auto-detection says we need ARP spoofing, start it
            # BEFORE opening WinDivert so traffic is already flowing
            # through us when the FORWARD layer opens.
            _arp_spoofer = None
            needs_arp = (
                _detection is not None
                and getattr(_detection, "needs_arp_spoof", False)
            )
            if needs_arp:
                # ARP-spoof capture is asymmetric: only one leg of the
                # target↔gateway flow lands through us (gateway caches on
                # consumer routers are harder to poison than endpoint caches,
                # so OUTBOUND target→gateway typically wins). Presets like
                # ps5_hotspot default all module directions to "inbound" —
                # correct for NETWORK_FORWARD on the ICS host, wrong here.
                # Force "both" so LagModule/pulse/tick_sync consume whatever
                # we actually capture (OUT, IN, or both).
                _arp_dir_keys = (
                    "direction",
                    "tick_sync_direction",
                    "pulse_direction",
                    "stealth_drop_direction",
                    "stealth_lag_direction",
                )
                for _k in _arp_dir_keys:
                    if params.get(_k) != "both":
                        log_info(
                            f"[WiFi] ARP-spoof path: forcing {_k}="
                            f"'both' (was {params.get(_k)!r})"
                        )
                        params[_k] = "both"
                try:
                    from app.network.arp_spoof import ArpSpoofer
                    from app.network.npcap_check import check_npcap
                    from app.logs.gui_notify import gui_toast

                    _npcap = check_npcap()
                    if not _npcap.available:
                        log_error(
                            f"[WiFi] Cannot ARP-spoof: {_npcap.reason}. "
                            f"Install Npcap: {_npcap.install_url}"
                        )
                        gui_toast(
                            "error",
                            f"WiFi same-network target detected but "
                            f"{_npcap.reason}. Install Npcap to enable "
                            f"ARP-spoof interception.",
                        )
                    else:
                        log_info(
                            f"[WiFi] Target {mask_ip(target_ip)} is on same "
                            f"WiFi network — activating ARP spoofing to "
                            f"redirect traffic through this machine"
                        )
                        gui_toast(
                            "info",
                            f"WiFi same-net target — starting ARP spoof "
                            f"({mask_ip(target_ip)})",
                        )
                        _arp_spoofer = ArpSpoofer(target_ip=target_ip)
                        if _arp_spoofer.start():
                            log_info("[WiFi] ARP spoofing active — traffic "
                                     "redirected, using NETWORK_FORWARD layer")
                            # Force FORWARD layer — traffic now routes through us
                            is_local = False
                            params["_network_local"] = False
                        else:
                            log_error(
                                "[WiFi] ARP spoofing failed to start. "
                                "Falling back to NETWORK layer (limited "
                                "effectiveness on WiFi same-network)."
                            )
                            gui_toast(
                                "error",
                                "ARP spoof failed to start — check logs. "
                                "Falling back to NETWORK layer (weak).",
                            )
                            _arp_spoofer = None
                except ImportError:
                    log_error("[WiFi] arp_spoof module not available")
                    try:
                        from app.logs.gui_notify import gui_toast as _t
                        _t("error", "ARP-spoof module unavailable.")
                    except Exception:
                        pass
                except Exception as arp_err:
                    log_error(f"[WiFi] ARP spoof error: {arp_err}")
                    try:
                        from app.logs.gui_notify import gui_toast as _t
                        _t("error", f"ARP spoof error: {arp_err}")
                    except Exception:
                        pass
                    _arp_spoofer = None

            if target_ip and target_ip != "unknown":
                filt_expr = (
                    f"ip.SrcAddr == {target_ip} or "
                    f"ip.DstAddr == {target_ip}"
                )
            else:
                filt_expr = "true"

            mode_label = "PC-LOCAL (NETWORK)" if is_local else "REMOTE (NETWORK_FORWARD)"
            if _arp_spoofer:
                mode_label += " + ARP SPOOF"
            log_info(f"{'='*50}\nDISRUPTION START: {mask_ip(target_ip)}\n"
                     f"  mode={mode_label}  methods={methods}"
                     f"  direction={params.get('direction', 'both')}"
                     f"  filter={filt_expr}\n{'='*50}")

            # FORWARD-layer cannot originate keepalives on the device's
            # behalf — the local Windows stack can't forge the device's
            # NAT binding without ICS cooperation. Surface this once so
            # nobody wastes time tuning godmode_keepalive_interval_ms on
            # PS5/Xbox targets.
            if not is_local and "godmode" in methods:
                log_info(
                    "FORWARD-layer keepalive injection is a no-op — "
                    "local stack cannot forge device NAT bindings. "
                    "godmode_keepalive_interval_ms ignored in this mode."
                )

            clumsy_dir = self._get_clumsy_dir()
            eng_params = dict(params)
            eng_params["_target_ip"] = target_ip
            eng_params["_network_local"] = is_local

            engine = None

            # Strategy 1: Native WinDivert engine (no GUI, no window)
            if NATIVE_ENGINE_AVAILABLE:
                log_info("Trying native WinDivert engine (no clumsy.exe)...")
                try:
                    native_engine = NativeWinDivertEngine(
                        dll_path=self.windivert_dll,
                        filter_str=filt_expr,
                        methods=methods,
                        params=eng_params,
                    )
                    if native_engine.start():
                        engine = native_engine
                        # Give the engine a handle to the live spoofer so
                        # its flow-health watchdog can produce actionable
                        # diagnostics ("ARP active but no packets" vs
                        # "no spoofer, switched LAN may need one").
                        try:
                            native_engine._arp_spoofer = _arp_spoofer
                        except Exception:
                            pass
                        log_info("Native WinDivert engine started successfully")
                    else:
                        log_error("Native engine start returned False — "
                                  "falling back to clumsy.exe")
                except Exception as e:
                    log_error(f"Native engine error: {e} — falling back to clumsy.exe")

            # Strategy 2: Clumsy.exe GUI automation (fallback)
            if engine is None:
                log_info("Using clumsy.exe GUI automation engine...")
                engine = ClumsyEngine(
                    clumsy_exe=self.clumsy_exe,
                    clumsy_dir=clumsy_dir,
                    filter_str=filt_expr,
                    methods=methods,
                    params=eng_params,
                )
                if not engine.start():
                    log_error("ClumsyEngine start FAILED")
                    return False

            with self._device_lock:
                self.disrupted_devices[target_ip] = {
                    "engine": engine,
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
            engine = info.get("engine")
            if engine:
                engine.stop()

            # Stop ARP spoofing if active — restore real ARP entries
            # and disable IP forwarding (if we enabled it).
            arp_spoofer = info.get("arp_spoofer")
            if arp_spoofer is not None:
                try:
                    arp_spoofer.stop()
                    log_info(f"[WiFi] ARP spoofing stopped for "
                             f"{mask_ip(target_ip)}")
                except Exception as arp_err:
                    log_error(f"[WiFi] ARP spoof cleanup error: {arp_err}")

            log_info(f"Disruption stopped: {mask_ip(target_ip)}")
            return True
        except Exception as e:
            log_error(f"Error stopping {mask_ip(target_ip)}: {e}")
            with self._device_lock:
                self.disrupted_devices.pop(target_ip, None)
            return False

    def clear_all_disruptions_clumsy(self) -> bool:
        with self._device_lock:
            ips = list(self.disrupted_devices.keys())
        for ip in ips:
            self.reconnect_device_clumsy(ip)
        return True

    def get_disrupted_devices_clumsy(self) -> List[str]:
        with self._device_lock:
            dead = [ip for ip, info in self.disrupted_devices.items()
                    if info.get("engine") and not info["engine"].alive]
            dead_infos = {ip: self.disrupted_devices.pop(ip) for ip in dead}
        for ip, info in dead_infos.items():
            if info.get("engine"):
                info["engine"].stop()
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
                    # / ARP-spoof=yes" badge line.
                    _det = info.get("detection")
                    if _det is not None:
                        stats = dict(stats)
                        stats["detection"] = _det
                    # Also surface ARP spoofer liveness so the GUI can
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

