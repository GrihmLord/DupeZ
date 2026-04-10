#!/usr/bin/env python3
"""
Voice Control — voice-activated disruption commands for DupeZ.

Architecture:
  1. Audio capture via sounddevice (16 kHz, mono, float32)
  2. Speech-to-text via OpenAI Whisper (local, offline — "tiny" or "base" model)
  3. Text routed through LLMAdvisor.ask() to produce disruption configs

Two modes:
  - **Toggle mode** (primary): Click LISTEN to start continuous listening.
    Engine captures audio in chunks, detects speech via energy threshold,
    and transcribes automatically. Say "stop listening" to deactivate.
  - **Push-to-talk** (legacy): Hold button to record, release to transcribe.

Dependencies:
  - sounddevice>=0.4.6
  - openai-whisper>=20231117  (the LOCAL package, not the API)
  - numpy (already in requirements)
  - ffmpeg system binary (required by whisper for audio decoding)

The module is fully optional — DupeZ runs fine without it.  All imports
are lazy so missing packages only surface when voice is actually activated.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

import numpy as np
from dataclasses import dataclass

from app.logs.logger import log_info, log_error

__all__ = [
    "VoiceConfig",
    "VoiceEngine",
    "VoiceController",
    "is_voice_available",
    "get_missing_packages",
]


# ── Lazy dependency resolution ────────────────────────────────────────
# Defer the actual import + log until first use so that importing this
# module has zero side effects (no I/O, no log output at import time).

_voice_deps_resolved: bool = False
SOUNDDEVICE: Any = None
WHISPER: Any = None
VOICE_AVAILABLE: bool = False


def _try_import(name: str) -> Any:
    """Import *name* or return ``None`` if unavailable.

    Catches ``Exception`` (not just ``ImportError``) because optional deps
    like ``whisper`` pull in ``torch``, which on Windows raises
    ``OSError [WinError 1114]`` (DLL init failed) when its CUDA/C++
    runtime is broken. That must not crash DupeZ — voice is optional.
    """
    try:
        return __import__(name)
    except Exception as exc:  # noqa: BLE001 — deliberately broad
        log_info(f"VoiceControl: optional import '{name}' failed ({type(exc).__name__}: {exc})")
        return None


def _resolve_voice_deps() -> None:
    """Resolve optional voice dependencies on first use."""
    global _voice_deps_resolved, SOUNDDEVICE, WHISPER, VOICE_AVAILABLE
    if _voice_deps_resolved:
        return
    _voice_deps_resolved = True

    SOUNDDEVICE = _try_import("sounddevice")
    WHISPER = _try_import("whisper")
    VOICE_AVAILABLE = SOUNDDEVICE is not None and WHISPER is not None

    if not VOICE_AVAILABLE:
        missing = []
        if SOUNDDEVICE is None:
            missing.append("sounddevice")
        if WHISPER is None:
            missing.append("openai-whisper")
        log_info(f"VoiceControl: disabled — missing packages: {', '.join(missing)}")

# Configuration
@dataclass
class VoiceConfig:
    """All tunables for voice capture + transcription."""
    # Audio capture
    sample_rate: int = 16000          # Whisper expects 16 kHz
    channels: int = 1                 # mono
    dtype: str = "float32"            # Whisper expects float32
    max_record_seconds: float = 10.0  # safety cap per utterance
    input_device: Optional[int] = None  # None = system default mic

    # Whisper model
    model_name: str = "tiny"          # tiny | base | small | medium | large
    language: str = "en"              # force English for speed
    fp16: bool = False                # True if CUDA available

    # Behaviour
    min_audio_length: float = 0.3     # ignore clips shorter than this (seconds)
    silence_threshold: float = 0.01   # RMS below this = silence, skip transcription
    cooldown: float = 1.0             # seconds between activations

    # Continuous listening (toggle mode)
    chunk_duration: float = 3.0       # seconds per analysis chunk
    speech_energy_threshold: float = 0.015  # RMS above this = speech detected
    silence_timeout: float = 1.5      # seconds of silence to end an utterance
    max_continuous_seconds: float = 15.0  # max single utterance in continuous mode

# Voice Engine
class VoiceEngine:
    """Captures audio, transcribes it, and fires a callback with the text.

    Supports two modes:
      - Push-to-talk: start_recording() on press, stop_recording() on release.
      - Continuous listening: start_continuous() to begin, stop_continuous() to end.
        Engine auto-detects speech boundaries via energy threshold.

    Usage:
        engine = VoiceEngine(on_text=handle_transcription)
        engine.load_model()
        engine.start_continuous()  # or start_recording() for PTT
    """

    def __init__(self, on_text: Callable[[str], None] = None,
                 on_status: Callable[[str], None] = None,
                 config: VoiceConfig = None) -> None:
        self.config = config or VoiceConfig()
        self._on_text = on_text        # called with transcribed string
        self._on_status = on_status    # called with status messages for UI

        self._model = None             # whisper model (lazy loaded)
        self._model_loading = False
        self._recording = False
        self._audio_buffer = []        # list of numpy chunks during recording
        self._record_stream = None
        self._lock = threading.Lock()
        self._last_trigger = 0.0

        # Continuous listening state
        self._continuous = False
        self._continuous_event = threading.Event()  # thread-safe check for audio callback
        self._continuous_stream = None
        self._continuous_buffer = []   # accumulates audio during speech
        self._speech_active = False    # True when speech energy detected
        self._silence_start = 0.0      # timestamp when silence began
        self._utterance_start = 0.0    # timestamp when speech began
        self._transcribing = False     # True while a transcription is in progress

    # Model management
    def load_model(self, model_name: str = None) -> bool:
        """Load the Whisper model. Blocks on first call (downloads weights).
        Call from a background thread if you want non-blocking init."""
        _resolve_voice_deps()
        if not VOICE_AVAILABLE:
            log_error("VoiceEngine: cannot load model — dependencies missing")
            return False

        if self._model is not None:
            return True

        if self._model_loading:
            return False

        self._model_loading = True
        name = model_name or self.config.model_name

        try:
            self._emit_status(f"Loading Whisper '{name}' model...")
            log_info(f"VoiceEngine: loading whisper model '{name}'")
            self._model = WHISPER.load_model(name)
            log_info(f"VoiceEngine: model '{name}' loaded successfully")
            self._emit_status(f"Voice ready (model: {name})")
            return True
        except Exception as e:
            log_error(f"VoiceEngine: failed to load model '{name}': {e}")
            self._emit_status(f"Voice model load failed: {e}")
            return False
        finally:
            self._model_loading = False

    def load_model_async(self, model_name: str = None,
                         callback: Callable[[bool], None] = None) -> None:
        """Load model in background thread."""
        def _run():
            ok = self.load_model(model_name)
            if callback:
                callback(ok)
        t = threading.Thread(target=_run, daemon=True, name="VoiceModelLoader")
        t.start()
        return t

    def is_ready(self) -> Any:
        _resolve_voice_deps()
        return VOICE_AVAILABLE and self._model is not None

    # Audio capture — push-to-talk
    def start_recording(self) -> bool:
        """Begin capturing audio from the microphone.
        Call this on hotkey PRESS."""
        if not self.is_ready():
            self._emit_status("Voice not ready — model not loaded")
            return False

        with self._lock:
            if self._recording:
                return False  # already recording

            # Cooldown check
            now = time.time()
            if now - self._last_trigger < self.config.cooldown:
                return False

            self._recording = True
            self._audio_buffer = []

        self._emit_status("Listening...")
        log_info("VoiceEngine: recording started")

        # Start an input stream with callback
        try:
            self._record_stream = SOUNDDEVICE.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                device=self.config.input_device,
                callback=self._audio_callback,
            )
            self._record_stream.start()
            return True
        except Exception as e:
            log_error(f"VoiceEngine: failed to start recording: {e}")
            self._emit_status(f"Mic error: {e}")
            with self._lock:
                self._recording = False
            return False

    def stop_recording(self) -> None:
        """Stop capturing and transcribe the audio.
        Call this on hotkey RELEASE.  Transcription runs in a background thread."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._last_trigger = time.time()

        # Stop the stream
        if self._record_stream is not None:
            try:
                self._record_stream.stop()
                self._record_stream.close()
            except Exception as e:
                log_error(f"VoiceEngine: error stopping stream: {e}")
            self._record_stream = None

        # Grab the captured audio
        with self._lock:
            if not self._audio_buffer:
                self._emit_status("No audio captured")
                return
            audio = np.concatenate(self._audio_buffer, axis=0)
            self._audio_buffer = []

        # Validate audio length
        duration = len(audio) / self.config.sample_rate
        if duration < self.config.min_audio_length:
            log_info(f"VoiceEngine: audio too short ({duration:.2f}s), skipping")
            self._emit_status("Too short — try again")
            return

        rms = np.sqrt(np.mean(audio ** 2))
        if rms < self.config.silence_threshold:
            log_info(f"VoiceEngine: audio is silence (RMS={rms:.4f}), skipping")
            self._emit_status("No speech detected")
            return

        # Cap at max duration
        max_samples = int(self.config.max_record_seconds * self.config.sample_rate)
        if len(audio) > max_samples:
            audio = audio[:max_samples]

        log_info(f"VoiceEngine: captured {duration:.1f}s audio (RMS={rms:.4f})")
        self._emit_status("Transcribing...")

        # Transcribe in background
        t = threading.Thread(target=self._transcribe, args=(audio,),
                             daemon=True, name="VoiceTranscribe")
        t.start()

    def is_recording(self): return self._recording

    # Continuous listening (toggle mode)
    def start_continuous(self) -> bool:
        """Start continuous listening — auto-detects speech and transcribes.
        Returns True if started successfully."""
        if not self.is_ready():
            self._emit_status("Voice not ready — model not loaded")
            return False

        with self._lock:
            if self._continuous:
                return True  # already running
            self._continuous = True
            self._continuous_event.set()
            self._speech_active = False
            self._continuous_buffer = []
            self._transcribing = False

        self._emit_status("Listening...")
        log_info("VoiceEngine: continuous listening started")

        try:
            # Use a blocksize that gives us ~100ms chunks for responsive detection
            blocksize = int(self.config.sample_rate * 0.1)
            self._continuous_stream = SOUNDDEVICE.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                device=self.config.input_device,
                callback=self._continuous_callback,
                blocksize=blocksize,
            )
            self._continuous_stream.start()
            return True
        except Exception as e:
            log_error(f"VoiceEngine: failed to start continuous listening: {e}")
            self._emit_status(f"Mic error: {e}")
            with self._lock:
                self._continuous = False
                self._continuous_event.clear()
            return False

    def stop_continuous(self) -> None:
        """Stop continuous listening."""
        with self._lock:
            if not self._continuous:
                return
            self._continuous = False
            self._continuous_event.clear()

        if self._continuous_stream is not None:
            try:
                self._continuous_stream.stop()
                self._continuous_stream.close()
            except Exception as e:
                log_error(f"VoiceEngine: error stopping continuous stream: {e}")
            self._continuous_stream = None

        # If there's pending speech, transcribe it
        with self._lock:
            if self._continuous_buffer and self._speech_active:
                self._flush_and_transcribe()
            else:
                self._continuous_buffer = []
                self._speech_active = False

        log_info("VoiceEngine: continuous listening stopped")
        self._emit_status("Voice off")

    def is_continuous(self): return self._continuous

    def _flush_and_transcribe(self, min_duration: bool = True) -> None:
        """Concatenate buffer, reset speech state, and spawn transcription thread.
        Must be called while holding self._lock."""
        audio = np.concatenate(self._continuous_buffer, axis=0)
        self._continuous_buffer = []
        self._speech_active = False
        self._silence_start = 0.0
        duration = len(audio) / self.config.sample_rate
        if self._transcribing or (min_duration and duration < self.config.min_audio_length):
            return
        self._transcribing = True
        if min_duration:
            log_info(f"VoiceEngine: utterance captured ({duration:.1f}s)")
        threading.Thread(target=self._transcribe_continuous,
                         args=(audio,), daemon=True,
                         name="VoiceTranscribeCont").start()

    def _continuous_callback(self, indata, frames, time_info, status) -> None:
        """Sounddevice callback for continuous mode — detects speech boundaries."""
        if status:
            log_error(f"VoiceEngine: continuous callback status: {status}")
        if not self._continuous_event.is_set():
            return

        chunk = indata.copy()
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        is_speech = rms >= self.config.speech_energy_threshold
        now = time.time()

        with self._lock:
            if is_speech:
                if not self._speech_active:
                    self._speech_active = True
                    self._utterance_start = now
                    self._continuous_buffer = []
                    log_info(f"VoiceEngine: speech detected (RMS={rms:.4f})")

                self._continuous_buffer.append(chunk)
                self._silence_start = 0.0

                # Safety cap — don't record forever
                if now - self._utterance_start > self.config.max_continuous_seconds:
                    self._flush_and_transcribe(min_duration=False)
            else:
                if self._speech_active:
                    self._continuous_buffer.append(chunk)
                    if self._silence_start == 0.0:
                        self._silence_start = now
                    elif now - self._silence_start >= self.config.silence_timeout:
                        self._flush_and_transcribe()

    def _transcribe_continuous(self, audio: np.ndarray) -> None:
        """Transcribe audio from continuous mode, then reset for next utterance."""
        try:
            self._emit_status("Processing...")
            self._transcribe(audio)
        finally:
            with self._lock:
                self._transcribing = False
            if self._continuous:
                self._emit_status("Listening...")

    # Audio input devices
    @staticmethod
    def list_input_devices() -> list:
        """Return list of available audio input devices."""
        _resolve_voice_deps()
        if not SOUNDDEVICE:
            return []
        devices = []
        for i, dev in enumerate(SOUNDDEVICE.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                })
        return devices

    def set_input_device(self, device_index: Optional[int]) -> None:
        """Set the input device by index. None = system default."""
        _resolve_voice_deps()
        self.config.input_device = device_index
        name = "default"
        if device_index is not None and SOUNDDEVICE:
            try:
                info = SOUNDDEVICE.query_devices(device_index)
                name = info.get("name", str(device_index))
            except Exception:
                name = str(device_index)
        log_info(f"VoiceEngine: input device set to {name}")

    # Internal
    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """Called by sounddevice InputStream for each audio chunk."""
        if status:
            log_error(f"VoiceEngine: audio callback status: {status}")
        if self._recording:
            # indata is (frames, channels) — copy to avoid overwrite
            with self._lock:
                self._audio_buffer.append(indata.copy())

    def _transcribe(self, audio: np.ndarray) -> None:
        """Run Whisper transcription on captured audio (background thread)."""
        try:
            # Whisper expects 1D float32 array at 16 kHz
            if audio.ndim > 1:
                audio = audio.squeeze()  # (N, 1) → (N,)
            audio = audio.astype(np.float32)

            result = self._model.transcribe(
                audio,
                language=self.config.language,
                fp16=self.config.fp16,
            )

            text = result.get("text", "").strip()
            if not text:
                self._emit_status("No speech recognized")
                log_info("VoiceEngine: transcription returned empty text")
                return

            log_info(f"VoiceEngine: transcribed: '{text}'")
            self._emit_status(f"Heard: \"{text}\"")

            # Fire callback
            if self._on_text:
                self._on_text(text)

        except Exception as e:
            log_error(f"VoiceEngine: transcription error: {e}")
            self._emit_status(f"Transcription failed: {e}")

    def _emit_status(self, msg: str) -> None:
        """Send status message to UI callback."""
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

