"""Enforce high-value package dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.builtin_presets import BUILTIN_PRESETS, get_builtin_preset

_ROOT = Path(__file__).resolve().parents[1]


def _app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


@pytest.mark.parametrize("package", ["core", "firewall_helper"])
def test_backend_packages_do_not_import_gui(package: str) -> None:
    violations = []
    for path in (_ROOT / "app" / package).rglob("*.py"):
        for module in _app_imports(path):
            if module == "app.gui" or module.startswith("app.gui."):
                violations.append(
                    f"{path.relative_to(_ROOT).as_posix()}: {module}"
                )
    assert not violations, (
        "backend packages must not depend on presentation modules:\n"
        + "\n".join(sorted(violations))
    )


def test_builtin_preset_resolver_returns_defensive_copies() -> None:
    original = BUILTIN_PRESETS["Red Disconnect"]["params"]["disconnect_chance"]
    resolved = get_builtin_preset("Red Disconnect")

    resolved["params"]["disconnect_chance"] = 1
    resolved["methods"].append("unexpected")

    assert BUILTIN_PRESETS["Red Disconnect"]["params"]["disconnect_chance"] == original
    assert "unexpected" not in BUILTIN_PRESETS["Red Disconnect"]["methods"]


def test_unknown_builtin_preset_is_empty() -> None:
    assert get_builtin_preset("does-not-exist") == {}


def test_controller_has_no_module_level_service_factory_call() -> None:
    path = _ROOT / "app" / "core" / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "get_disruption_manager"
        ):
            offenders.append(node.lineno)
    assert not offenders, (
        "controller must resolve the disruption manager inside AppController, "
        f"not at import time; offending lines: {offenders}"
    )
