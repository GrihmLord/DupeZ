"""Tests for scripts.verify_requirements_lock."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_requirements_lock import verify


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_runtime_lock_contract_passes() -> None:
    assert verify(
        Path("requirements.in"),
        Path("requirements-locked.txt"),
    ) == []


def test_missing_direct_requirement_is_rejected(tmp_path) -> None:
    requirements = _write(tmp_path / "requirements.in", "requests>=2.30\n")
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "urllib3==2.6.3 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("requests" in error and "missing" in error for error in errors)


def test_out_of_range_pin_is_rejected(tmp_path) -> None:
    requirements = _write(tmp_path / "requirements.in", "requests>=2.30,<3\n")
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "requests==1.0.0 \\\n"
        "    --hash=sha256:" + "b" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("does not satisfy" in error for error in errors)


def test_hashless_pin_is_rejected(tmp_path) -> None:
    requirements = _write(tmp_path / "requirements.in", "requests>=2\n")
    lock = _write(tmp_path / "requirements-locked.txt", "requests==2.33.1\n")

    errors = verify(requirements, lock)

    assert any("no SHA-256 hash" in error for error in errors)


def test_platform_marker_must_survive(tmp_path) -> None:
    requirements = _write(
        tmp_path / "requirements.in",
        "pywin32>=306; sys_platform == 'win32'\n",
    )
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "pywin32==312 \\\n"
        "    --hash=sha256:" + "c" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("marker" in error and "lost" in error for error in errors)
