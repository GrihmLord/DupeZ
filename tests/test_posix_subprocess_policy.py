"""Policy regressions for privileged POSIX executable resolution."""

from __future__ import annotations

from pathlib import Path


def test_privileged_arp_code_never_executes_from_path() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "network" / "arp_spoof.py"
    ).read_text(encoding="utf-8")

    assert "resolve_posix_system_binary" in source
    assert "shutil.which" not in source
    assert "check_output" not in source
    assert '["ip",' not in source


def test_posix_resolver_does_not_consult_path() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "core"
        / "safe_subprocess.py"
    ).read_text(encoding="utf-8")
    resolver = source[source.index("def resolve_posix_system_binary") :]

    assert "shutil.which" not in resolver
    assert "_POSIX_SYSTEM_DIRS" in resolver
    assert "st_uid != 0" in resolver
    assert "stat.S_IWGRP | stat.S_IWOTH" in resolver
