#!/usr/bin/env python3
"""GPC script generator for controller accessibility workflows.

The built-in templates are intentionally limited to legitimate comfort,
accessibility, and private-diagnostic marker workflows. They are not designed
to automate competitive advantage, game-state manipulation, or network misuse.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.logs.logger import log_error, log_info

__all__ = [
    "BUTTON_MAP",
    "PS4_TO_XB1",
    "ComboStep",
    "ComboSequence",
    "GPCTemplate",
    "GPCGenerator",
    "adjust_combo_timing",
    "list_templates",
    "get_template",
    "get_template_names",
]

BUTTON_MAP = {
    "A": "XB1_A",
    "B": "XB1_B",
    "X": "XB1_X",
    "Y": "XB1_Y",
    "LB": "XB1_LB",
    "RB": "XB1_RB",
    "LT": "XB1_LT",
    "RT": "XB1_RT",
    "UP": "XB1_UP",
    "DOWN": "XB1_DOWN",
    "LEFT": "XB1_LEFT",
    "RIGHT": "XB1_RIGHT",
    "LS": "XB1_LS",
    "RS": "XB1_RS",
    "VIEW": "XB1_VIEW",
    "MENU": "XB1_MENU",
    "CROSS": "PS4_CROSS",
    "CIRCLE": "PS4_CIRCLE",
    "SQUARE": "PS4_SQUARE",
    "TRIANGLE": "PS4_TRIANGLE",
    "L1": "PS4_L1",
    "R1": "PS4_R1",
    "L2": "PS4_L2",
    "R2": "PS4_R2",
}

PS4_TO_XB1 = {
    "PS4_CROSS": "XB1_A",
    "PS4_CIRCLE": "XB1_B",
    "PS4_SQUARE": "XB1_X",
    "PS4_TRIANGLE": "XB1_Y",
    "PS4_L1": "XB1_LB",
    "PS4_R1": "XB1_RB",
    "PS4_L2": "XB1_LT",
    "PS4_R2": "XB1_RT",
}


@dataclass
class ComboStep:
    """A single action in a combo sequence."""

    button: str
    value: int = 100
    hold_ms: int = 50
    wait_after_ms: int = 50


@dataclass
class ComboSequence:
    """A named sequence of button actions."""

    name: str
    description: str = ""
    steps: List[ComboStep] = field(default_factory=list)
    loop: bool = False

    @property
    def total_duration_ms(self) -> int:
        return sum(step.hold_ms + step.wait_after_ms for step in self.steps)


@dataclass
class GPCTemplate:
    """A complete GPC script template."""

    name: str
    description: str
    game: str = "Universal"
    platform: str = "XB1"
    trigger_button: str = "XB1_VIEW"
    combos: List[ComboSequence] = field(default_factory=list)
    defines: Dict[str, int] = field(default_factory=dict)
    dupez_sync: bool = False


def _template_dayz_accessibility() -> GPCTemplate:
    return GPCTemplate(
        name="DayZ Accessibility Helper",
        description=(
            "Slow controller comfort sequence for private/local workflows. "
            "Verify server rules before using automation."
        ),
        game="DayZ",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"MENU_HOLD": 80, "NAV_HOLD": 60, "CYCLE_WAIT": 150},
        combos=[
            ComboSequence(
                name="inventory_comfort_cycle",
                description="Open inventory and move between inventory panes",
                steps=[
                    ComboStep(button="XB1_Y", value=100, hold_ms=60, wait_after_ms=200),
                    ComboStep(button="XB1_RB", value=100, hold_ms=50, wait_after_ms=150),
                    ComboStep(button="XB1_LB", value=100, hold_ms=50, wait_after_ms=100),
                ],
                loop=True,
            )
        ],
    )


def _template_hold_toggle() -> GPCTemplate:
    return GPCTemplate(
        name="Hold Toggle Helper",
        description="Slow hold/toggle helper for accessibility workflows.",
        game="Universal Accessibility",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"HOLD_MS": 250, "REST_MS": 250},
        combos=[
            ComboSequence(
                name="hold_toggle",
                description="Slow repeated hold for accessibility",
                steps=[
                    ComboStep(button="XB1_A", value=100, hold_ms=250, wait_after_ms=250),
                ],
                loop=True,
            )
        ],
    )


def _template_diagnostic_marker() -> GPCTemplate:
    return GPCTemplate(
        name="Diagnostic Marker",
        description=(
            "Local marker button for private-server diagnostics and recordings."
        ),
        game="Universal Diagnostics",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"MARK_HOLD": 100, "MARK_WAIT": 100},
        combos=[
            ComboSequence(
                name="diagnostic_marker",
                description="Short visible input marker",
                steps=[
                    ComboStep(button="XB1_LS", value=100, hold_ms=100, wait_after_ms=100),
                ],
                loop=False,
            )
        ],
    )


def _template_stick_rest() -> GPCTemplate:
    return GPCTemplate(
        name="Stick Rest Helper",
        description="Gentle stick centering helper for accessibility testing.",
        game="Universal Accessibility",
        platform="Universal",
        trigger_button="XB1_VIEW",
        defines={"REST_VALUE": 0, "REST_DELAY": 10},
        combos=[
            ComboSequence(
                name="stick_rest",
                description="Return right stick to neutral",
                steps=[
                    ComboStep(button="XB1_RY", value=0, hold_ms=10, wait_after_ms=0),
                ],
                loop=True,
            )
        ],
    )


TEMPLATES: Dict[str, GPCTemplate] = {}


def _register_templates() -> None:
    global TEMPLATES
    TEMPLATES = {}
    for factory in (
        _template_dayz_accessibility,
        _template_hold_toggle,
        _template_diagnostic_marker,
        _template_stick_rest,
    ):
        template = factory()
        TEMPLATES[template.name] = template


_register_templates()


class GPCGenerator:
    """Generate valid .gpc source code from safe templates."""

    def __init__(self) -> None:
        self._indent = "    "

    def generate(self, template: GPCTemplate, disruption_params: Dict = None) -> str:
        if template is None:
            log_error("GPCGenerator.generate: template is None")
            return "// ERROR: No template provided\n"
        if disruption_params is None:
            disruption_params = {}

        lines = [
            "// ============================================",
            f"// DupeZ GPC Script: {template.name}",
            f"// Game: {template.game}",
            f"// Platform: {template.platform}",
            f"// {template.description}",
            "// Safety: accessibility/private diagnostics only; verify server rules.",
            f"// Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "// ============================================",
            "",
        ]
        for name, value in template.defines.items():
            lines.append(f"define {name} = {value};")
        lines.extend(["", "int active = 0;", "", "main {"])
        lines.append(f"{self._indent}// Toggle on trigger button press")
        lines.append(f"{self._indent}if (event_press({template.trigger_button})) {{")
        lines.append(f"{self._indent}{self._indent}active = !active;")
        lines.append(f"{self._indent}}}")
        lines.append("")

        for combo_seq in template.combos:
            lines.append(f"{self._indent}// {combo_seq.description}")
            if combo_seq.loop:
                lines.append(f"{self._indent}if (active) {{")
                lines.append(f"{self._indent}{self._indent}combo_run({combo_seq.name});")
                lines.append(f"{self._indent}}}")
            else:
                lines.append(
                    f"{self._indent}if (active && event_press({template.trigger_button})) {{"
                )
                lines.append(f"{self._indent}{self._indent}combo_run({combo_seq.name});")
                lines.append(f"{self._indent}}}")
        lines.extend(["}", ""])

        for combo_seq in template.combos:
            lines.append(f"// {combo_seq.description}")
            lines.append(f"combo {combo_seq.name} {{")
            for step in combo_seq.steps:
                lines.append(f"{self._indent}set_val({step.button}, {step.value});")
                if step.hold_ms > 0:
                    lines.append(f"{self._indent}wait({step.hold_ms});")
                if step.wait_after_ms > 0:
                    if step.value != 0:
                        lines.append(f"{self._indent}set_val({step.button}, 0);")
                    lines.append(f"{self._indent}wait({step.wait_after_ms});")
            lines.extend(["}", ""])

        return "\n".join(lines)

    def generate_from_disruption(self, disruption_config: Dict) -> str:
        """Return a safe helper script for the current local workflow."""
        methods = set(disruption_config.get("methods", []))
        params = disruption_config.get("params", {})
        if {"report", "diagnostic"} & methods:
            template = TEMPLATES["Diagnostic Marker"]
        elif {"lag", "drop", "bandwidth"} & methods:
            template = TEMPLATES["DayZ Accessibility Helper"]
        else:
            template = TEMPLATES["Hold Toggle Helper"]
        return self.generate(template, disruption_params=params)

    def export_to_file(self, source: str, path: str) -> bool:
        """Write generated GPC source to a .gpc file atomically."""
        if not source or not path:
            log_error("GPCGenerator.export_to_file: empty source or path")
            return False

        tmp_path = path + ".tmp"
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(source)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            log_info(f"GPCGenerator: exported script to {path}")
            return True
        except Exception as exc:
            log_error(f"GPCGenerator: failed to export to {path}: {exc}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return False


def adjust_combo_timing(script_source: str, multiplier: float) -> str:
    """Scale all wait() values in a GPC script by a multiplier."""
    import re

    def replace_wait(match):
        original = int(match.group(1))
        adjusted = max(1, int(original * multiplier))
        return f"wait({adjusted})"

    return re.sub(r"wait\(\s*(\d+)\s*\)", replace_wait, script_source)


def list_templates() -> List[dict]:
    """Return all registered templates as dictionaries."""
    return [
        {"name": template.name, "game": template.game, "description": template.description}
        for template in TEMPLATES.values()
    ]


def get_template(name: str) -> Optional[GPCTemplate]:
    """Get a template by name."""
    return TEMPLATES.get(name)


def get_template_names() -> List[str]:
    """Return all registered template names."""
    return list(TEMPLATES.keys())
