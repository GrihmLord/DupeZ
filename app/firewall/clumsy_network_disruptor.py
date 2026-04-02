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

import os
import sys
import time
import threading
import subprocess
import traceback
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional
from app.logs.logger import log_info, log_error

# Native WinDivert engine — primary engine (no GUI, no window)
try:
    from app.firewall.native_divert_engine import NativeWinDivertEngine
    NATIVE_ENGINE_AVAILABLE = True
    log_info("Native WinDivert engine available")
except ImportError as e:
    NATIVE_ENGINE_AVAILABLE = False
    log_info(f"Native WinDivert engine not available: {e} (falling back to clumsy.exe)")


# ======================================================================
# Win32 Constants
# ======================================================================
CREATE_NO_WINDOW   = 0x08000000

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


# ======================================================================
# Window management
# ======================================================================
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


def _type_into_edit(hwnd, value_str: str):
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

    # Verify what was typed
    final = _get_window_text(hwnd)
    return final


def _hide_window(hwnd) -> bool:
    """Make a window completely invisible: transparent + no taskbar + hidden."""
    try:
        user32 = ctypes.windll.user32

        # 1. Add WS_EX_TOOLWINDOW (removes from taskbar / Alt+Tab)
        #    Add WS_EX_LAYERED (allows transparency)
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




def _kill_all_clumsy():
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


