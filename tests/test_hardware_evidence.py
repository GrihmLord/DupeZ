from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.hardware_evidence import (
    CANONICAL_TEST_FILES,
    CANONICAL_TEST_NODES,
    _junit_result,
    build_evidence,
    main,
    validate_evidence,
)


COMMIT = "a" * 40


def _write_native_fixture(tmp_path):
    native = tmp_path / "app" / "firewall" / "clumsy.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"hardware-native-fixture")
    provenance = tmp_path / "binary-provenance.json"
    provenance.write_text(
        json.dumps({
            "schema": "dupez.bundled-binaries.v1",
            "artifacts": [{
                "path": "app/firewall/clumsy.exe",
                "size": native.stat().st_size,
                "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            }],
        }),
        encoding="utf-8",
    )
    return native, provenance


def _write_passing_junit(tmp_path):
    cases = []
    for node in CANONICAL_TEST_NODES:
        test_file, _, test_name = node.partition("::")
        classname = test_file.removesuffix(".py").replace("/", ".")
        cases.append(
            f'    <testcase classname="{classname}" name="{test_name}" '
            f'file="{test_file}" />'
        )
    test_count = len(cases)
    junit = tmp_path / "hardware.junit.xml"
    junit.write_text(
        "\n".join([
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<testsuites tests="{test_count}" failures="0" '
            'errors="0" skipped="0">',
            f'  <testsuite name="hardware" tests="{test_count}" '
            'failures="0" errors="0" skipped="0">',
            *cases,
            "  </testsuite>",
            "</testsuites>",
        ]),
        encoding="utf-8",
    )
    return junit


def _set_github_hardware_context(monkeypatch) -> None:
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "GrihmLord/DupeZ",
        "GITHUB_WORKFLOW": "Hardware Smoketest",
        "GITHUB_WORKFLOW_REF": (
            "GrihmLord/DupeZ/.github/workflows/"
            "hardware-smoketest.yml@refs/heads/main"
        ),
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": COMMIT,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _build_fixture_evidence(tmp_path, monkeypatch):
    native, provenance = _write_native_fixture(tmp_path)
    junit = _write_passing_junit(tmp_path)
    _set_github_hardware_context(monkeypatch)
    evidence = build_evidence(
        junit_path=junit,
        commit=COMMIT,
        provenance_path=provenance,
        source_root=tmp_path,
        clumsy_processes_remaining=0,
    )
    return native, provenance, evidence


def test_hardware_junit_parser_accepts_normal_utf8(tmp_path) -> None:
    junit = _write_passing_junit(tmp_path)

    count, files, nodes = _junit_result(junit)

    assert count == len(CANONICAL_TEST_NODES)
    assert files == list(CANONICAL_TEST_FILES)
    assert nodes == list(CANONICAL_TEST_NODES)


def test_hardware_junit_parser_rejects_utf16_internal_entity_bypass(
    tmp_path,
) -> None:
    junit = tmp_path / "hardware.junit.xml"
    junit.write_bytes(
        """<?xml version="1.0" encoding="utf-16"?>
<!DoCtYpE testsuite [
  <!EnTiTy seed "expanded">
  <!EnTiTy payload "&seed;&seed;&seed;&seed;">
]>
<testsuite tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_unrelated" name="&payload;" />
</testsuite>""".encode("utf-16")
    )

    with pytest.raises(ValueError, match="must be strict UTF-8"):
        _junit_result(junit)


def test_hardware_evidence_binds_commit_tests_and_native_hashes(
    tmp_path, monkeypatch
) -> None:
    native, provenance, evidence = _build_fixture_evidence(
        tmp_path, monkeypatch
    )

    assert evidence["commit"] == COMMIT
    assert evidence["invocation"]["kind"] == "github-actions"
    assert evidence["invocation"]["head_sha"] == COMMIT
    assert evidence["tests"] == {
        "result": "passed",
        "count": len(CANONICAL_TEST_NODES),
        "files": list(CANONICAL_TEST_FILES),
        "node_ids": list(CANONICAL_TEST_NODES),
    }
    assert evidence["process_cleanup"] == {
        "measurement": "workflow-post-cleanup-owned-path-cim",
        "clumsy_processes_remaining": 0,
    }
    assert evidence["source_native_artifacts"] == [{
        "path": "app/firewall/clumsy.exe",
        "size": native.stat().st_size,
        "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
    }]
    assert "target_ip" not in json.dumps(evidence).casefold()
    assert validate_evidence(
        evidence,
        expected_commit=COMMIT,
        provenance_path=provenance,
        source_root=tmp_path,
    ) == []


def test_hardware_evidence_rejects_commit_native_and_privacy_tampering(
    tmp_path, monkeypatch
) -> None:
    _, provenance, evidence = _build_fixture_evidence(tmp_path, monkeypatch)
    evidence["commit"] = "b" * 40
    evidence["source_native_artifacts"][0]["sha256"] = "c" * 64
    evidence["target_ip"] = "redacted-fixture"

    errors = validate_evidence(
        evidence,
        expected_commit=COMMIT,
        provenance_path=provenance,
        source_root=tmp_path,
    )

    assert any("commit mismatch" in error for error in errors)
    assert any("native hashes" in error for error in errors)
    assert any("prohibited target identifiers" in error for error in errors)


def test_hardware_evidence_creation_rejects_local_context(
    tmp_path, monkeypatch
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = _write_passing_junit(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    with pytest.raises(ValueError, match="requires GitHub Actions"):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=0,
        )


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("GITHUB_REPOSITORY", "attacker/fork", "unexpected GitHub repository"),
        ("GITHUB_WORKFLOW", "Other Workflow", "unexpected GitHub workflow"),
        ("GITHUB_SHA", "b" * 40, "does not match GITHUB_SHA"),
    ),
)
def test_hardware_evidence_creation_rejects_wrong_github_identity(
    tmp_path, monkeypatch, variable, value, message
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = _write_passing_junit(tmp_path)
    _set_github_hardware_context(monkeypatch)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=0,
        )


def test_hardware_evidence_rejects_generic_one_test_junit(
    tmp_path, monkeypatch
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = tmp_path / "generic.junit.xml"
    junit.write_text(
        """<testsuite tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_unrelated" name="test_false_green" />
</testsuite>""",
        encoding="utf-8",
    )
    _set_github_hardware_context(monkeypatch)

    with pytest.raises(ValueError, match="exact canonical suite"):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=0,
        )


def test_hardware_evidence_rejects_unmeasured_cleanup_result(
    tmp_path, monkeypatch
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = _write_passing_junit(tmp_path)
    _set_github_hardware_context(monkeypatch)

    with pytest.raises(ValueError, match="process count must be zero"):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=1,
        )


def test_hardware_evidence_rejects_skipped_or_failed_junit(
    tmp_path, monkeypatch
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = tmp_path / "hardware.junit.xml"
    junit.write_text(
        """<testsuite tests="1" failures="0" errors="0" skipped="1">
  <testcase classname="tests.test_hardware" name="skipped">
    <skipped />
  </testcase>
</testsuite>""",
        encoding="utf-8",
    )
    _set_github_hardware_context(monkeypatch)

    with pytest.raises(ValueError, match="not a complete pass"):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=0,
        )


def test_hardware_evidence_rejects_junit_dtd_or_entities(
    tmp_path, monkeypatch
) -> None:
    _, provenance = _write_native_fixture(tmp_path)
    junit = tmp_path / "hardware.junit.xml"
    junit.write_text(
        """<?xml version="1.0"?>
<!DOCTYPE testsuite [<!ENTITY injected "test_false_green">]>
<testsuite tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_unrelated" name="&injected;" />
</testsuite>""",
        encoding="utf-8",
    )
    _set_github_hardware_context(monkeypatch)

    with pytest.raises(ValueError, match="must not contain DTDs or entities"):
        build_evidence(
            junit_path=junit,
            commit=COMMIT,
            provenance_path=provenance,
            source_root=tmp_path,
            clumsy_processes_remaining=0,
        )


def test_verify_native_cli_rejects_substitution(tmp_path, capsys) -> None:
    native, provenance = _write_native_fixture(tmp_path)

    assert main([
        "verify-native",
        "--provenance",
        str(provenance),
        "--source-root",
        str(tmp_path),
    ]) == 0
    assert "Hardware native provenance: PASS" in capsys.readouterr().out

    native.write_bytes(b"substituted-after-checkout")
    assert main([
        "verify-native",
        "--provenance",
        str(provenance),
        "--source-root",
        str(tmp_path),
    ]) == 2
    assert "mismatch" in capsys.readouterr().err


def test_hardware_workflow_holds_native_locks_through_evidence() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "hardware-smoketest.yml"
    ).read_text(encoding="utf-8")

    lock_index = workflow.index("[System.IO.FileShare]::Read")
    verify_index = workflow.index("scripts/hardware_evidence.py verify-native")
    test_index = workflow.index("-X faulthandler -m pytest")
    evidence_index = workflow.index("scripts/hardware_evidence.py create")
    dispose_index = workflow.index("$stream.Dispose()")

    assert lock_index < verify_index < test_index < evidence_index < dispose_index
    assert "Reparse points are forbidden in native hardware paths" in workflow
    assert "FileShare.ReadWrite" not in workflow
