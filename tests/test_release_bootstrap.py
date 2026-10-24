"""Exercise the finalizer's bootstrap resolver without invoking a build."""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "scripts" / "finalize_release.ps1"


def _ps_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _resolve_fixture(
    repository: Path, configured: str, *, validation_exit: int = 0
) -> dict:
    """Load only the real resolver AST; replace execution with a checked spy."""
    if os.name != "nt":
        pytest.skip("Windows release bootstrap contract")
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    script = rf"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_ps_string(FINALIZER)}, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {{ throw 'Finalizer parse errors.' }}
$definitions = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Resolve-ReleaseBootstrapPython'
}}, $true))
if ($definitions.Count -ne 1) {{ throw 'Resolver definition missing or duplicated.' }}
. ([scriptblock]::Create($definitions[0].Extent.Text))
$repoRoot = {_ps_string(repository)}
$script:invocations = @()
function Invoke-Checked {{
    param([string]$FilePath, [string[]]$ArgumentList, [string]$Description)
    $script:invocations += @{{
        path = $FilePath
        arguments = $ArgumentList
        description = $Description
    }}
    if ({validation_exit} -ne 0) {{ throw 'Interpreter validation failed.' }}
}}
try {{
    $selected = Resolve-ReleaseBootstrapPython -ConfiguredPath {_ps_string(configured)}
    @{{selected=$selected; error=$null; invocations=@($script:invocations)}} |
        ConvertTo-Json -Depth 5 -Compress
}}
catch {{
    @{{selected=$null; error=$_.Exception.Message; invocations=@($script:invocations)}} |
        ConvertTo-Json -Depth 5 -Compress
}}
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        shell=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never executed: the PowerShell fixture intercepts Invoke-Checked.
    path.write_bytes(b"bootstrap fixture")
    return path


def test_finalizer_forwards_verified_bootstrap_before_source_preflight_and_build():
    text = FINALIZER.read_text(encoding="utf-8")
    selection = text.index("$python = Resolve-ReleaseBootstrapPython")
    override = text.index(
        '-ConfiguredPath (Resolve-EnvVar -Name "DUPEZ_BOOTSTRAP_PYTHON")', selection
    )
    forwarding = text.index("$env:DUPEZ_BOOTSTRAP_PYTHON = $python", override)
    preflight = text.index('-Description "SOURCE RELEASE PREFLIGHT"', forwarding)
    build = text.index('-Description "BUILD RELEASE ARTIFACTS"', preflight)
    assert selection < override < forwarding < preflight < build
    assert '$python = Resolve-Tool -Candidates' not in text


def test_bootstrap_defaults_to_repository_venv(tmp_path):
    expected = _executable(tmp_path / ".venv" / "Scripts" / "python.exe")
    result = _resolve_fixture(tmp_path, "")
    assert result["error"] is None
    assert result["selected"] == str(expected)
    assert len(result["invocations"]) == 1
    call = result["invocations"][0]
    assert call["path"] == str(expected)
    assert call["arguments"][:3] == ["-I", "-S", "-c"]
    assert call["description"] == "VERIFY RELEASE PYTHON"


def test_explicit_bootstrap_wins_over_existing_default(tmp_path):
    _executable(tmp_path / ".venv" / "Scripts" / "python.exe")
    expected = _executable(tmp_path / "custom interpreter's path" / "python.exe")
    result = _resolve_fixture(tmp_path, str(expected))
    assert result["error"] is None
    assert result["selected"] == str(expected)
    assert result["invocations"][0]["path"] == str(expected)


def test_invalid_explicit_bootstrap_never_falls_back(tmp_path):
    _executable(tmp_path / ".venv" / "Scripts" / "python.exe")
    result = _resolve_fixture(tmp_path, str(tmp_path / "missing.exe"))
    assert result["selected"] is None
    assert "was not found" in result["error"]
    assert result["invocations"] == []


@pytest.mark.parametrize("configured", ["python.exe", r".venv\Scripts\python.exe"])
def test_relative_bootstrap_is_rejected_without_ambient_lookup(tmp_path, configured):
    result = _resolve_fixture(tmp_path, configured)
    assert result["selected"] is None
    assert "absolute executable path" in result["error"]
    assert result["invocations"] == []


def test_non_executable_bootstrap_is_rejected(tmp_path):
    candidate = _executable(tmp_path / "python.ps1")
    result = _resolve_fixture(tmp_path, str(candidate))
    assert result["selected"] is None
    assert result["invocations"] == []


@pytest.mark.parametrize("directory", [".release-venv", ".RELEASE-VENV"])
def test_bootstrap_cannot_be_in_environment_the_build_will_remove(tmp_path, directory):
    candidate = _executable(tmp_path / directory / "Scripts" / "python.exe")
    result = _resolve_fixture(tmp_path, str(candidate))
    assert result["selected"] is None
    assert "disposable .release-venv" in result["error"]
    assert result["invocations"] == []


def test_similarly_named_external_environment_is_allowed(tmp_path):
    candidate = _executable(tmp_path / ".release-venv-backup" / "python.exe")
    result = _resolve_fixture(tmp_path, str(candidate))
    assert result["error"] is None
    assert result["selected"] == str(candidate)


def test_failed_python_validation_never_returns_or_falls_back(tmp_path):
    _executable(tmp_path / ".venv" / "Scripts" / "python.exe")
    candidate = _executable(tmp_path / "alternate" / "python.exe")
    result = _resolve_fixture(tmp_path, str(candidate), validation_exit=1)
    assert result["selected"] is None
    assert result["error"] == "Interpreter validation failed."
    assert len(result["invocations"]) == 1
    assert result["invocations"][0]["path"] == str(candidate)


@pytest.mark.parametrize(
    ("version", "pointer_size", "expected"),
    [
        ((3, 13, 14), 8, 0),
        ((3, 13, 14), 4, 1),
        ((3, 13, 13), 8, 1),
        ((3, 13, 15), 8, 1),
        ((3, 12, 14), 8, 1),
        ((3, 14, 14), 8, 1),
    ],
)
def test_bootstrap_validation_requires_exact_version_and_64_bits(
    version, pointer_size, expected
):
    text = FINALIZER.read_text(encoding="utf-8")
    checks = re.findall(r'"import struct,sys; raise SystemExit\((.*?)\)"', text)
    assert len(checks) == 1
    result = eval(
        checks[0],
        {"__builtins__": {}},
        {
            "sys": SimpleNamespace(version_info=version),
            "struct": SimpleNamespace(calcsize=lambda _: pointer_size),
        },
    )
    assert result == expected