# ======================================================================
# Clumsy Engine — GUI automation (fallback if native WinDivert fails)
# ======================================================================
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
                 filter_str: str, methods: list, params: dict):
        self.clumsy_exe = clumsy_exe
        self.clumsy_dir = clumsy_dir
        self.filter_str = filter_str
        self.methods = methods
        self.params = params
        self._proc = None
        self._hwnd = None

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
            presets_path = os.path.join(self.clumsy_dir, "presets.ini")
            config_path = os.path.join(self.clumsy_dir, "config.txt")
            if not os.path.isfile(presets_path):
                log_error(f"FATAL: presets.ini NOT FOUND at {presets_path}")
                return False
            if not os.path.isfile(config_path):
                log_error(f"FATAL: config.txt NOT FOUND at {config_path}")
                return False
            presets_size = os.path.getsize(presets_path)
            config_size = os.path.getsize(config_path)
            log_info(f"presets.ini: {presets_path} ({presets_size} bytes)")
            log_info(f"config.txt: {config_path} ({config_size} bytes)")
            if presets_size < 100:
                log_error(f"FATAL: presets.ini too small ({presets_size} bytes)")
                return False
            if config_size < 10:
                log_error(f"FATAL: config.txt too small ({config_size} bytes)")
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

            # Enable modules via checkbox clicks
            try:
                self._enable_modules()
            except Exception as e:
                log_error(f"ClumsyEngine GUI: _enable_modules error: {e}")

            # Click sub-checkboxes
            try:
                self._click_sub_checkboxes()
            except Exception as e:
                log_error(f"ClumsyEngine GUI: _click_sub_checkboxes error: {e}")

            # Type numeric values into input fields
            try:
                self._set_input_values()
            except Exception as e:
                log_error(f"ClumsyEngine GUI: _set_input_values error: {e}")

            # Click the Start button
            started = self._click_start_button()
            if not started:
                started = self._try_keybind_fallback()

            if not started:
                log_error("ClumsyEngine GUI: could not start filtering")
                return False

            # Verify process is alive
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

        This is exactly what the user does manually in standalone clumsy.
        """
        user32 = ctypes.windll.user32
        enabled_count = 0

        for module_name in self.methods:
            cb_text = MODULE_CHECKBOX_TEXT.get(module_name)
            if not cb_text:
                log_info(f"  Module '{module_name}' has no checkbox mapping — skip")
                continue

            # Find the checkbox by its label text
            cb_hwnd = _find_child_by_text(self._hwnd, cb_text)
            if not cb_hwnd:
                # Also try searching all BUTTON-class children for partial match
                all_buttons = _find_children_by_class(self._hwnd, "BUTTON")
                for btn in all_buttons:
                    text = _get_window_text(btn)
                    if text.lower() == cb_text.lower():
                        cb_hwnd = btn
                        break
            if not cb_hwnd:
                log_error(f"  Could not find '{cb_text}' checkbox in window")
                continue

            log_info(f"  Clicking '{cb_text}' checkbox (hwnd={cb_hwnd})")

            # Single click — checkbox starts UNCHECKED (presets set all to false)
            # BM_CLICK toggles it ON and fires ACTION callback → enabledFlag = 1
            _click_button(cb_hwnd)
            time.sleep(0.05)  # give IUP time to process the callback

            # Verify it's now checked
            state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
            if state == BST_CHECKED:
                enabled_count += 1
                log_info(f"  '{cb_text}': CONFIRMED enabled (checked)")
            else:
                log_error(f"  '{cb_text}': click may have failed "
                          f"(state={state}), retrying...")
                # Retry once
                _click_button(cb_hwnd)
                time.sleep(0.05)
                state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
                if state == BST_CHECKED:
                    enabled_count += 1
                    log_info(f"  '{cb_text}': CONFIRMED enabled on retry")
                else:
                    log_error(f"  '{cb_text}': STILL not checked after retry")

        log_info(f"_enable_modules: {enabled_count}/{len(self.methods)} "
                 "modules physically enabled")
        return enabled_count > 0

    def _click_sub_checkboxes(self):
        """Click sub-checkboxes inside module controls that need explicit toggling.

        CRITICAL BUG FIX: preset1_config() uses IupSetAttribute to set
        sub-checkboxes like "Drop Throttled" and "Redo Checksum". This
        changes the VISUAL state but does NOT fire their ACTION callbacks.
        The ACTION callback calls uiSyncToggle → InterlockedExchange16 to
        set the C variable (dropThrottled, doChecksum).

        Default C values:
          - dropThrottled = 0 (OFF) ← MUST CLICK if user wants throttle+drop
          - doChecksum = 1 (ON) ← defaults ON, only click if user wants OFF

        These sub-checkboxes are BUTTON-class children inside the module's
        controls HBox. They become ACTIVE only after _enable_modules clicks
        the module's main enable checkbox (uiToggleControls sets ACTIVE="YES").
        """
        user32 = ctypes.windll.user32
        p = self.params

        # Map: (param_key, checkbox_text, default_c_value, desired_when_true)
        # We click if the param is True and default is 0 (OFF → ON)
        # or if the param is False and default is 1 (ON → OFF)
        sub_checks = [
            # throttle_drop: C default dropThrottled=0. Click once → ON.
            ("throttle_drop", "Drop Throttled", 0),
            # tamper_checksum: C default doChecksum=1. Already ON.
            # Only click if user explicitly set it to False (toggle OFF).
            ("tamper_checksum", "Redo Checksum", 1),
        ]

        for param_key, cb_text, c_default in sub_checks:
            desired = bool(p.get(param_key, False))

            # Determine if we need to click:
            # If c_default=0 (OFF) and desired=True → click once to turn ON
            # If c_default=1 (ON) and desired=False → click once to turn OFF
            # If c_default matches desired → no click needed
            need_click = (c_default == 0 and desired) or (c_default == 1 and not desired)

            if not need_click:
                log_info(f"  Sub-checkbox '{cb_text}': no click needed "
                         f"(default={c_default}, desired={desired})")
                continue

            # Find the checkbox by text
            cb_hwnd = _find_child_by_text(self._hwnd, cb_text)
            if not cb_hwnd:
                # Fallback: search all BUTTON children for partial match
                all_buttons = _find_children_by_class(self._hwnd, "BUTTON")
                for btn in all_buttons:
                    text = _get_window_text(btn)
                    if text.lower() == cb_text.lower():
                        cb_hwnd = btn
                        break

            if not cb_hwnd:
                log_error(f"  Sub-checkbox '{cb_text}' NOT FOUND — "
                          f"C variable stays at default ({c_default})")
                continue

            log_info(f"  Clicking sub-checkbox '{cb_text}' "
                     f"(hwnd={cb_hwnd}, default={c_default}→desired={desired})")
            _click_button(cb_hwnd)
            time.sleep(0.05)

            # Verify
            state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
            expected = BST_CHECKED if desired else 0
            if state == expected:
                log_info(f"  '{cb_text}': CONFIRMED {'checked' if desired else 'unchecked'}")
            else:
                log_error(f"  '{cb_text}': state={state}, expected={expected} — retrying")
                _click_button(cb_hwnd)
                time.sleep(0.05)
                state = user32.SendMessageW(cb_hwnd, BM_GETCHECK, 0, 0)
                if state == expected:
                    log_info(f"  '{cb_text}': CONFIRMED on retry")
                else:
                    log_error(f"  '{cb_text}': STILL wrong after retry (state={state})")

    def _set_input_values(self):
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

            # Get the value from GUI params
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

    def stop(self):
        """Kill clumsy.exe and clean up."""
        if self._proc:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    capture_output=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._hwnd = None
        log_info("ClumsyEngine stopped")

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---- cleanup ----

    def _cleanup(self):
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    # ---- config file writers ----

    def _write_config(self):
        """Write config.txt next to clumsy.exe with filter expression.

        loadConfig() in clumsy uses GetModuleFileName() to find config.txt
        relative to the EXE path (NOT CWD). Format is:
            filter_name: filter_expression
        where ':' is the delimiter. First entry becomes the default filter
        in the text field (line 1263: filterText VALUE = filters[0].filterValue).
        """
        path = os.path.join(self.clumsy_dir, "config.txt")
        content = f"DupeZ: {self.filter_str}\n"

        with open(path, "w") as f:
            f.write(content)
        log_info(f"config.txt written: {path}")
        log_info(f"  filter entry: DupeZ: {self.filter_str}")

    def _write_presets(self):
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

        lag_in, lag_out   = flag("lag")
        drop_in, drop_out = flag("drop")
        disc_in, disc_out = flag("disconnect")
        bw_in, bw_out     = flag("bandwidth")
        thr_in, thr_out   = flag("throttle")
        dup_in, dup_out   = flag("duplicate")
        ood_in, ood_out   = flag("ood")
        tam_in, tam_out   = flag("corrupt") if "corrupt" in methods else flag("tamper")
        rst_in, rst_out   = flag("rst")

        log_info(f"presets.ini Preset1: methods={methods}, direction={direction}")
        log_info(f"  Lag delay={lag_del}, Drop chance={drop_ch}, RST chance={rst_ch}")
        log_info(f"  Throttle chance={thr_ch}, frame={thr_fr}, drop_throttled={thr_dr}")
        log_info(f"  Duplicate count={dup_ct}, chance={dup_ch}, OOD chance={ood_ch}")
        log_info(f"  Inbound/outbound flags set per direction={direction}")

        content = f"""\
