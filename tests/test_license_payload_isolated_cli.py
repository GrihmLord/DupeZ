"""Recipient notice tooling must work without implicit script/CWD imports."""

from pathlib import Path
import subprocess
import sys


def test_notice_cli_supports_isolated_interpreter_from_another_directory(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "license_payload.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--verify" in result.stdout
