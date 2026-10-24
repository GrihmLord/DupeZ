"""Policy tests for source-validation GitHub Actions workflows."""

import json

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_tests_ci_triggers_for_every_python_source_area_and_configuration():
    workflow = _read(".github/workflows/tests-ci.yml")

    required_paths = (
        "app/**",
        "bench/**",
        "docs/**/*.py",
        "packaging/**",
        "plugins/**/*.py",
        "scripts/**",
        "tests/**",
        "tools/**/*.py",
        "dupez.py",
        "dupez_helper.py",
        "dupez_single_instance.py",
        ".github/workflows/**",
        "pytest.ini",
        "ruff.toml",
        "requirements.in",
        "requirements.txt",
        "requirements-locked.header",
        "requirements-locked.txt",
        "requirements-test.in",
        "requirements-test-locked.txt",
        "requirements-hardware-test.in",
        "requirements-hardware-test-locked.txt",
    )
    for path in required_paths:
        assert workflow.count(f"- '{path}'") == 2, path


def test_tests_ci_runs_pinned_ruff_and_parses_every_tracked_python_file():
    workflow = _read(".github/workflows/tests-ci.yml")

    assert "\n  ruff:\n" in workflow
    assert "-r requirements-test-locked.txt" in workflow
    assert "'ruff==0.7.4'" not in workflow
    assert "ruff check --" in workflow
    assert "Run Ruff on every tracked Python file" in workflow
    assert "AST-parse every tracked Python file" in workflow
    assert '["git", "ls-files", "-z", "--", "*.py"]' in workflow
    assert "pathlib.Path('app').rglob('*.py')" not in workflow


def test_tests_ci_enforces_measured_whole_application_coverage_floor():
    workflow = _read(".github/workflows/tests-ci.yml")

    assert "-r requirements-test-locked.txt" in workflow
    assert "pip install 'pytest==9.0.3' 'pytest-cov==7.1.0'" not in workflow
    assert "--cov=app " in workflow
    assert "--cov-fail-under=40" in workflow
    assert "--cov=app.core.second_factor" not in workflow
    assert "--cov=app.gui.dayz_account_tracker" not in workflow
    assert "--only-binary=:all: --require-hashes" in workflow


def test_source_preflight_runs_for_every_exact_head_without_path_filters():
    workflow = _read(".github/workflows/source-preflight.yml")

    assert "\n  pull_request:\n" in workflow
    assert "\n  push:\n" in workflow
    assert "branches: [main]" in workflow
    assert "paths:" not in workflow
    assert "paths-ignore:" not in workflow
    assert "python-version: '3.13.14'" in workflow
    assert "python -I scripts/release_preflight.py" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "persist-credentials: false" in workflow


def test_hardware_actions_share_the_node24_runner_contract():
    workflow = _read(".github/workflows/hardware-smoketest.yml")

    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "GitHub Actions runner 2.327.1 or newer" in workflow


def test_dependency_review_is_blocking_for_every_dependency_manifest():
    workflow = _read(".github/workflows/dependency-review.yml")

    for path in (
        "requirements.in",
        "requirements.txt",
        "requirements-locked.header",
        "requirements-locked.txt",
        "requirements-test.in",
        "requirements-test-locked.txt",
        "requirements-hardware-test.in",
        "requirements-hardware-test-locked.txt",
        "packaging/requirements-build.in",
        "packaging/requirements-build-locked.txt",
    ):
        assert f'- "{path}"' in workflow, path

    assert "actions/dependency-review-action@" in workflow
    assert "fail-on-severity: moderate" in workflow
    assert "continue-on-error" not in workflow
    assert "::warning::" not in workflow


def test_lock_workflow_verifies_runtime_and_build_tool_graphs():
    workflow = _read(".github/workflows/requirements-lock.yml")

    for path in (
        "requirements.in",
        "requirements-locked.txt",
        "requirements-test.in",
        "requirements-test-locked.txt",
        "requirements-hardware-test.in",
        "requirements-hardware-test-locked.txt",
        "packaging/requirements-build.in",
        "packaging/requirements-build-locked.txt",
    ):
        assert workflow.count(f'- "{path}"') == 2, path

    assert "--requirements requirements.in" in workflow
    assert "--lock requirements-locked.txt" in workflow
    assert "--requirements requirements-test.in" in workflow
    assert "--lock requirements-test-locked.txt" in workflow
    assert "--requirements packaging/requirements-build.in" in workflow
    assert "--lock packaging/requirements-build-locked.txt" in workflow
    assert "-r requirements-locked.txt" in workflow
    assert "-r packaging/requirements-build-locked.txt" in workflow
    assert "verify-build-lock:" in workflow
    assert "verify-test-lock:" in workflow
    assert "verify-hardware-test-lock:" in workflow
    assert "runs-on: windows-latest" in workflow
    push_paths = workflow[
        workflow.index("  push:") : workflow.index("  pull_request:")
    ]
    pull_paths = workflow[
        workflow.index("  pull_request:") : workflow.index("\npermissions:")
    ]
    for path in (
        "requirements-hardware-test.in",
        "requirements-hardware-test-locked.txt",
    ):
        assert f'- "{path}"' in pull_paths
        assert f'- "{path}"' in push_paths

    hardware_job = workflow[workflow.index("  verify-hardware-test-lock:") :]
    for token in (
        "runs-on: windows-latest",
        "python-version: '3.13.14'",
        "python -m pip install --upgrade 'pip==26.2.2'",
        "--requirements requirements-hardware-test.in",
        "--lock requirements-hardware-test-locked.txt",
        "--only-binary=:all:",
        "--dry-run --require-hashes",
        "-r requirements-hardware-test-locked.txt",
    ):
        assert token in hardware_job, token


