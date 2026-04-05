# Changelog

All notable changes to DupeZ are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## v3.5.0 — 2026-04-03 (Live Stats + Distribution Polish)

Quality-of-life release: real-time packet stats dashboard, PyInstaller packaging improvements, and version bump.

### Added
- **Live Stats Dashboard** in Clumsy Control view — real-time packet counters (processed, dropped, passed, inbound, outbound) with auto-refresh every 1.5s. Includes drop rate progress bar, active engine count, and per-device breakdown table with method labels.
- **`NativeDisruptEngine.get_stats()`** — returns live packet counters dict from each engine instance.
- **`ClumsyNetworkDisruptor.get_all_engine_stats()`** — aggregates stats across all active disruption engines with per-device breakdown.
- **`AppController.get_engine_stats()`** — exposes aggregated engine stats to the GUI layer.
- **`_format_count()` helper** — human-readable packet counts (1.2K, 3.4M).

### Changed
- **`dupez.spec`** — Added hidden imports for voice (`sounddevice`, `whisper`) and GPC (`serial`, `serial.tools`, `serial.tools.list_ports`) so PyInstaller bundles optional dependencies correctly.
- **Version bump** — 3.3.0 → 3.5.0 across `main.py`, `dashboard.py`, `network_tools.py`, AppUserModelID.

---

## v3.4.0 — 2026-04-02 (God Mode + Voice + GPC)

Major feature release. Directional lag engine (God Mode), push-to-talk voice control via Whisper, and native CronusZEN/MAX GPC script integration.

### Added — God Mode
- **`native_divert_engine.py` → `GodModeModule`** — Directional lag engine using WinDivert packet direction detection. Delays inbound packets (server → target) while passing outbound untouched. Target freezes on other players' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound packet drop percentage.
- **Direction-aware filtering** — All disruption modules now implement `matches_direction()`. WinDivert `Outbound` bit (position 17 in addr bitfield) used for per-packet direction classification.
- **`NETWORK_FORWARD` layer support** — Enables God Mode on ICS/hotspot setups where the machine is the gateway.
- **God Mode preset** — 2000ms inbound lag, outbound untouched. One-click activation.
- **God Mode Aggressive preset** — God Mode + 30% inbound drop for harder freeze effect.
- **Smart Engine godmode strategy** — 6th goal strategy in AI auto-tune. Connection-type adjustments (hotspot reduces lag by 20%).
- **LLM Advisor godmode fallback** — Keyword-based God Mode interpretation with intensity scaling and hotspot detection when no LLM is available.

### Added — Voice Control
- **`app/ai/voice_control.py`** — Complete push-to-talk voice command module (~480 lines):
  - `VoiceEngine` — Audio capture via `sounddevice` InputStream callback (16kHz, mono, float32). Silence detection (RMS threshold), minimum length validation, max duration cap.
  - `VoiceController` — Wires VoiceEngine → OpenAI Whisper STT → LLMAdvisor → disruption config. Thread-safe callback marshaling to Qt main thread.
  - `VoiceConfig` dataclass — sample rate, channels, dtype, model name (tiny/base/small), language, silence threshold, min/max duration.
  - Lazy dependency checks — DupeZ runs without `sounddevice` or `openai-whisper` installed.
  - Simple voice commands: "stop"/"off" → stop disruption, "start"/"on" → start.
  - Input device listing and selection.
- **Voice Control UI panel** in Clumsy Control — INIT button, PUSH TO TALK button, model selector (tiny/base/small), mic selector, status label.

### Added — GPC / CronusZEN Support
- **`app/gpc/gpc_parser.py`** — GPC script tokenizer + recursive descent parser (~350 lines). Parses preprocessor directives, variables, main blocks, combo blocks, and functions into structured `GPCScript` objects.
- **`app/gpc/gpc_generator.py`** — GPC script generator (~350 lines). 4 built-in templates: DayZ Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil. Generates complete .gpc source synced with DupeZ disruption timing. Atomic file export.
- **`app/gpc/device_bridge.py`** — Cronus USB device detection + Zen Studio integration (~250 lines). Scans for VID 0x2508 via pyserial (WMI fallback on Windows). Background `DeviceMonitor` thread for connect/disconnect events. Auto-discovers Zen Studio library folder for direct .gpc export.
- **`app/gpc/__init__.py`** — Package init with full public API exports.
- **GPC UI panel** in Clumsy Control — Device status, template selector, description label, GENERATE/EXPORT/SYNC TIMING buttons, script preview.

