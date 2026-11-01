"""Tests for Qt argv normalization before native application startup."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from app.core import qt_startup
from app.core.qt_startup import normalized_qt_argv


_GRAPHICS_OVERRIDES = (
    "QT_OPENGL",
    "QT_OPENGL_DLL",
    "QT_OPENGL_BUGLIST",
    "QT_NO_OPENGL_BUGLIST",
    "QT_WIDGETS_RHI",
    "QT_WIDGETS_RHI_BACKEND",
    "QT_WIDGETS_RHI_DEBUG_LAYER",
    "QT_WIDGETS_HIGHDPI_DOWNSCALE",
    "QSG_RHI_BACKEND",
    "QSG_RHI_PREFER_SOFTWARE_RENDERER",
    "QT_QUICK_BACKEND",
    "QT_ANGLE_PLATFORM",
)


@pytest.mark.parametrize("value", ["", "0", "unreviewed"])
def test_frozen_graphics_policy_removes_case_insensitive_overrides(
    monkeypatch, value: str,
) -> None:
    monkeypatch.setattr(qt_startup.sys, "platform", "win32")
    monkeypatch.setattr(qt_startup.sys, "frozen", True, raising=False)
    preserved = {
        "QT_PLUGIN_PATH": "bundle/PyQt6/Qt6/plugins",
        "QT_SCALE_FACTOR": "1.5",
        "QT_SCREEN_SCALE_FACTORS": "1.5;2",
        "QT_FONT_DPI": "144",
        "QT_ACCESSIBILITY": "1",
        "Path": "system-path",
    }
    environment = {
        **preserved,
        **{key: value for key in _GRAPHICS_OVERRIDES},
        **{key.lower(): value for key in _GRAPHICS_OVERRIDES},
        "Qt_OpenGL_Dll": "unreviewed.dll",
    }

    qt_startup.sanitize_frozen_qt_graphics_environment(environment)

    assert environment == {**preserved, "QT_OPENGL": "software"}
    qt_startup.sanitize_frozen_qt_graphics_environment(environment)
    assert environment == {**preserved, "QT_OPENGL": "software"}


@pytest.mark.parametrize(
    ("platform", "frozen"), [("win32", False), ("linux", True)],
)
def test_graphics_policy_preserves_source_and_non_windows_diagnostics(
    monkeypatch, platform: str, frozen: bool,
) -> None:
    monkeypatch.setattr(qt_startup.sys, "platform", platform)
    monkeypatch.setattr(qt_startup.sys, "frozen", frozen, raising=False)
    environment = {key: "diagnostic" for key in _GRAPHICS_OVERRIDES}
    original = dict(environment)

    qt_startup.sanitize_frozen_qt_graphics_environment(environment)

    assert environment == original


@pytest.mark.parametrize("entrypoint", ["dupez.py", "app/main.py"])
def test_frozen_entrypoints_sanitize_before_native_or_role_dispatch(
    monkeypatch, entrypoint: str,
) -> None:
    path = Path(__file__).resolve().parents[1] / entrypoint
    tree = ast.parse(path.read_text(encoding="utf-8"))
    policy_index = next(
        index for index, node in enumerate(tree.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "sanitize_frozen_qt_graphics_environment"
    )
    prefix = ast.Module(body=tree.body[:policy_index + 1], type_ignores=[])
    for node in ast.walk(prefix):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("PyQt6")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "_enforce_frozen_windows_startup_hardening",
                "_maybe_dispatch_helper_role", "_maybe_handle_v576_flags",
                "_inproc_self_elevate_if_needed",
            }
    monkeypatch.setattr(qt_startup.sys, "platform", "win32")
    monkeypatch.setattr(qt_startup.sys, "frozen", True, raising=False)
    # Use a private mapping: neither Qt nor a real child process is started.
    environment = {key: "unreviewed" for key in _GRAPHICS_OVERRIDES}
    monkeypatch.setattr(qt_startup.os, "environ", environment)

    exec(compile(prefix, str(path), "exec"), {"__name__": "startup_test"})

    assert environment == {"QT_OPENGL": "software"}


def test_renderer_failure_cannot_restore_inherited_graphics_overrides(
    monkeypatch,
) -> None:
    from app.gui.map_host import renderer_tier

    monkeypatch.setattr(qt_startup.sys, "platform", "win32")
    monkeypatch.setattr(qt_startup.sys, "frozen", True, raising=False)
    environment = {key: "unreviewed" for key in _GRAPHICS_OVERRIDES}
    monkeypatch.setattr(qt_startup.os, "environ", environment)
    qt_startup.sanitize_frozen_qt_graphics_environment()

    def fail_renderer() -> None:
        raise RuntimeError("simulated renderer policy failure")

    monkeypatch.setattr(renderer_tier, "apply_chromium_flags", fail_renderer)
    path = Path(__file__).resolve().parents[1] / "dupez.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    renderer_block = next(
        node for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.ImportFrom)
            and child.module == "app.gui.map_host.renderer_tier"
            and any(alias.name == "apply_chromium_flags" for alias in child.names)
            for child in node.body
        )
    )

    exec(
        compile(ast.Module(body=[renderer_block], type_ignores=[]), str(path), "exec"),
        {"os": qt_startup.os, "_safe_stderr": lambda _message: None},
    )

    assert environment == {
        "QT_OPENGL": "software",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
        "DUPEZ_MAP_RENDERER_TIER": "tier3_cpu",
    }


def test_qt_argv_supplies_program_name_when_empty(tmp_path) -> None:
    executable = tmp_path / "DupeZ-GPU.exe"

    assert normalized_qt_argv([], executable=str(executable)) == [
        os.path.abspath(executable)
    ]


def test_qt_argv_replaces_blank_program_name_and_preserves_arguments(
    tmp_path,
) -> None:
    executable = tmp_path / "DupeZ-Compat.exe"

    assert normalized_qt_argv(
        ["", "--verify-self"],
        executable=str(executable),
    ) == [os.path.abspath(executable), "--verify-self"]


def test_qt_argv_returns_a_private_copy() -> None:
    original = ["DupeZ.exe", "--safe"]

    normalized = normalized_qt_argv(original)

    assert normalized == original
    assert normalized is not original


def test_main_sets_shared_context_attribute_before_qapplication() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")

    attribute = source.index("QCoreApplication.setAttribute(")
    application = source.index("app = QApplication(normalized_qt_argv())")
    assert attribute < application