# Voice Controller — ties VoiceEngine + LLMAdvisor + HotkeyManager together
class VoiceController:
    """High-level controller that wires voice input to disruption commands.

    Two interaction modes:
      - **Toggle (primary)**: Call toggle_listening() to start/stop continuous
        listening. Engine auto-detects speech and transcribes. Say "stop listening"
        or "voice off" to deactivate via voice command.
      - **Push-to-talk (legacy)**: Hold button to record, release to transcribe.

    Usage:
        vc = VoiceController(
            advisor=LLMAdvisor(),
            on_command=lambda cfg: print("Apply:", cfg),
            on_status=lambda msg: print(msg),
        )
        vc.initialize()  # loads model in background
        vc.toggle_listening()  # start continuous listening
    """

    # Voice commands that deactivate the listener
    STOP_LISTENING_PHRASES = frozenset({
        "stop listening", "voice off", "stop voice", "disable voice",
        "turn off voice", "listening off", "voice stop", "mute",
    })

    # Voice commands that stop disruption
    STOP_DISRUPTION_PHRASES = frozenset({
        "stop", "off", "disable", "halt", "cancel",
        "stop disruption", "stop all", "kill it",
    })

    # Voice commands that start disruption
    START_DISRUPTION_PHRASES = frozenset({
        "start", "on", "enable", "go", "begin",
        "start disruption", "resume",
    })

    def __init__(self, advisor=None, on_command: Callable[[dict], None] = None,
                 on_status: Callable[[str], None] = None,
                 on_listening_changed: Callable[[bool], None] = None,
                 config: VoiceConfig = None) -> None:
        self._advisor = advisor
        self._on_command = on_command
        self._on_status = on_status
        self._on_listening_changed = on_listening_changed  # GUI toggle sync
        self._config = config or VoiceConfig()

        self._engine = VoiceEngine(
            on_text=self._handle_transcription,
            on_status=on_status,
            config=self._config,
        )
        self._enabled = False
        self._hotkey_registered = False

    def initialize(self, callback: Callable[[bool], None] = None) -> None:
        """Load the Whisper model in background. Call once at startup."""
        _resolve_voice_deps()
        if not VOICE_AVAILABLE:
            self._emit_status("Voice control unavailable — install sounddevice + openai-whisper")
            if callback:
                callback(False)
            return

        def _on_loaded(ok):
            self._enabled = ok
            if callback:
                callback(ok)

        self._engine.load_model_async(callback=_on_loaded)

    # Toggle listening (primary mode)
    def toggle_listening(self) -> bool:
        """Toggle continuous listening on/off. Returns new state."""
        if not self._enabled:
            return False

        if self._engine.is_continuous():
            self.stop_listening()
            return False
        else:
            return self.start_listening()

    def _notify_listening(self, state: bool) -> None:
        if self._on_listening_changed:
            try:
                self._on_listening_changed(state)
            except Exception:
                pass

    def start_listening(self) -> bool:
        """Start continuous listening mode."""
        if not self._enabled:
            return False
        ok = self._engine.start_continuous()
        if ok:
            self._notify_listening(True)
        return ok

    def stop_listening(self) -> None:
        """Stop continuous listening mode."""
        self._engine.stop_continuous()
        self._notify_listening(False)

    def push_to_talk_press(self) -> None:
        """Call on hotkey press — starts recording."""
        if not self._enabled:
            return
        self._engine.start_recording()

    def push_to_talk_release(self) -> None:
        """Call on hotkey release — stops recording, triggers transcription."""
        if not self._enabled:
            return
        self._engine.stop_recording()

    # State queries
    def is_available(self) -> bool:
        """True if voice control is fully initialized."""
        return VOICE_AVAILABLE and self._enabled and self._engine.is_ready()

    def is_recording(self) -> bool:
        return self._engine.is_recording()

    def set_input_device(self, device_index: Optional[int]) -> None:
        """Change microphone."""
        self._engine.set_input_device(device_index)

    def list_input_devices(self) -> list:
        return VoiceEngine.list_input_devices()

    def enable(self) -> None:
        """Enable voice control."""
        if self._engine.is_ready():
            self._enabled = True
            log_info("VoiceController: enabled")

    def disable(self) -> None:
        """Disable voice control and stop all audio."""
        self._enabled = False
        if self._engine.is_recording():
            self._engine.stop_recording()
        if self._engine.is_continuous():
            self._engine.stop_continuous()
        log_info("VoiceController: disabled")

    # Hotkey integration
    def _handle_transcription(self, text: str) -> None:
        """Route transcribed text through LLM advisor to get a disruption config."""
        log_info(f"VoiceController: processing command: '{text}'")

        text_lower = text.lower().strip()

        # Strip leading/trailing punctuation that Whisper sometimes adds
        text_clean = text_lower.strip(' .,!?')

        # 1. Check for "stop listening" — deactivate the voice engine itself
        if text_clean in self.STOP_LISTENING_PHRASES:
            self._emit_status("Voice command: STOP LISTENING")
            log_info("VoiceController: stop-listening command received")
            self.stop_listening()
            return

        # 2. Check for disruption stop commands
        if text_clean in self.STOP_DISRUPTION_PHRASES:
            self._emit_status("Voice command: STOP")
            if self._on_command:
                self._on_command({"action": "stop"})
            return

        # 3. Check for disruption start commands
        if text_clean in self.START_DISRUPTION_PHRASES:
            self._emit_status("Voice command: START")
            if self._on_command:
                self._on_command({"action": "start"})
            return

        # 4. Route through LLM advisor for disruption config
        if self._advisor is None:
            log_error("VoiceController: no LLM advisor configured")
            self._emit_status("No advisor — voice text ignored")
            return

        self._emit_status(f"Processing: \"{text}\"")

        def _on_result(config):
            if config:
                log_info(f"VoiceController: advisor returned: {config.get('name', 'unnamed')}")
                self._emit_status(f"Applying: {config.get('name', 'voice command')}")
                if self._on_command:
                    self._on_command(config)
            else:
                log_error("VoiceController: advisor returned None")
                self._emit_status("Could not interpret voice command")

        self._advisor.ask_async(text, callback=_on_result)

    def _emit_status(self, msg: str) -> None:
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

# Module-level convenience
def is_voice_available() -> bool:
    """Check if voice control dependencies are installed."""
    _resolve_voice_deps()
    return VOICE_AVAILABLE

def get_missing_packages() -> list:
    """Return list of missing packages needed for voice control."""
    _resolve_voice_deps()
    missing = []
    if SOUNDDEVICE is None:
        missing.append("sounddevice")
    if WHISPER is None:
        missing.append("openai-whisper")
    return missing