### Fixed
- **100% drop fidelity** — Drop module now uses `continue` (discard packet) instead of re-injecting, guaranteeing true 100% drop when configured.
- **`llm_advisor.py`** — Missing `_fallback_godmode()` method caused `AttributeError` when godmode keywords matched without LLM. Added complete implementation with intensity scaling and hotspot detection.
- **`llm_advisor.py`** — False positive on bare "god" keyword (matched "good"). Removed; kept specific patterns ("god mode", "godmode", "freeze them", etc.).
- **`smart_engine.py`** — Goal key mismatch: GUI sent "god mode" (with space) but strategy map keyed on "godmode". Added `goal.replace(" ", "")` normalization.
- **`smart_engine.py`** — Hotspot adjustment never touched `godmode_lag_ms`. Added `*= 0.8` reduction in hotspot branch.
- **`clumsy_control.py`** — Voice command callback ran on background thread, modifying Qt widgets unsafely. Split into thread-safe marshal (`QMetaObject.invokeMethod`) + main-thread `@pyqtSlot` handler.
- **`clumsy_control.py`** — `_voice_controller` AttributeError when voice dependencies unavailable. Added `None` initialization in `__init__`.
- **`voice_control.py`** — Audio buffer appended from sounddevice callback thread without lock. Added `with self._lock:` guard on both append and read paths.
- **`llm_advisor.py`** — Removed unused `import os`.
- **`app/ai/__init__.py`** — Added voice control exports with `ImportError` fallback.

### Changed
- `smart_engine.py` — Goal strategies expanded from 5 to 6 (added godmode).
- `clumsy_control.py` — Smart Mode goal selector includes "God Mode". Voice and GPC panels added to control layout.
- `requirements.txt` — Added optional dependencies: `sounddevice>=0.4.6`, `openai-whisper>=20231117`, `pyserial>=3.5`.

---

## v3.3.1 — 2026-04-02 (Hardening Pass)

Full codebase audit — 11 fixes across 11 files targeting thread safety, crash resilience, frozen-exe compatibility, and correctness.

### Fixed — Critical
- **`blocker.py`** — Missing `log_warning` import crashed `clear_all_dupez_blocks()` at runtime.
- **`blocker.py`** — `is_active()` method shadowed `self.is_active` bool attribute; renamed to `get_active()`.

### Fixed — High
- **`data_persistence.py`** — `save_data()` used bare `json.dump`; crash mid-write corrupted file. Now uses atomic tmp → fsync → replace pattern.
- **`smart_engine.py`** — Hardcoded `"app/data/session_history.json"` broke in PyInstaller builds. Now uses `_resolve_data_directory()`.
- **`logger.py`** — Relative `"logs"` directory resolved to `System32\logs` in frozen exe. Added `_resolve_log_directory()` with `sys.frozen` detection.

### Fixed — Medium
- **`state.py`** — `_observers` list had no thread protection. Added `threading.Lock` to `add_observer()` and `notify_observers()`.
- **`controller.py`** — `start_auto_scan()` never reset `stop_scanning` flag, preventing auto-scan restart after manual stop.
- **`network_profiler.py`** — `ip.startswith("172.2")` incorrectly matched public IPs 172.200-255.x.x. Added proper RFC1918 172.16.0.0/12 range check.
- **`session_tracker.py`** — `_active_sessions` dict mutations in `start_session()`/`end_session()` were unprotected. Now guarded by `self._lock`.

### Fixed — Low
- **`native_divert_engine.py`** — Out-of-Order module had unbounded packet buffer. Added `MAX_BUFFER=64` safety valve.
- **`helpers.py`** — 350-entry duplicate emoji replac