#!/usr/bin/env python3
"""
DupeZ — Single root launcher.
Run this file to start DupeZ.  Works both as a script and as PyInstaller entry.
"""
import sys, os

# ── Frozen helper-mode dispatch (ADR-0001 split) ───────────────────
# Under DupeZ-GPU.exe, the elevated helper process is the SAME frozen
# exe re-invoked with `--role helper`. We dispatch to the helper entry
# point BEFORE any self-elevation or GUI imports, so a runas-spawned
# "DupeZ-GPU.exe --role helper --parent-pid N" does NOT boot the GUI
# again (which previously caused an infinite admin-spawn loop).
def _maybe_dispatch_helper_role() -> None:
    if "--role" not in sys.argv:
        return
    try:
        i = sys.argv.index("--role")
    except ValueError:
        return
    if i + 1 >= len(sys.argv) or sys.argv[i + 1] != "helper":
        return
    # Ensure bundle/repo root on path for `import dupez_helper` and app.*.
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    # PyInstaller: bundled modules live in _MEIPASS.
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass and _meipass not in sys.path:
        sys.path.insert(0, _meipass)
    try:
        import dupez_helper  # noqa: E402
    except Exception as e:
        sys.stderr.write(f"[dupez] helper dispatch: import failed: {e}\n")
        sys.exit(1)
    sys.exit(dupez_helper.main() or 0)


_maybe_dispatch_helper_role()

# ── ADR-0001 manifest-flip compat shim ─────────────────────────────
# The Win32 manifest was flipped from `requireAdministrator` to
# `asInvoker` so the GUI can launch at Medium IL under DUPEZ_ARCH=split
# (required for Chromium GPU init in the embedded map).
#
# But the DEFAULT architecture is still `inproc`, which needs admin so
# WinDivert can load. Without this shim, a double-click launch on a
# fresh install would come up at Medium IL, try to initialize WinDivert,
# fail, and hard-crash. That's a regression vs the shipped behavior.
#
# Rule:
#   DUPEZ_ARCH=inproc (default) + not admin  → self-elevate via runas,
#                                               then exit this Medium-IL
#                                               instance. The elevated
#                                               re-launch runs the real
#                                               app.
#   DUPEZ_ARCH=inproc           + admin      → proceed as before.
#   DUPEZ_ARCH=split            + any        → proceed at Medium IL; the
#                                               elevation module spawns
#                                               the helper elevated.
#
# This runs BEFORE any app.* or PyQt6 import so nothing gets booted in
# the wrong integrity level.
def _inproc_self_elevate_if_needed() -> None:
    if sys.platform != "win32":
        return
    # Resolve arch the same way feature_flag.get_arch() does, so the
    # compiled-in variant default (split for DupeZ-GPU.exe, inproc for
    # DupeZ-Compat.exe) is honored. Env var still wins if explicitly set.
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        _meipass = getattr(sys, "_MEIPASS", None)
        if _meipass and _meipass not in sys.path:
            sys.path.insert(0, _meipass)
        from app.firewall_helper.feature_flag import is_split_mode
        if is_split_mode():
            return  # split mode runs unelevated on purpose
    except Exception:
        # Fallback to legacy env-var-only behavior if feature_flag can't
        # be imported this early (should never happen under a normal build).
        arch = (os.environ.get("DUPEZ_ARCH") or "inproc").strip().lower()
        if arch != "inproc":
            return
    try:
        import ctypes
        if bool(ctypes.windll.shell32.IsUserAnAdmin()):
            return  # already elevated — carry on
    except Exception:
        return  # can't probe, don't block startup

    # Not admin + inproc — re-launch elevated via ShellExecuteW runas.
    # ERROR_CANCELLED (1223) = user said no; surface a readable message
    # and exit so the UAC decline doesn't look like a silent crash.
    try:
        import ctypes
        if getattr(sys, "frozen", False):
            # PyInstaller bundle — relaunch self.
            lp_file = sys.executable
            lp_params = " ".join('"' + a + '"' for a in sys.argv[1:])
        else:
            # Dev path — relaunch python with this script.
            lp_file = sys.executable
            script = os.path.abspath(__file__)
            lp_params = '"' + script + '" ' + " ".join(
                '"' + a + '"' for a in sys.argv[1:]
            )
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", lp_file, lp_params,
            os.path.dirname(os.path.abspath(__file__)), 1,
        )
        if int(rc) <= 32:
            # ShellExecuteW returns <=32 on failure. 5 = ERROR_ACCESS_DENIED
            # is the decline path on some Windows builds; also surface any
            # other failure plainly.
            try:
                import ctypes.wintypes as _wt  # noqa: F401
                err = ctypes.GetLastError()
            except Exception:
                err = -1
            sys.stderr.write(
                f"[dupez] UAC elevation failed (ShellExecuteW rc={rc} "
                f"err={err}). Right-click DupeZ and choose 'Run as "
                f"administrator', or set DUPEZ_ARCH=split to run unelevated.\n"
            )
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"[dupez] self-elevation crashed: {e}\n")
        sys.exit(1)


