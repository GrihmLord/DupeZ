#!/usr/bin/env python3
"""
GPC Script Generator — create CronusZEN/MAX scripts synced with DupeZ.

Generates .gpc scripts that complement DupeZ network disruption:
  - Auto-dupe button sequences timed to lag windows
  - Rapid-fire / turbo macros synced with packet manipulation
  - Game-specific combo scripts (DayZ inventory dupe, etc.)
  - Hotkey-triggered preset switching

Generated scripts are exported as .gpc files ready for Zen Studio import.

Controller button constants follow XB1 naming (CronusZEN default):
  XB1_A=4, XB1_B=5, XB1_X=6, XB1_Y=7,
  XB1_LB=8, XB1_RB=9, XB1_LT=10, XB1_RT=11,
  XB1_UP=13, XB1_DOWN=14, XB1_LEFT=15, XB1_RIGHT=16,
  XB1_LS=1, XB1_RS=2, XB1_VIEW=3, XB1_MENU=12,
  XB1_LX=17, XB1_LY=18, XB1_RX=19, XB1_RY=20
"""

import time
import os
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from app.logs.logger import log_info, log_error


# ---------------------------------------------------------------------------
# Controller button map
# ---------------------------------------------------------------------------
BUTTON_MAP = {
    "A": "XB1_A", "B": "XB1_B", "X": "XB1_X", "Y": "XB1_Y",
    "LB": "XB1_LB", "RB": "XB1_RB", "LT": "XB1_LT", "RT": "XB1_RT",
    "UP": "XB1_UP", "DOWN": "XB1_DOWN", "LEFT": "XB1_LEFT", "RIGHT": "XB1_RIGHT",
    "LS": "XB1_LS", "RS": "XB1_RS", "VIEW": "XB1_VIEW", "MENU": "XB1_MENU",
    "CROSS": "PS4_CROSS", "CIRCLE": "PS4_CIRCLE",
    "SQUARE": "PS4_SQUARE", "TRIANGLE": "PS4_TRIANGLE",
    "L1": "PS4_L1", "R1": "PS4_R1", "L2": "PS4_L2", "R2": "PS4_R2",
}

# PS4 ↔ XB1 mapping for cross-platform
PS4_TO_XB1 = {
    "PS4_CROSS": "XB1_A", "PS4_CIRCLE": "XB1_B",
    "PS4_SQUARE": "XB1_X", "PS4_TRIANGLE": "XB1_Y",
    "PS4_L1": "XB1_LB", "PS4_R1": "XB1_RB",
    "PS4_L2": "XB1_LT", "PS4_R2": "XB1_RT",
}


# ---------------------------------------------------------------------------
# Combo step definition
# ---------------------------------------------------------------------------
@dataclass
class ComboStep:
    """A single action in a combo sequence."""
    button: str            # Button constant (e.g., "XB1_A")
    value: int = 100       # Button value (0-100, 100 = fully pressed)
    hold_ms: int = 50      # How long to hold
    wait_after_ms: int = 50  # Wait after releasing


@dataclass
class ComboSequence:
    """A named sequence of button actions."""
    name: str
    description: str = ""
    steps: List[ComboStep] = field(default_factory=list)
    loop: bool = False     # Repeat combo while trigger held

    @property
    def total_duration_ms(self) -> int:
        return sum(s.hold_ms + s.wait_after_ms for s in self.steps)


# ---------------------------------------------------------------------------
# Script templates
# ---------------------------------------------------------------------------
@dataclass
class GPCTemplate:
    """A complete GPC script template."""
    name: str
    description: str
    game: str = "Universal"
    platform: str = "XB1"      # XB1, PS4, Universal
    trigger_button: str = "XB1_VIEW"  # Button that activates the script
    combos: List[ComboSequence] = field(default_factory=list)
    defines: Dict[str, int] = field(default_factory=dict)
    dupez_sync: bool = True    # Whether script is designed to sync with DupeZ


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------
def _template_dayz_dupe() -> GPCTemplate:
    """DayZ inventory dupe — rapid drop + pick up during lag window."""
    return GPCTemplate(
        name="DayZ Auto Dupe",
        description=(
            "Automated inventory dupe sequence for DayZ. "
            "Rapidly drops and picks up items during DupeZ lag window. "
            "Hold VIEW/SELECT to activate."
        ),
        game="DayZ",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"DROP_HOLD": 80, "PICKUP_HOLD": 60, "CYCLE_WAIT": 100},
        combos=[
            ComboSequence(
                name="dupe_cycle",
                description="Drop → wait → pick up cycle",
                steps=[
                    # Open inventory (Y / Triangle)
                    ComboStep(button="XB1_Y", value=100, hold_ms=60, wait_after_ms=200),
                    # Navigate to item (assumed cursor already on item)
                    # Drop item (A / Cross)
                    ComboStep(button="XB1_A", value=100, hold_ms=80, wait_after_ms=100),
                    # Move cursor to ground
                    ComboStep(button="XB1_RB", value=100, hold_ms=50, wait_after_ms=150),
                    # Pick up item (A / Cross)
                    ComboStep(button="XB1_A", value=100, hold_ms=60, wait_after_ms=100),
                    # Move back to inventory
                    ComboStep(button="XB1_LB", value=100, hold_ms=50, wait_after_ms=100),
                ],
                loop=True,
            ),
        ],
    )


