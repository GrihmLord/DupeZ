"""An advisory inventory must not turn missing or stale evidence into release approval."""
from __future__ import annotations

import json
from types import SimpleNamespace
import subprocess

import pytest

from scripts import release_readiness as readiness


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness.preflight, "check_source", lambda _version: [])
    monkeypatch.setattr(readiness.preflight, "_check_license_policy", lambda **_kwargs: ([], []))
    return tmp_path


def _complete_inventory(root):
    for name in (*readiness.preflight.required_distribution_artifacts("5.8.0"), *readiness.EVIDENCE_FILES):
        path = root / "dist" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"stale, unsigned and unverified fixture")
    (root / "LICENSE.txt").write_text("fixture", encoding="utf-8")


def test_missing_inputs_block_without_creating_output(workspace):
    report = readiness.collect_readiness("5.8.0")
    assert report["disposition"] == "blocked"
    assert report["release_authorized"] is False
    assert any(item["path"] == "dist/DupeZ_v5.8.0_Setup.exe" for item in report["inventory"])
    assert not list(workspace.iterdir())


def test_complete_filenames_never_mean_verified_release(workspace):
    _complete_inventory(workspace)
    before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    report = readiness.collect_readiness("5.8.0")
    assert report["disposition"] == "requires-gate-validation"
    assert report["release_authorized"] is False
    assert all(item["state"] == "present-unverified" for item in report["inventory"])
    assert {path: path.read_bytes() for path in before} == before


def test_owner_evidence_uses_distribution_gate(workspace, monkeypatch):
    calls = []

    def validate(*, distribution):
        calls.append(distribution)
        return ["owner decision unresolved"], []

    monkeypatch.setattr(readiness.preflight, "_check_license_policy", validate)
    report = readiness.collect_readiness("5.8.0")
    assert calls == [True]
    check = next(item for item in report["checks"] if item["id"] == "owner-distribution-evidence")
    assert check["state"] == "blocked"
    assert "1 owner distribution-evidence checks failed" in check["detail"]


def test_source_checker_failure_is_not_reported_as_pass(workspace, monkeypatch):
    def failed(_version):
        raise OSError("private filesystem details")

    monkeypatch.setattr(readiness.preflight, "check_source", failed)
    check = readiness.collect_readiness("5.8.0")["checks"][0]
    assert check["state"] == "blocked"
    assert "private filesystem details" not in check["detail"]


def test_returned_preflight_errors_do_not_export_private_paths(workspace, monkeypatch):
    private = r"C:\Users\SyntheticOperator\private-owner-record.txt"
    monkeypatch.setattr(readiness.preflight, "check_source", lambda _version: [private])
    monkeypatch.setattr(readiness.preflight, "_check_license_policy", lambda **_kw: ([private], []))
    rendered = json.dumps(readiness.collect_readiness("5.8.0"))
    assert "SyntheticOperator" not in rendered
    assert "private-owner-record" not in rendered


def test_empty_artifact_is_unavailable(workspace):
    _complete_inventory(workspace)
    (workspace / "dist/DupeZ-GPU.exe").write_bytes(b"")
    report = readiness.collect_readiness("5.8.0")
    assert report["disposition"] == "blocked"
    assert readiness._inventory_file("dist/DupeZ-GPU.exe")["state"] == "missing-or-empty"


@pytest.mark.parametrize("version", ["../5.8.0", "5.8", "5.8.0\n", "5.8.0;calc"])
def test_invalid_version_rejected_before_checks(version, workspace):
    with pytest.raises(ValueError, match="version"):
        readiness.collect_readiness(version)


def _runs(commit):
    return [{"name": name, "head_sha": commit, "status": "completed", "conclusion": "success"}
            for name in sorted(readiness.REQUIRED_CHECKS)]


@pytest.mark.parametrize("condition,expected", [
    ("complete", "passed"), ("missing", "blocked"), ("failure", "blocked"),
    ("queued", "blocked"), ("skipped", "blocked"), ("wrong-head", "not-checked"),
    ("duplicate", "not-checked"), ("truncated", "not-checked"), ("float-count", "not-checked"),
    ("malformed", "not-checked"), ("denied", "not-checked"), ("timeout", "not-checked"),
])
def test_github_is_exact_commit_complete_and_fail_closed(workspace, monkeypatch, condition, expected):
    commit = "a" * 40
    runs = _runs(commit)
    if condition == "missing":
        runs.pop()
    elif condition in {"failure", "skipped"}:
        runs[0]["conclusion"] = condition
    elif condition == "queued":
        runs[0]["status"] = "queued"
    elif condition == "wrong-head":
        runs[0]["head_sha"] = "b" * 40
    elif condition == "duplicate":
        runs.append(dict(runs[0]))
    payload = {"check_runs": runs, "total_count": len(runs) + (condition == "truncated")}
    if condition == "float-count":
        payload["total_count"] = float(len(runs))

    def invoke(args, **kwargs):
        assert args[:2] == ["gh", "api"]
        assert f"/commits/{commit}/check-runs?per_page=100" in args[2]
        assert kwargs["timeout"] == 30
        if condition == "timeout":
            raise subprocess.TimeoutExpired(args, 30)
        return SimpleNamespace(returncode=1 if condition == "denied" else 0,
                               stdout="{" if condition == "malformed" else json.dumps(payload))

    monkeypatch.setattr(readiness.subprocess, "run", invoke)
    assert readiness._github_check(commit)["state"] == expected


def test_default_does_not_contact_github(workspace, monkeypatch):
    monkeypatch.setattr(readiness.subprocess, "run", lambda *_a, **_kw: pytest.fail("unexpected network query"))
    readiness.collect_readiness("5.8.0")


def test_json_cli_and_exit_status(workspace, capsys):
    assert readiness.main(["--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "dupez.release-readiness.v1"
    _complete_inventory(workspace)
    assert readiness.main(["--json"]) == 2
    assert json.loads(capsys.readouterr().out)["release_authorized"] is False


def test_github_requires_an_explicit_complete_commit(workspace):
    with pytest.raises(SystemExit) as exc:
        readiness.main(["--github"])
    assert exc.value.code == 2
    with pytest.raises(ValueError, match="commit"):
        readiness.collect_readiness("5.8.0", github_commit="HEAD;anything")
