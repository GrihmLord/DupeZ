"""Private runtime staging admits exact inert files, never ambient DLL roots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import msvc_runtime_stage as staging


def make_verified_inputs(root: Path):
    """Small inert package-output fixture; no native files or process execution."""
    root.mkdir(parents=True, exist_ok=True)
    verified = root / "verified"
    (verified / "dlls").mkdir(parents=True)
    rows = []
    for name in staging.NAMES:
        data = b"inert-msvc-fixture-" + name.encode()
        row = {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
               "cabinet_member": name.lower() + "_amd64"}
        (verified / "dlls" / row["cabinet_member"]).write_bytes(data)
        rows.append(row)
    package = {"filename": "VC_redist.x64.exe", "size": 123, "sha256": "a" * 64,
               "version": "14.51.36247.0", "signer_thumbprint": "B" * 40}
    manifest = {"schema": "dupez.msvc-redist-inputs.v1", "package": package, "binaries": rows,
                "release_approved": False, "distribution_approved": False}
    manifest_path = root / "msvc-redist-inputs.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_bytes = manifest_path.read_bytes()
    upstream = {"schema": "dupez.msvc-redist-provenance.v1", "status": "exact-upstream-package-bytes-verified",
                "manifest": {"size": len(manifest_bytes), "sha256": hashlib.sha256(manifest_bytes).hexdigest()},
                "package": package, "binaries": [{**row, "origin": "pinned-microsoft-redist-minimum-x64-cabinet"} for row in rows],
                "signature_observations": [{"name": name, "status": "Valid", "subject": "O=Microsoft Corporation",
                                            "file_version": package["version"], "thumbprint": package["signer_thumbprint"]}
                                           for name in ("package", *staging.NAMES)],
                "consumed_artifacts": [{"path": "dlls/" + row["cabinet_member"], "size": row["size"], "sha256": row["sha256"]}
                                       for row in rows],
                **{key: False for key in ("release_approved", "distribution_approved", "installer_executed",
                                          "global_installation_performed", "elevation_requested")}}
    receipt = verified / "receipt.json"
    receipt.write_text(json.dumps(upstream), encoding="utf-8")
    return SimpleNamespace(root=root, verified=verified, manifest=manifest_path, manifest_data=manifest,
                           upstream=upstream, receipt=receipt, output=root / "msvc-runtime")


@pytest.fixture
def inputs(tmp_path):
    return make_verified_inputs(tmp_path)


def test_stage_is_closed_exact_byte_mapping_and_has_no_approval(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Staging must not spawn a process or execute an installer")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    result = staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    assert result == staging.validate_stage(inputs.output, inputs.manifest)
    assert {p.name for p in inputs.output.iterdir()} == {*staging.NAMES, "stage-receipt.json", "upstream-receipt.json"}
    assert (inputs.output / "upstream-receipt.json").read_bytes() == inputs.receipt.read_bytes()
    for row in result["binaries"]:
        assert Path(row["source"]).parent == inputs.output
        assert Path(row["source"]).read_bytes() == (inputs.verified / "dlls" / (row["name"].lower() + "_amd64")).read_bytes()
    public = (inputs.output / "stage-receipt.json").read_text()
    assert str(inputs.root) not in public
    assert json.loads(public)["release_approved"] is False


@pytest.mark.parametrize("mutation", ["manifest", "package", "mapping", "signature", "signer", "consumed", "approved", "executed", "duplicate"])
def test_unreviewed_or_contradictory_upstream_receipts_reject_before_output(inputs, mutation):
    value = inputs.upstream
    if mutation == "manifest": value["manifest"]["sha256"] = "0" * 64
    if mutation == "package": value["package"] = {**value["package"], "sha256": "0" * 64}
    if mutation == "mapping": value["binaries"][0]["origin"] = "caller-supplied"
    if mutation == "signature": value["signature_observations"][1]["status"] = "NotSigned"
    if mutation == "signer": value["signature_observations"][0]["thumbprint"] = "C" * 40
    if mutation == "consumed": value["consumed_artifacts"][0]["sha256"] = "0" * 64
    if mutation == "approved": value["distribution_approved"] = True
    if mutation == "executed": value["installer_executed"] = True
    if mutation == "duplicate": value["signature_observations"].append(value["signature_observations"][0])
    inputs.receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    assert not inputs.output.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "directory", "case", "bytes", "receipt", "upstream", "duplicate_json", "boolean_as_int", "size_as_float"])
def test_stage_inventory_pins_and_receipts_are_revalidated(inputs, mutation):
    staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    path = inputs.output / staging.NAMES[0]
    if mutation == "missing": path.unlink()
    if mutation == "extra": (inputs.output / "ambient.dll").write_bytes(b"unexpected")
    if mutation == "directory": (inputs.output / "plugins").mkdir()
    if mutation == "case": path.rename(inputs.output / "wrong.dll")
    if mutation == "bytes": path.write_bytes(b"different-runtime-version")
    if mutation == "receipt":
        receipt = inputs.output / "stage-receipt.json"
        value = json.loads(receipt.read_text())
        value["package"]["sha256"] = "0" * 64
        receipt.write_text(json.dumps(value))
    if mutation in {"boolean_as_int", "size_as_float"}:
        receipt = inputs.output / "stage-receipt.json"
        value = json.loads(receipt.read_text())
        if mutation == "boolean_as_int": value["release_approved"] = 0
        else: value["binaries"][0]["size"] = float(value["binaries"][0]["size"])
        receipt.write_text(json.dumps(value))
    if mutation == "upstream": (inputs.output / "upstream-receipt.json").write_text("{}")
    if mutation == "duplicate_json":
        receipt = inputs.output / "stage-receipt.json"
        receipt.write_text('{"schema":"wrong",' + receipt.read_text()[1:])
    with pytest.raises(ValueError):
        staging.validate_stage(inputs.output, inputs.manifest)


def test_staging_rejects_stale_extracted_bytes_and_existing_output(inputs):
    path = inputs.verified / "dlls" / inputs.manifest_data["binaries"][0]["cabinet_member"]
    original = path.read_bytes()
    path.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="extracted DLL"):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    path.write_bytes(original)
    inputs.output.mkdir()
    with pytest.raises(ValueError, match="must be new"):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)


def test_consumed_source_mutation_never_issues_stage_receipt(inputs, monkeypatch):
    original = staging._snapshot
    calls = 0
    def mutate(path, limit=staging.MAX_FILE):
        nonlocal calls
        if Path(path) == inputs.receipt:
            calls += 1
            if calls == 2:
                inputs.receipt.write_text("{}")
        return original(path, limit)
    monkeypatch.setattr(staging, "_snapshot", mutate)
    with pytest.raises(ValueError, match="source changed"):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    assert not (inputs.output / "stage-receipt.json").exists()


def test_validation_rechecks_earlier_dll_bytes(inputs, monkeypatch):
    staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    original = staging._snapshot
    victim = inputs.output / staging.NAMES[0]
    calls = 0
    def mutate(path, limit=staging.MAX_FILE):
        nonlocal calls
        if Path(path) == victim:
            calls += 1
            if calls == 2:
                victim.write_bytes(b"mutated")
        return original(path, limit)
    monkeypatch.setattr(staging, "_snapshot", mutate)
    with pytest.raises(ValueError, match="changed during validation"):
        staging.validate_stage(inputs.output, inputs.manifest)


def test_hard_linked_stage_is_rejected(inputs):
    staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
    try:
        os.link(inputs.output / staging.NAMES[0], inputs.root / "aliased.dll")
    except OSError as error:
        pytest.skip(f"Hard links unavailable: {error}")
    with pytest.raises(ValueError, match="hard links"):
        staging.validate_stage(inputs.output, inputs.manifest)


def test_reparse_marker_is_rejected_without_following_it(inputs, monkeypatch):
    original = Path.lstat
    def reparse(path):
        result = original(path)
        if path == inputs.verified:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="reparse"):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)


def test_oversized_receipt_is_rejected_before_parsing(inputs):
    inputs.receipt.write_bytes(b"x" * (staging.MAX_JSON + 1))
    with pytest.raises(ValueError, match="size bound"):
        staging.prepare_stage(inputs.verified, inputs.output, inputs.manifest)
