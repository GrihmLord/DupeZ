"""Tests for scripts.verify_requirements_lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_requirements_lock import parse_direct_requirements, parse_lock, verify


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_runtime_lock_contract_passes() -> None:
    assert verify(
        Path("requirements.in"),
        Path("requirements-locked.txt"),
    ) == []


def test_runtime_urllib3_floor_excludes_september_2026_advisories() -> None:
    # GHSA-8988-9cw3-xx77, GHSA-gh4c-6fx4-qh6g and GHSA-vxq7-64xx-v4gw
    # are fixed in 2.8.0. Keep source resolution and the release pin aligned.
    requirement = next(req for _line, req in parse_direct_requirements(Path("requirements.in"))
                       if req.name == "urllib3")
    assert "2.7.0" not in requirement.specifier
    assert "2.8.0" in requirement.specifier
    locked = parse_lock(Path("requirements-locked.txt"))["urllib3"]
    assert locked.version in requirement.specifier


@pytest.mark.parametrize("name,rejected,accepted", [
    ("pillow", "12.3.0", "13.0.0"),
    ("certifi", "2026.2.25", "2026.10.19"),
    ("cryptography", "50.0.0", "50.0.2"),
    ("pyqt6-qt6", "6.11.0", "6.11.2"),
    ("pyqt6-webengine-qt6", "6.11.0", "6.11.2"),
])
def test_october_security_floors_and_lock_stay_aligned(name, rejected, accepted):
    requirements = {
        req.name.lower(): req
        for _line, req in parse_direct_requirements(Path("requirements.in"))
    }
    requirement = requirements[name]
    assert rejected not in requirement.specifier
    assert accepted in requirement.specifier
    locked = parse_lock(Path("requirements-locked.txt"))[name]
    assert locked.version in requirement.specifier


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

    with pytest.raises(ValueError, match="no SHA-256 hash"):
        verify(requirements, lock)


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


def test_platform_marker_operator_cannot_drift(tmp_path) -> None:
    requirements = _write(
        tmp_path / "requirements.in",
        "pywin32>=306; sys_platform == 'win32'\n",
    )
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "pywin32==312 ; sys_platform != 'win32' \\\n"
        "    --hash=sha256:" + "d" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("does not exactly match" in error for error in errors)


def test_platform_marker_expression_cannot_be_reassociated(tmp_path) -> None:
    requirements = _write(
        tmp_path / "requirements.in",
        "pywin32>=306; "
        "python_version >= '3.12' and python_version < '3.14'\n",
    )
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "pywin32==312 ; "
        "python_version < '3.12' and python_version >= '3.14' \\\n"
        "    --hash=sha256:" + "f" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("does not exactly match" in error for error in errors)


def test_unmarked_direct_requirement_rejects_injected_lock_marker(tmp_path) -> None:
    requirements = _write(tmp_path / "requirements.in", "requests>=2\n")
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "requests==2.34.2 ; python_version < '0' \\\n"
        "    --hash=sha256:" + "e" * 64 + "\n",
    )

    errors = verify(requirements, lock)

    assert any("injects an unexpected marker" in error for error in errors)


@pytest.mark.parametrize(
    ("unsupported", "message"),
    (
        (
            "unreviewed @ https://example.invalid/unreviewed.whl \\\n"
            "    --hash=sha256:" + "b" * 64 + "\n",
            "direct URL lock entries",
        ),
        (
            "--hash=sha256:" + "c" * 64 + "\n",
            "orphan lock hash",
        ),
        (
            "unreviewed>=1 \\\n"
            "    --hash=sha256:" + "d" * 64 + "\n",
            "exact == pin",
        ),
        (
            "unreviewed==1 \\\n"
            "    --hash=sha256:" + "e" * 64 + " \\\n"
            "    --trusted-host example.invalid\n",
            "unsupported lock option",
        ),
    ),
)
def test_unsupported_or_orphan_lock_lines_fail_closed(
    tmp_path,
    unsupported,
    message,
) -> None:
    requirements = _write(tmp_path / "requirements.in", "requests>=2\n")
    lock = _write(
        tmp_path / "requirements-locked.txt",
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        + unsupported,
    )

    with pytest.raises(ValueError, match=message):
        verify(requirements, lock)