def _template_rapid_fire() -> GPCTemplate:
    """Universal rapid-fire on RT/R2."""
    return GPCTemplate(
        name="Rapid Fire",
        description="Rapid-fire on right trigger. Adjustable rate via FIRE_RATE define.",
        game="Universal",
        platform="Universal",
        trigger_button="XB1_RT",
        defines={"FIRE_RATE": 40, "FIRE_HOLD": 20},
        combos=[
            ComboSequence(
                name="rapid_fire",
                description="Rapid trigger pull",
                steps=[
                    ComboStep(button="XB1_RT", value=100, hold_ms=20, wait_after_ms=20),
                    ComboStep(button="XB1_RT", value=0, hold_ms=0, wait_after_ms=20),
                ],
                loop=True,
            ),
        ],
    )


def _template_godmode_sync() -> GPCTemplate:
    """Script synced with DupeZ God Mode — actions during lag window."""
    return GPCTemplate(
        name="God Mode Actions",
        description=(
            "Execute actions during DupeZ God Mode lag window. "
            "While others are frozen, perform rapid actions that register before unlag."
        ),
        game="Universal",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"ACTION_SPEED": 30, "ACTION_WAIT": 20},
        dupez_sync=True,
        combos=[
            ComboSequence(
                name="burst_actions",
                description="Rapid action burst during lag window",
                steps=[
                    ComboStep(button="XB1_RT", value=100, hold_ms=30, wait_after_ms=20),
                    ComboStep(button="XB1_RT", value=0, hold_ms=0, wait_after_ms=10),
                    ComboStep(button="XB1_RT", value=100, hold_ms=30, wait_after_ms=20),
                    ComboStep(button="XB1_RT", value=0, hold_ms=0, wait_after_ms=10),
                ],
                loop=True,
            ),
        ],
    )


def _template_anti_recoil() -> GPCTemplate:
    """Anti-recoil for shooters."""
    return GPCTemplate(
        name="Anti Recoil",
        description="Automatic recoil compensation while firing. Adjust RECOIL_STRENGTH.",
        game="Universal FPS",
        platform="Universal",
        trigger_button="XB1_RT",
        defines={"RECOIL_STRENGTH": 20, "RECOIL_DELAY": 10},
        combos=[
            ComboSequence(
                name="anti_recoil",
                description="Pull right stick down while firing",
                steps=[
                    # Push right stick Y down (positive = down)
                    ComboStep(button="XB1_RY", value=20, hold_ms=10, wait_after_ms=0),
                ],
                loop=True,
            ),
        ],
    )


# Registry of all built-in templates
TEMPLATES: Dict[str, GPCTemplate] = {}


def _register_templates():
    global TEMPLATES
    for fn in [_template_dayz_dupe, _template_rapid_fire,
               _template_godmode_sync, _template_anti_recoil]:
        t = fn()
        TEMPLATES[t.name] = t


_register_templates()


