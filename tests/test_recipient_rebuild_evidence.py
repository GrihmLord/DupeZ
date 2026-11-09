import json
import zipfile

import pytest

from scripts.recipient_rebuild_evidence import MARKER, build_observation, fingerprint


@pytest.fixture
def inputs(tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.comment = b"a" * 40
        for name in ("dupez.py", "app/__version__.py", "requirements-locked.txt"):
            bundle.writestr(name, "fixture")
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"non-executable test fixture")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"check": "runtime-imports", "ok": True}))
    return dict(archive=archive, commit="a" * 40, artifact=artifact, report=report,
                variant="gpu", exit_code=0, modified=False, inputs=[])


def test_observation_binds_bytes_without_claiming_release(inputs):
    value = build_observation(**inputs)
    assert value["disposition"] == "local-operator-observation-not-release-approval"
    assert value["artifact"] == fingerprint(inputs["artifact"])
    assert value["source_commit"] == "a" * 40
    assert len(value["limitations"]) == 3
    assert str(inputs["archive"].parent) not in json.dumps(value)


def test_official_prefixed_source_archive_is_accepted(inputs):
    with zipfile.ZipFile(inputs["archive"], "w") as bundle:
        bundle.comment = b"a" * 40
        bundle.writestr("DupeZ-v5.8.0/", "")
        for name in ("dupez.py", "app/__version__.py", "requirements-locked.txt"):
            bundle.writestr("DupeZ-v5.8.0/" + name, "fixture")
    assert build_observation(**inputs)["source_prefix"] == "DupeZ-v5.8.0/"


@pytest.mark.parametrize("extra", ["DupeZ-v5.8.0/dupez.py", "DUPEZ.PY"])
def test_mixed_or_case_colliding_source_roots_reject(inputs, extra):
    with zipfile.ZipFile(inputs["archive"], "a") as bundle:
        bundle.writestr(extra, "fixture")
    with pytest.raises(ValueError):
        build_observation(**inputs)


@pytest.mark.parametrize("changes", [
    {"commit": "b" * 40}, {"commit": "HEAD"}, {"exit_code": 1},
    {"exit_code": False}, {"variant": "other"}, {"modified": True},
])
def test_bad_identity_or_unproven_scenario_rejects(inputs, changes):
    inputs.update(changes)
    with pytest.raises(ValueError):
        build_observation(**inputs)


@pytest.mark.parametrize("result", [
    {"check": "runtime-imports", "ok": False},
    {"check": "runtime-imports", "ok": 1},
    {"check": "self", "ok": True},
    {"check": "runtime-imports", "ok": True, "unexpected_field": "unexpected"},
])
def test_wrong_report_rejects(inputs, result):
    inputs["report"].write_text(json.dumps(result))
    with pytest.raises(ValueError):
        build_observation(**inputs)


def test_modified_python_library_proof_requires_both_runtime_markers(inputs, tmp_path):
    inputs["modified"] = True
    inputs["report"].write_text(json.dumps({"check": "runtime-imports", "ok": True,
        "application_marker": MARKER, "library_marker": MARKER}))
    files = [tmp_path / name for name in ("__version__.py", "__init__.py", "dupez.py")]
    for path in files:
        path.write_text("recipient modification fixture")
    inputs["inputs"] = files
    value = build_observation(**inputs)
    assert value["scenario"] == "modified-application-and-zeroconf-python-layer"
    assert len(value["additional_inputs"]) == 3


def test_empty_or_non_regular_evidence_rejects(tmp_path):
    with pytest.raises(ValueError):
        fingerprint(tmp_path)
    empty = tmp_path / "empty"
    empty.touch()
    with pytest.raises(ValueError):
        fingerprint(empty)


def test_observation_does_not_spawn_a_process(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Evidence recording must not execute binaries")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    assert build_observation(**inputs)["observed_exit_code"] == 0