[General]
Keybind = [

[Preset1]
PresetName = DupeZ
Lag_Inbound = {lag_in}
Lag_Outbound = {lag_out}
Lag_Delay = {lag_del}
Drop_Inbound = {drop_in}
Drop_Outbound = {drop_out}
Drop_Chance = {drop_ch}
Disconnect_Inbound = {disc_in}
Disconnect_Outbound = {disc_out}
BandwidthLimiter_QueueSize = {bw_q}
BandwidthLimiter_Size = {bw_sz}
BandwidthLimiter_Inbound = {bw_in}
BandwidthLimiter_Outbound = {bw_out}
BandwidthLimiter_Limit = {bw_lim}
Throttle_DropThrottled = {thr_dr}
Throttle_Timeframe = {thr_fr}
Throttle_Inbound = {thr_in}
Throttle_Outbound = {thr_out}
Throttle_Chance = {thr_ch}
Duplicate_Count = {dup_ct}
Duplicate_Inbound = {dup_in}
Duplicate_Outbound = {dup_out}
Duplicate_Chance = {dup_ch}
OutOfOrder_Inbound = {ood_in}
OutOfOrder_Outbound = {ood_out}
OutOfOrder_Chance = {ood_ch}
Tamper_RedoChecksum = {tam_cs}
Tamper_Inbound = {tam_in}
Tamper_Outbound = {tam_out}
Tamper_Chance = {tam_ch}
SetTCPRST_Inbound = {rst_in}
SetTCPRST_Outbound = {rst_out}
SetTCPRST_Chance = {rst_ch}
"""
        # Empty presets 2-5 (ALL must be present or ini_parse fails → exit 1)
        for i in range(2, 6):
            content += f"""
[Preset{i}]
PresetName = Preset_{i}
Lag_Inbound = false
Lag_Outbound = false
Lag_Delay = 0
Drop_Inbound = false
Drop_Outbound = false
Drop_Chance = 0
Disconnect_Inbound = false
Disconnect_Outbound = false
BandwidthLimiter_QueueSize = 0
BandwidthLimiter_Size = kb
BandwidthLimiter_Inbound = false
BandwidthLimiter_Outbound = false
BandwidthLimiter_Limit = 0
Throttle_DropThrottled = false
Throttle_Timeframe = 0
Throttle_Inbound = false
Throttle_Outbound = false
Throttle_Chance = 0
Duplicate_Count = 0
Duplicate_Inbound = false
Duplicate_Outbound = false
Duplicate_Chance = 0
OutOfOrder_Inbound = false
OutOfOrder_Outbound = false
OutOfOrder_Chance = 0
Tamper_RedoChecksum = false
Tamper_Inbound = false
Tamper_Outbound = false
Tamper_Chance = 0
SetTCPRST_Inbound = false
SetTCPRST_Outbound = false
SetTCPRST_Chance = 0
"""
        path = os.path.join(self.clumsy_dir, "presets.ini")
        with open(path, "w") as f:
            f.write(content)
        log_info(f"presets.ini written: {path} ({len(content)} chars)")

        # Read back to verify
        try:
            with open(path, "r") as f:
                head = f.read(200)
            log_info(f"presets.ini readback: {head[:200]}")
        except Exception as e:
            log_error(f"presets.ini readback failed: {e}")


# ======================================================================
# Public API — same interface the controller and GUI expect
# ======================================================================
class ClumsyNetworkDisruptor:
    def __init__(self):
        self.is_running = False
        self.disrupted_devices: Dict[str, dict] = {}
        self._device_lock = threading.Lock()
        self.clumsy_exe = None
        self.windivert_dll = None
        self.windivert_sys = None
        self._initialized = False
        self._init_paths()

    def _init_paths(self):
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
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _get_clumsy_dir(self):
        return os.path.dirname(os.path.abspath(self.clumsy_exe))

    # ------------------------------------------------------------------
    # Core disruption
    # ------------------------------------------------------------------
    def disconnect_device_clumsy(self, target_ip: str,
                                  methods: Optional[List[str]] = None,
                                  params: Optional[Dict] = None) -> bool:
        if methods is None:
            methods = ["disconnect", "drop", "lag", "bandwidth", "throttle"]
        if params is None:
            params = {
                "lag_delay": 1500, "drop_chance": 95,
                "bandwidth_limit": 1, "bandwidth_queue": 0,
                "throttle_chance": 100, "throttle_frame": 400,
                "throttle_drop": True, "direction": "both",
            }

        try:
            if target_ip in self.disrupted_devices:
                log_info(f"{target_ip} already disrupted — restarting")
                self.reconnect_device_clumsy(target_ip)

            if not self._initialized:
                if not self.initialize():
                    log_error("Cannot disrupt: initialization failed")
                    return False

            # Use "true" filter — captures ALL packets on the WinDivert layer.
            # This matches the user's proven working standalone config.
            # IP-specific filters fail on NETWORK_FORWARD (ICS/hotspot) due
            # to NAT translation timing. "true" is what clumsy uses by default
            # and what actually produces disruption on the 192.168.137.x subnet.
            filt_expr = "true"

            log_info(f"{'='*50}")
            log_info(f"DISRUPTION START: {target_ip}")
            log_info(f"  methods={methods}")
            log_info(f"  direction={params.get('direction', 'both')}")
            log_info(f"  filter={filt_expr}")
            log_info(f"{'='*50}")

            clumsy_dir = self._get_clumsy_dir()
            eng_params = dict(params)
            eng_params["_target_ip"] = target_ip

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
                }
            log_info(f"DISRUPTION ACTIVE: {target_ip} (PID={engine._proc.pid})")
            return True

        except Exception as e:
            log_error(f"DISRUPTION FAILED for {target_ip}: {e}")
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
            log_info(f"Disruption stopped: {target_ip}")
            return True
        except Exception as e:
            log_error(f"Error stopping {target_ip}: {e}")
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
        return {
            "is_running": self.is_running,
            "clumsy_exe_exists": bool(self.clumsy_exe and os.path.exists(self.clumsy_exe)),
            "windivert_dll_exists": bool(self.windivert_dll and os.path.exists(self.windivert_dll)),
            "windivert_sys_exists": bool(self.windivert_sys and os.path.exists(self.windivert_sys)),
            "disrupted_devices_count": len(self.disrupted_devices),
            "disrupted_devices": list(self.disrupted_devices.keys()),
            "is_admin": self._is_admin(),
            "initialized": self._initialized,
        }

    def start_clumsy(self):
        self.is_running = True
        engine_name = "native WinDivert" if NATIVE_ENGINE_AVAILABLE else "clumsy.exe"
        log_info(f"Disruptor started (engine={engine_name})")

    def stop_clumsy(self):
        self.is_running = False
        self.clear_all_disruptions_clumsy()
        log_info("Disruptor stopped")


# Global instance
clumsy_network_disruptor = ClumsyNetworkDisruptor()