# ---------------------------------------------------------------------------
# GPC Code Generator
# ---------------------------------------------------------------------------
class GPCGenerator:
    """Generate valid .gpc source code from templates or custom configs."""

    def __init__(self):
        self._indent = "    "

    def generate(self, template: GPCTemplate,
                 disruption_params: Dict = None) -> str:
        """Generate a complete .gpc script from a template.

        Args:
            template: The GPCTemplate to generate from
            disruption_params: Optional DupeZ disruption params to sync timing

        Returns:
            Complete .gpc source code as a string
        """
        if template is None:
            log_error("GPCGenerator.generate: template is None")
            return "// ERROR: No template provided\n"

        if disruption_params is None:
            disruption_params = {}

        lines = []

        # Header comment
        lines.append(f"// ============================================")
        lines.append(f"// DupeZ GPC Script: {template.name}")
        lines.append(f"// Game: {template.game}")
        lines.append(f"// Platform: {template.platform}")
        lines.append(f"// {template.description}")
        lines.append(f"// Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if template.dupez_sync and disruption_params:
            lines.append(f"// Synced with DupeZ disruption config")
        lines.append(f"// ============================================")
        lines.append("")

        # Defines
        for name, value in template.defines.items():
            lines.append(f"define {name} = {value};")

        # Sync defines from disruption params
        if disruption_params and template.dupez_sync:
            lines.append("")
            lines.append("// DupeZ sync timing")
            lag = disruption_params.get("lag_delay",
                  disruption_params.get("godmode_lag_ms", 0))
            if lag:
                lines.append(f"define DUPEZ_LAG_MS = {lag};")
            lines.append(f"define DUPEZ_ACTIVE = 1;")

        lines.append("")

        # State variable
        lines.append("int active = 0;")
        lines.append("")

        # Main block
        lines.append("main {")
        lines.append(f"{self._indent}// Toggle on trigger button press")
        lines.append(f"{self._indent}if (event_press({template.trigger_button})) {{")
        lines.append(f"{self._indent}{self._indent}active = !active;")
        lines.append(f"{self._indent}}}")
        lines.append("")

        # Run combos when active
        for combo_seq in template.combos:
            lines.append(f"{self._indent}// {combo_seq.description}")
            if combo_seq.loop:
                lines.append(f"{self._indent}if (active) {{")
                lines.append(f"{self._indent}{self._indent}combo_run({combo_seq.name});")
                lines.append(f"{self._indent}}}")
            else:
                lines.append(f"{self._indent}if (active && event_press({template.trigger_button})) {{")
                lines.append(f"{self._indent}{self._indent}combo_run({combo_seq.name});")
                lines.append(f"{self._indent}}}")

        lines.append("}")
        lines.append("")

        # Combo blocks
        for combo_seq in template.combos:
            lines.append(f"// {combo_seq.description}")
            lines.append(f"combo {combo_seq.name} {{")
            for step in combo_seq.steps:
                lines.append(f"{self._indent}set_val({step.button}, {step.value});")
                if step.hold_ms > 0:
                    lines.append(f"{self._indent}wait({step.hold_ms});")
                if step.wait_after_ms > 0:
                    # Release the button then wait
                    if step.value != 0:
                        lines.append(f"{self._indent}set_val({step.button}, 0);")
                    lines.append(f"{self._indent}wait({step.wait_after_ms});")
            lines.append("}")
            lines.append("")

        return '\n'.join(lines)

    def generate_from_disruption(self, disruption_config: Dict) -> str:
        """Auto-generate a GPC script based on current DupeZ disruption config.

        Analyzes the active disruption methods and creates appropriate
        controller scripts to complement them.
        """
        methods = disruption_config.get("methods", [])
        params = disruption_config.get("params", {})

        # Pick the best matching template
        if "godmode" in methods:
            template = TEMPLATES.get("God Mode Actions", _template_godmode_sync())
        elif any(m in methods for m in ["lag", "duplicate", "ood"]):
            template = TEMPLATES.get("DayZ Auto Dupe", _template_dayz_dupe())
        else:
            template = TEMPLATES.get("Rapid Fire", _template_rapid_fire())

        return self.generate(template, disruption_params=params)

    def export_to_file(self, source: str, path: str) -> bool:
        """Write generated GPC source to a .gpc file (atomic write)."""
        if not source or not path:
            log_error("GPCGenerator.export_to_file: empty source or path")
            return False

        tmp_path = path + ".tmp"
        try:
            # Ensure parent directory exists
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            # Atomic write: tmp → fsync → replace
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(source)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            log_info(f"GPCGenerator: exported script to {path}")
            return True
        except Exception as e:
            log_error(f"GPCGenerator: failed to export to {path}: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return False


# ---------------------------------------------------------------------------
# Script modifier — adjust timing in existing scripts
# ---------------------------------------------------------------------------
def adjust_combo_timing(script_source: str, multiplier: float) -> str:
    """Scale all wait() values in a GPC script by a multiplier.

    Useful for syncing existing scripts to DupeZ lag settings.
    E.g., multiplier=0.5 halves all delays (faster), 2.0 doubles them.
    """
    import re

    def replace_wait(match):
        original = int(match.group(1))
        adjusted = max(1, int(original * multiplier))
        return f"wait({adjusted})"

    return re.sub(r'wait\(\s*(\d+)\s*\)', replace_wait, script_source)


def get_template_names() -> List[str]:
    """Return names of all built-in templates."""
    return list(TEMPLATES.keys())


def get_template(name: str) -> Optional[GPCTemplate]:
    """Get a built-in template by name."""
    return TEMPLATES.get(name)


def list_templates() -> List[Dict]:
    """Return template metadata for UI display."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "game": t.game,
            "platform": t.platform,
            "dupez_sync": t.dupez_sync,
            "combo_count": len(t.combos),
        }
        for t in TEMPLATES.values()
    ]
