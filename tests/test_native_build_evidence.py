"""Offline frozen archive evidence tests; all payloads are inert byte fixtures."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("native_build_evidence", ROOT / "scripts/native_build_evidence.py")
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _hash(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def build(tmp_path):
    source_root, venv, base, system = [tmp_path / name for name in ("source", "venv", "python", "system")]
    _write(venv / "pyvenv.cfg", f"home = {base}\ninclude-system-site-packages = false\n".encode())
    _write(venv / "Scripts/python.exe", b"inert-venv-python")
    _write(base / "python.exe", b"inert-base-python")
    payloads, rows = {}, []

    def add(name, source, origin, data=b"inert-native-bytes"):
        _write(source, data)
        payloads[name] = data
        rows.append({"destination": name, "source": str(source), "origin": origin,
                     "kind": "BINARY", "sha256": _hash(data)})

    managed = "app/firewall/driver.sys"
    add(managed, source_root / managed, "managed-native", b"inert-pinned-driver")
    # Real managed build inputs are temporary validated snapshots, deleted on exit.
    rows[0]["source"] = str(tmp_path / "deleted-snapshot/driver.sys")
    add("libssl-3.dll", base / "DLLs/libssl-3.dll", "verified-base-python")
    add("libcrypto-3.dll", base / "DLLs/libcrypto-3.dll", "verified-base-python")
    add("PyQt6/Qt6/plugins/tls/qschannelbackend.dll",
        venv / "Lib/site-packages/PyQt6/Qt6/plugins/tls/qschannelbackend.dll", "locked-build-venv")
    add("extension.pyd", venv / "Lib/site-packages/extension.pyd", "locked-build-venv")
    add("system.dll", system / "system.dll", "windows-system32")
    provenance = {"schema": "dupez.bundled-binaries.v1", "artifacts": [
        {"path": managed, "sha256": _hash(payloads[managed]), "size": len(payloads[managed])}]}
    _write(source_root / "packaging/binary-provenance.json", json.dumps(provenance).encode())
    _write(source_root / "packaging/release-data.json", json.dumps(
        {"schema": "dupez.release-data.v1", "binaries": [managed]}).encode())
    artifact = _write(tmp_path / "DupeZ.exe", b"inert-not-an-executable")
    manifest = tmp_path / "native-binaries.json"
    table = {name: (0, len(data), len(data), 0, "b") for name, data in payloads.items()}
    table["PYZ.pyz"] = (0, 1, 1, 0, "z")

    class Archive:
        def __init__(self, filename):
            assert filename == str(artifact)
            self.toc = table
            self._start_offset = 0

        def extract(self, name):
            return payloads[name]

    def inspect():
        manifest.write_text(json.dumps({"schema": "dupez.native-binary-origins.v1",
                                       "qt_tls_policy": "schannel-only", "binaries": rows}), encoding="utf-8")
        return evidence.inspect_native_build(artifact=artifact, manifest=manifest, source_root=source_root,
                                             build_venv=venv, python_base=base, system_directory=system,
                                             archive_reader_cls=Archive)

    return SimpleNamespace(inspect=inspect, add=add, artifact=artifact, manifest=manifest, source_root=source_root,
                           venv=venv, base=base, system=system, rows=rows, payloads=payloads, table=table,
                           tmp_path=tmp_path, managed=managed)


def test_success_is_sanitized_non_approval_and_deterministic(build):
    report = build.inspect()
    assert report == build.inspect()
    assert report["schema"] == "dupez.native-build-observation.v1"
    assert report["disposition"] == "offline-local-byte-observation-not-release-approval"
    assert report["native_entry_count"] == 6
    assert report["origin_counts"] == {"managed-native": 1, "verified-base-python": 2,
                                       "locked-build-venv": 2, "windows-system32": 1}
    assert report["artifact"]["sha256"] == _hash(build.artifact.read_bytes())
    assert str(build.tmp_path) not in json.dumps(report)
    assert len(report["native_inventory_sha256"]) == 64


@pytest.mark.parametrize("compressed", [False, True])
def test_windows_type_b_data_is_not_misclassified_as_native(build, compressed):
    data = b"ordinary-QML-text"
    raw = zlib.compress(data) if compressed else data
    build.artifact.write_bytes(raw)
    build.table["ordinary.qml"] = (0, len(raw), len(data), int(compressed), "b")
    assert build.inspect()["native_entry_count"] == 6


@pytest.mark.parametrize("compressed", [False, True])
def test_unreported_renamed_mz_payload_is_rejected(build, compressed):
    data = b"MZ-inert-unreported-native-signature"
    raw = zlib.compress(data) if compressed else data
    build.artifact.write_bytes(raw)
    build.table["unexpected.dat"] = (0, len(raw), len(data), int(compressed), "b")
    with pytest.raises(ValueError, match="inventory differs"):
        build.inspect()


@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate_case", "data_native", "oversize"])
def test_archive_inventory_and_native_types_fail_closed(build, mutation):
    if mutation == "extra":
        build.table["extra.dll"] = (0, 1, 1, 0, "b")
    elif mutation == "missing":
        del build.table["extension.pyd"]
    elif mutation == "duplicate_case":
        build.table["EXTENSION.PYD"] = build.table["extension.pyd"]
    elif mutation == "data_native":
        build.table["extension.pyd"] = (0, 18, 18, 0, "x")
    else:
        build.table["extension.pyd"] = (0, 1, 1024 * 1024 * 1024 + 1, 0, "b")
    with pytest.raises(ValueError):
        build.inspect()


@pytest.mark.parametrize("mutation", ["duplicate", "false_origin", "invalid_digest", "invalid_kind", "extra_key"])
def test_manifest_rows_fail_closed(build, mutation):
    row = build.rows[-1]
    if mutation == "duplicate":
        build.rows.append(dict(row, destination=row["destination"].upper()))
    elif mutation == "false_origin":
        row["origin"] = "verified-base-python"
    elif mutation == "invalid_digest":
        row["sha256"] = "not-a-hash"
    elif mutation == "invalid_kind":
        row["kind"] = "DATA"
    else:
        row["unexpected"] = True
    with pytest.raises(ValueError):
        build.inspect()


@pytest.mark.parametrize("name", ["qopensslbackend.dll", "qcertonlybackend.dll", "libssl-3-x64.dll",
                                  "PyQt6/Qt6/plugins/tls/newbackend.dll"])
def test_forbidden_and_unreviewed_tls_payloads_fail_closed(build, name):
    build.add(name, build.venv / name, "locked-build-venv")
    build.table[name] = (0, len(build.payloads[name]), len(build.payloads[name]), 0, "b")
    with pytest.raises(ValueError, match="Forbidden|Unreviewed|OpenSSL"):
        build.inspect()


def test_ambient_source_and_prefix_lookalike_fail_closed(build):
    row = build.rows[-1]
    row["source"] = str(_write(build.tmp_path / "venv-unrelated/system.dll", build.payloads["system.dll"]))
    with pytest.raises(ValueError, match="Ambient"):
        build.inspect()


@pytest.mark.parametrize("target", ["libssl-3.dll", "PyQt6/Qt6/plugins/tls/qschannelbackend.dll"])
def test_same_bytes_wrong_tls_source_are_not_accepted(build, target):
    row = next(row for row in build.rows if row["destination"] == target)
    row["source"] = str(_write(build.venv / "wrong-source" / Path(target).name, build.payloads[target]))
    row["origin"] = "locked-build-venv"
    with pytest.raises(ValueError, match="OpenSSL|Schannel"):
        build.inspect()


@pytest.mark.parametrize("target", ["archive", "source", "managed_original", "managed_pin"])
def test_independent_byte_comparisons_reject_tampering(build, target):
    if target == "archive":
        build.payloads["extension.pyd"] = b"other-native-bytes!"
    elif target == "source":
        Path(build.rows[-1]["source"]).write_bytes(b"different-source")
    elif target == "managed_original":
        (build.source_root / build.managed).write_bytes(b"different-managed-original")
    else:
        pin = build.source_root / "packaging/binary-provenance.json"
        document = json.loads(pin.read_text())
        document["artifacts"][0]["sha256"] = "0" * 64
        pin.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="bytes|size|source"):
        build.inspect()


def test_wrong_venv_base_is_rejected(build):
    (build.venv / "pyvenv.cfg").write_text(f"home = {build.venv}\n")
    with pytest.raises(ValueError, match="base Python"):
        build.inspect()


@pytest.mark.parametrize("destination", ["../outside.dll", "/absolute.dll", "C:/escape.dll", "a//b.dll",
                                         "a/./b.dll", "a\\..\\b.dll", "a\x00b.dll"])
def test_unsafe_archive_destinations_are_rejected(destination):
    with pytest.raises(ValueError):
        evidence._destination(destination)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"one","schema":"two"}')
    with pytest.raises(ValueError, match="duplicate keys"):
        evidence._json(path)


def test_cli_writes_exclusive_sanitized_summary(tmp_path, monkeypatch, capsys):
    output = tmp_path / "result.json"
    args = ["inspector", "--artifact", "artifact", "--manifest", "manifest", "--source-root", "root",
            "--build-venv", "venv", "--python-base", "base", "--output", str(output)]
    monkeypatch.setattr(evidence.sys, "argv", args)
    monkeypatch.setattr(evidence, "inspect_native_build", lambda **kwargs: {"disposition": "not-approval"})
    assert evidence.main() == 0
    original = output.read_bytes()
    assert evidence.main() == 1
    assert output.read_bytes() == original
    assert str(tmp_path) not in capsys.readouterr().out