def test_lock_generation_and_install_checks_pin_their_bootstrap_tools():
    powershell = _read("scripts/lock-requirements.ps1")
    posix = _read("scripts/lock-requirements.sh")
    lock_workflow = _read(".github/workflows/requirements-lock.yml")
    hardware_workflow = _read(".github/workflows/hardware-smoketest.yml")
    secret_scan_workflow = _read(".github/workflows/secret-scan.yml")

    for script in (powershell, posix):
        assert 'pip==26.2.2' in script
        assert 'pip-tools==7.6.1' in script
        assert "--only-binary=:all:" in script
        assert "requirements-test.in" in script
        assert "requirements-test-locked.txt" in script
        assert "scripts/verify_requirements_lock.py" in script
        assert "--dry-run" in script
        assert "--require-hashes" in script
        assert "--upgrade pip-tools" not in script
    assert "python -m pip install --upgrade 'pip==26.2.2'" in lock_workflow
    assert (
        "& $toolPython -m pip install --upgrade 'pip==26.2.2'"
        in hardware_workflow
    )
    assert "requirements-hardware-test-locked.txt" in hardware_workflow
    assert "--only-binary=:all: --require-hashes" in hardware_workflow
    assert "pip install 'pytest==9.0.3'" not in hardware_workflow
    assert "pip install pytest" not in hardware_workflow
    assert (
        "pip install 'detect-secrets==1.5.0' 'pytest==9.0.3'"
        in secret_scan_workflow
    )
    assert "python -m pip install --upgrade 'pip==26.2.2'" in (
        secret_scan_workflow
    )


def test_privileged_hardware_pytest_graph_is_minimal_and_hash_locked():
    source = _read("requirements-hardware-test.in")
    lock = _read("requirements-hardware-test-locked.txt")

    assert "pytest==9.0.3" in source
    package_lines = [
        line
        for line in lock.splitlines()
        if line and not line[0].isspace() and not line.startswith("#")
    ]
    expected_names = {
        "colorama",
        "iniconfig",
        "packaging",
        "pluggy",
        "pygments",
        "pytest",
    }
    assert {line.partition("==")[0] for line in package_lines} == expected_names
    for index, package_line in enumerate(package_lines):
        start = lock.index(package_line)
        end = (
            lock.index(package_lines[index + 1], start)
            if index + 1 < len(package_lines)
            else len(lock)
        )
        assert "--hash=sha256:" in lock[start:end], package_line
    # pip-tools 7.6.1 specializes environment markers while compiling on
    # Windows, so the Windows-only pytest dependency is emitted as an
    # unconditional locked line in this Windows-only privileged workflow.
    assert "colorama==0.4.6 \\" in package_lines
    assert "pytest-cov" not in lock
    assert "ruff" not in lock
    assert "http://" not in lock
    assert "https://" not in lock


def test_pytest_audit_isolation_fails_closed():
    conftest = _read("tests/conftest.py")

    assert "raise pytest.UsageError" in conftest
    assert "could not establish isolated audit logging" in conftest
    assert "audit isolation skipped" not in conftest


def test_secret_scan_checks_tracked_files_without_mutating_the_baseline():
    workflow = _read(".github/workflows/secret-scan.yml")

    assert "test -f .secrets.baseline" in workflow
    assert "git ls-files -z" in workflow
    assert (
        "xargs -0 detect-secrets-hook --baseline .secrets.baseline"
        in workflow
    )
    assert "git diff --exit-code -- .secrets.baseline" in workflow
    assert "detect-secrets scan --baseline" not in workflow
    assert "detect-secrets audit --report" not in workflow

    baseline = json.loads(_read(".secrets.baseline"))
    for path, findings in baseline["results"].items():
        assert "\\" not in path, path
        assert all(finding["filename"] == path for finding in findings), path
