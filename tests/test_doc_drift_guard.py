"""Doc-drift guard — the in-app help must match the real app.

WHY THIS EXISTS
---------------
v5.7.x shipped in-app help (``app/gui/panels/help_panel.py``) that
described a "Dupe Engine v2" and a "DUPE METHOD" card. Both had been
removed releases earlier. A user followed the help text and hit a wall:
the documented UI did not exist. The fix corrected the text — this test
stops the whole *class* of bug from recurring.

It cross-checks the help panel against ground truth WITHOUT importing any
Qt module — it parses source with ``ast`` and plain text — so it runs
anywhere the rest of the suite runs. It fails the build if the help panel:

  * still names the removed DUPE METHOD card,
  * omits a real preset or disruption module, or
  * disagrees with the menu bar about keyboard shortcuts.

If you add or remove a preset / module / shortcut, update help_panel.py
in the SAME change. Forcing that is the entire point of this test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HELP = _ROOT / "app" / "gui" / "panels" / "help_panel.py"
_CLUMSY = _ROOT / "app" / "gui" / "clumsy_control.py"
_PRESETS = _ROOT / "app" / "core" / "builtin_presets.py"
_DASHBOARD = _ROOT / "app" / "gui" / "dashboard.py"

# The tray-toggle is a standalone QShortcut, not a menu QAction, so the
# menu-bar AST walk below cannot see it. It is allowed to appear in the
# help shortcut table without a matching _add_action() call.
_NON_MENU_SHORTCUTS = {"Ctrl+Shift+D"}


# ── Ground-truth extraction (ast / text only — no Qt import) ──────────

def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_value(tree: ast.Module, name: str) -> ast.expr | None:
    """Return the RHS expression of a module-level assignment to *name*.

    Handles both plain ``NAME = ...`` and annotated ``NAME: T = ...``.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    return None


def _preset_names() -> set[str]:
    """The built-in preset names from the backend source of truth."""
    val = _find_value(_parse(_PRESETS), "BUILTIN_PRESETS")
    assert isinstance(val, ast.Dict), "BUILTIN_PRESETS is not a dict literal"
    names = {
        k.value for k in val.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert names, "no preset names extracted from PRESETS"
    return names


def _module_labels() -> set[str]:
    """UI labels from MODULE_DEFS — the 2nd positional arg of each _mdef()."""
    val = _find_value(_parse(_CLUMSY), "MODULE_DEFS")
    assert isinstance(val, ast.List), "clumsy_control.MODULE_DEFS is not a list literal"
    labels: set[str] = set()
    for elt in val.elts:
        if (isinstance(elt, ast.Call)
                and isinstance(elt.func, ast.Name)
                and elt.func.id == "_mdef"
                and len(elt.args) >= 2
                and isinstance(elt.args[1], ast.Constant)):
            labels.add(elt.args[1].value)
    assert labels, "no module labels extracted from MODULE_DEFS"
    return labels


def _menu_shortcuts() -> set[str]:
    """Non-empty shortcut strings passed to dashboard._add_action()."""
    shortcuts: set[str] = set()
    for node in ast.walk(_parse(_DASHBOARD)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_add_action"
                and len(node.args) >= 3
                and isinstance(node.args[2], ast.Constant)):
            sc = node.args[2].value
            if sc:
                shortcuts.add(sc)
    assert shortcuts, "no shortcuts extracted from dashboard _add_action calls"
    return shortcuts


def _help_text() -> str:
    return _HELP.read_text(encoding="utf-8")


def _help_shortcut_cells() -> set[str]:
    """Shortcut strings from the help-panel KEYBOARD SHORTCUTS table.

    The table renders each shortcut in a monospace ``<td>``; this pulls
    the cell contents straight out of the source.
    """
    cells = re.findall(r"font-family:monospace[^>]*>([^<]+)</td>", _help_text())
    return {c.strip() for c in cells}


# ── Tests ────────────────────────────────────────────────────────────

def test_removed_dupe_method_card_not_documented() -> None:
    """The exact PUTKASKANU regression — the removed card must stay gone."""
    assert "DUPE METHOD" not in _help_text(), (
        "help_panel.py references the removed 'DUPE METHOD' card. "
        "DupeEngineV2 was deleted; duplication runs through the Red "
        "Disconnect preset's stateful DISCONNECT module. Fix the help text."
    )


def test_every_preset_is_documented() -> None:
    """Every built-in preset must be named in the help panel."""
    help_text = _help_text()
    missing = sorted(p for p in _preset_names() if p not in help_text)
    assert not missing, (
        f"presets exist in builtin_presets.BUILTIN_PRESETS but are not documented "
        f"in help_panel.py: {missing}"
    )


def test_every_module_is_documented() -> None:
    """Every disruption module label must appear in the help panel."""
    help_lower = _help_text().lower()
    missing = sorted(m for m in _module_labels() if m.lower() not in help_lower)
    assert not missing, (
        f"disruption modules exist in MODULE_DEFS but are not documented "
        f"in help_panel.py: {missing}"
    )


def test_keyboard_shortcuts_match_menu() -> None:
    """The help shortcut table and the real menu bar must agree."""
    menu = _menu_shortcuts()
    documented = _help_shortcut_cells()

    undocumented = sorted(menu - documented)
    assert not undocumented, (
        f"menu actions register these shortcuts but the help KEYBOARD "
        f"SHORTCUTS table omits them: {undocumented}"
    )

    invented = sorted(documented - menu - _NON_MENU_SHORTCUTS)
    assert not invented, (
        f"the help KEYBOARD SHORTCUTS table lists shortcuts that no menu "
        f"action registers: {invented}"
    )
