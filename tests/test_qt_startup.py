"""Tests for Qt argv normalization before native application startup."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.qt_startup import normalized_qt_argv


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