_inproc_self_elevate_if_needed()

# ── QtWebEngine bootstrap (ADR-0001 §4.7) ──────────────────────────
# Chromium GPU init deadlocks under an admin token, so the tier resolver
# forces software raster whenever the GUI is elevated (legacy inproc mode)
# and picks hardware raster / SwiftShader / CPU raster under split mode
# based on DUPEZ_MAP_RENDERER and a best-effort GPU probe. This must run
# BEFORE any PyQt6 import — Qt reads the Chromium flags exactly once.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

# ── Read persisted map_renderer setting early ──────────────────────
# The user can set "gpu" / "swiftshader" / "software" in Settings →
# Interface → Map Renderer. We read it from the JSON file directly
# (no AppState import, no PyQt6 import) and inject it into the env
# var that renderer_tier.py consumes. "auto" means don't override.
if "DUPEZ_MAP_RENDERER" not in os.environ:
    try:
        import json as _json
        _settings_paths = [
            os.path.join(_root, "app", "config", "settings.json"),
        ]
        # Frozen exe: look relative to the exe dir as well
        if getattr(sys, "frozen", False):
            _settings_paths.insert(0, os.path.join(
                os.path.dirname(sys.executable), "app", "config", "settings.json"))
        for _sp in _settings_paths:
            if os.path.isfile(_sp):
                with open(_sp, "r", encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
                _mr = _cfg.get("map_renderer", "auto")
                if _mr and _mr != "auto":
                    os.environ["DUPEZ_MAP_RENDERER"] = _mr
                    print(f"[dupez] map_renderer from settings: {_mr}", file=sys.stderr)
                break
    except Exception as _e:
        print(f"[dupez] early settings read failed (non-fatal): {_e}", file=sys.stderr)

try:
    from app.gui.map_host.renderer_tier import apply_chromium_flags
    apply_chromium_flags()
except Exception as _tier_err:
    # Fallback to the conservative pre-ADR-0001 baseline (CPU raster).
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--no-sandbox --disable-gpu --disable-gpu-compositing",
    )
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ["DUPEZ_MAP_RENDERER_TIER"] = "tier3_cpu"
    print(f"[dupez] renderer_tier fallback: {_tier_err}", file=sys.stderr)

# NOTE: we previously tried QT_SCALE_FACTOR=1 to kill hi-DPI pixel
# doubling in the WebEngine, but it also shrunk the native Qt widgets
# to an unusable size on high-DPI displays. Hi-DPI is now killed only
# at the web page level (via the devicePixelRatio override in
# app/gui/dayz_map_gui_new.py) so the rest of the app keeps its
# normal scaling.

from app.main import main

if __name__ == "__main__":
    main()
