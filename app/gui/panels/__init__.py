# app/gui/panels — Extracted panel widgets from ClumsyControlView
from .stats_panel import StatsPanel
from .voice_panel import VoicePanel
from .gpc_panel import GPCPanel
from .smart_mode_panel import SmartModePanel
from .ai_panel import AIPanel, SMART_MODE_OFF, SMART_MODE_LEARN, SMART_MODE_ASSIST
from .lan_cut_panel import LanCutPanel

# Install after every participating class is imported and before any panel
# instance is constructed. Lifetime safety must be in place before the advanced
# panel's __init__ calls its parameter-adapter hook; the event UI policy then
# applies exact bundled-Clumsy limits and removes the obsolete direction lock.
from .clumsy_advanced_lifetime import install_clumsy_advanced_lifetime
from .clumsy_event_ui_policy import install_clumsy_event_ui_policy

install_clumsy_advanced_lifetime()
install_clumsy_event_ui_policy()
