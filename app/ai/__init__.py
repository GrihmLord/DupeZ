# app/ai/ — Smart Disruption Engine
#
# Intelligent auto-tuning and voice control:
#   1. NetworkProfiler  — characterizes target connections in real-time
#   2. SmartEngine       — maps network profiles to optimal disruption params
#   3. LLMAdvisor        — optional natural-language tuning via Ollama/Mistral
#   4. SessionTracker    — logs outcomes to improve future recommendations
#   5. VoiceController   — push-to-talk voice commands via Whisper STT

from app.ai.network_profiler import NetworkProfile, NetworkProfiler
from app.ai.smart_engine import SmartDisruptionEngine
from app.ai.llm_advisor import LLMAdvisor
from app.ai.session_tracker import SessionTracker

# Voice control is optional — requires sounddevice + openai-whisper
try:
    from app.ai.voice_control import VoiceController, VoiceConfig, is_voice_available
except ImportError:
    VoiceController = None
    VoiceConfig = None
    is_voice_available = lambda: False

__all__ = [
    "NetworkProfile",
    "NetworkProfiler",
    "SmartDisruptionEngine",
    "LLMAdvisor",
    "SessionTracker",
    "VoiceController",
    "VoiceConfig",
    "is_voice_available",
]

