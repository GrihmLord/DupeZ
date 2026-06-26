"""Guard active shipped content against exploit/evasion positioning."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]

_ACTIVE_CONTENT_FILES = (
    "app/config/dayz_duping_config.json",
    "app/config/dayz_tips_tricks.json",
    "app/config/game_profiles/dayz.json",
    "app/config/latency_config.json",
    "app/gpc/gpc_generator.py",
    "app/ai/smart_engine.py",
    "app/ai/llm_advisor.py",
    "app/core/builtin_presets.py",
    "app/core/preset_store.py",
    "app/firewall/modules/disconnect.py",
    "app/firewall/native_divert_engine.py",
    "app/gui/clumsy_control.py",
    "app/gui/dialogs/preset_editor_dialog.py",
    "app/gui/panels/help_panel.py",
    "app/gui/panels/smart_mode_panel.py",
    "README.md",
    "ROADMAP.md",
    "docs/README.md",
    "docs/ROADMAP_v6.md",
    "docs/competitive_audit.md",
    "docs/audits/DEEP_DEFENSIVE_AUDIT_2026-06-24.md",
    "docs/release-notes/v5.7.7.md",
)

_BANNED_ACTIVE_PHRASES = (
    "DayZ Auto Dupe",
    "God Mode Actions",
    "Anti Recoil",
    "duping_methods",
    "success_rate_estimate",
    "detection_risk",
    "stealth_recommendations",
    "behavioral_stealth",
    "anti_cheat",
    "clone-dupe",
    "maximum cut",
    "inventory exploitation",
    "exploitation techniques",
    "God Mode",
    "god mode",
    "dupe window",
    "duplication preset",
    "DUPLICATION WORKFLOW",
    "inventory desync",
    "invulnerable",
    "ghost teleport",
    "hits land",
    "Run anyway",
    "ARP spoof",
    "ARP poison",
    "poisons the ARP",
    "anti-cheat evasion",
    "anti-detect",
    "public-server manipulation",
    "game exploitation",
)


def test_active_dayz_content_is_defensive_and_diagnostic() -> None:
    findings: list[str] = []
    for rel in _ACTIVE_CONTENT_FILES:
        text = (_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        for phrase in _BANNED_ACTIVE_PHRASES:
            if phrase.lower() in lowered:
                findings.append(f"{rel}: {phrase}")

    assert findings == []
