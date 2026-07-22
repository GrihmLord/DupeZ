# app/gui/panels — Extracted panel widgets from ClumsyControlView
from .stats_panel import StatsPanel
from .voice_panel import VoicePanel
from .gpc_panel import GPCPanel
from .smart_mode_panel import SmartModePanel
from .ai_panel import AIPanel, SMART_MODE_OFF, SMART_MODE_LEARN, SMART_MODE_ASSIST
from .lan_cut_panel import LanCutPanel

# Install after every participating class is imported. This removes the legacy
# bidirectional-only lock and applies the exact bundled-Clumsy UI limits before
# any panel instance is constructed in either frozen architecture.
from .clumsy_event_ui_policy import install_clumsy_event_ui_policy

install_clumsy_event_ui_policy()
