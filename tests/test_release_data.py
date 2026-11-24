from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGING_DIR = ROOT / "packaging"
sys.path.insert(0, str(PACKAGING_DIR))
try:
    import release_data
finally:
    sys.path.remove(str(PACKAGING_DIR))


SIGNER = "a" * 64


def test_compile_installer_entrypoint_imports_under_isolated_mode() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(PACKAGING_DIR / "compile_installer.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--mode" in completed.stdout
    assert "--iscc" in completed.stdout


def _unsigned_pe(marker: bytes = b"reviewed-clumsy") -> bytes:
    payload = bytearray(512)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x80 + 20, 0xE0)
    optional = 0x80 + 24
    struct.pack_into("<H", payload, optional, 0x10B)
    struct.pack_into("<I", payload, optional + 64, 0x12345678)
    struct.pack_into("<I", payload, optional + 92, 16)
    payload[-len(marker):] = marker
    return bytes(payload)


def _authenticode_signed(source: bytes) -> bytes:
    payload = bytearray(source)
    pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
    optional = pe_offset + 24
    security = optional + 96 + (4 * 8)
    while len(payload) % 8:
        payload.append(0)
    certificate_offset = len(payload)
    certificate = struct.pack("<IHH", 16, 0x200, 0x0002) + b"sigbytes"
    payload.extend(certificate)
    struct.pack_into("<I", payload, optional + 64, 0x87654321)
    struct.pack_into("<II", payload, security, certificate_offset, len(certificate))
    return bytes(payload)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_repository(tmp_path: Path) -> tuple[Path, Path, Path, bytes, bytes]:
    root = tmp_path / "repo"
    firewall = root / "app" / "firewall"
    firewall.mkdir(parents=True)
    clumsy = _unsigned_pe()
    iup = b"reviewed-iup-native"
    (firewall / "clumsy.exe").write_bytes(clumsy)
    (firewall / "iup.dll").write_bytes(iup)

    manifest = tmp_path / "release-data.json"
    manifest.write_text(
        json.dumps({
            "schema": release_data.MANIFEST_SCHEMA,
            "files": ["app/config/settings.json"],
            "binaries": [
                "app/firewall/clumsy.exe",
                "app/firewall/iup.dll",
            ],
        }),
        encoding="utf-8",
    )
    provenance = tmp_path / "binary-provenance.json"
    provenance.write_text(
        json.dumps({
            "schema": release_data.SOURCE_PROVENANCE_SCHEMA,
            "artifacts": [
                {
                    "path": "app/firewall/clumsy.exe",
                    "size": len(clumsy),
                    "sha256": _sha256(clumsy),
                    "version": "0.3.4",
                    "source": "https://example.invalid/clumsy",
                    "source_commit": "1" * 40,
                },
                {
                    "path": "app/firewall/iup.dll",
                    "size": len(iup),
                    "sha256": _sha256(iup),
                    "version": "3.30",
                    "source": "https://example.invalid/iup",
                },
            ],
        }),
        encoding="utf-8",
    )
    return root, manifest, provenance, clumsy, iup


def _prepare(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, bytes, bytes]:
    root, manifest, provenance, clumsy, iup = _write_repository(tmp_path)
    stage = release_data.prepare_native_stage(
        root,
        manifest_path=manifest,
        provenance_path=provenance,
    )
    return root, stage, manifest, provenance, clumsy, iup


def _valid_signature(_path: Path) -> tuple[str, str]:
    return "Valid", SIGNER


def test_prepare_replaces_only_a_safe_exact_native_stage(tmp_path) -> None:
    root, manifest, provenance, clumsy, iup = _write_repository(tmp_path)
    stale = root / "build" / "release-native"
    stale.mkdir(parents=True)
    (stale / "stale.bin").write_bytes(b"stale")

    stage = release_data.prepare_native_stage(
        root,
        manifest_path=manifest,
        provenance_path=provenance,
    )

    assert stage == root / "build" / "release-native"
    assert not (stage / "stale.bin").exists()
    assert (stage / "app" / "firewall" / "clumsy.exe").read_bytes() == clumsy
    assert (stage / "app" / "firewall" / "iup.dll").read_bytes() == iup


def test_prepare_rejects_reparse_component_before_cleanup(
    tmp_path, monkeypatch
) -> None:
    root, manifest, provenance, _clumsy, _iup = _write_repository(tmp_path)
    build = root / "build"
    stage = build / "release-native"
    stage.mkdir(parents=True)
    sentinel = stage / "must-survive.txt"
    sentinel.write_text("sentinel", encoding="utf-8")
    original = release_data._is_reparse_point
    monkeypatch.setattr(
        release_data,
        "_is_reparse_point",
        lambda path: path == build or original(path),
    )
    monkeypatch.setattr(
        shutil,
        "rmtree",
        lambda _path: pytest.fail("unsafe stage cleanup was attempted"),
    )

    with pytest.raises(ValueError, match="reparse point"):
        release_data.prepare_native_stage(
            root,
            manifest_path=manifest,
            provenance_path=provenance,
        )

    assert sentinel.read_text(encoding="utf-8") == "sentinel"


def test_prepare_rejects_real_symlink_escape_when_supported(tmp_path) -> None:
    root, manifest, provenance, _clumsy, _iup = _write_repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "must-survive.txt"
    sentinel.write_text("sentinel", encoding="utf-8")
    try:
        (root / "build").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")

    with pytest.raises(ValueError, match="reparse point"):
        release_data.prepare_native_stage(
            root,
            manifest_path=manifest,
            provenance_path=provenance,
        )

    assert sentinel.read_text(encoding="utf-8") == "sentinel"


def test_explicit_unsigned_finalize_verify_and_tampering(tmp_path) -> None:
    root, stage, manifest, provenance, _clumsy, _iup = _prepare(tmp_path)
    unsigned = lambda _path: ("NotSigned", None)
    output = release_data.finalize_native_stage(
        root,
        release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=unsigned,
    )

    payload = release_data.verify_native_stage(
        root,
        expected_mode=release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=unsigned,
    )
    assert output.is_file()
    assert payload["release_mode"] == release_data.UNSIGNED_MODE
    assert all(
        artifact["transform"] == "source-exact"
        for artifact in payload["artifacts"]
    )

    (stage / "app" / "firewall" / "iup.dll").write_bytes(b"substitution")
    with pytest.raises(ValueError, match="does not match provenance"):
        release_data.verify_native_stage(
            root,
            expected_mode=release_data.UNSIGNED_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=unsigned,
        )


def test_unsigned_finalize_rejects_changed_clumsy(tmp_path) -> None:
    root, stage, manifest, provenance, clumsy, _iup = _prepare(tmp_path)
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(clumsy + b"x")

    with pytest.raises(ValueError, match="unsigned staged binary changed"):
        release_data.finalize_native_stage(
            root,
            release_data.UNSIGNED_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=lambda _path: ("NotSigned", None),
        )


def test_standard_finalize_accepts_only_authenticode_equivalent_pinned_signer(
    tmp_path,
) -> None:
    root, stage, manifest, provenance, clumsy, _iup = _prepare(tmp_path)
    signed = _authenticode_signed(clumsy)
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(signed)

    output = release_data.finalize_native_stage(
        root,
        release_data.STANDARD_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
        expected_signer_certificate_sha256=SIGNER,
    )
    payload = release_data.verify_native_stage(
        root,
        expected_mode=release_data.STANDARD_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
        expected_signer_certificate_sha256=SIGNER,
    )

    clumsy_record = next(
        item
        for item in payload["artifacts"]
        if item["path"] == release_data.CLUMSY_PATH
    )
    assert output.is_file()
    assert clumsy_record["sha256"] == _sha256(signed)
    assert clumsy_record["source_sha256"] == _sha256(clumsy)
    assert clumsy_record["source_equivalence"] == (
        release_data.AUTHENTICODE_TRANSFORM
    )
    assert payload["signer_certificate_sha256"] == SIGNER

    tampered = bytearray(signed)
    tampered[-1] ^= 0x01
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(tampered)
    with pytest.raises(ValueError, match="does not match provenance"):
        release_data.verify_native_stage(
            root,
            expected_mode=release_data.STANDARD_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=_valid_signature,
            expected_signer_certificate_sha256=SIGNER,
        )


def test_standard_lifecycle_records_and_reuses_measured_signer_without_env_pin(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv(release_data.EXPECTED_SIGNER_ENV, raising=False)
    root, stage, manifest, provenance, clumsy, _iup = _prepare(tmp_path)
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(
        _authenticode_signed(clumsy)
    )

    output = release_data.finalize_native_stage(
        root,
        release_data.STANDARD_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
    )
    measured = json.loads(output.read_text(encoding="utf-8"))
    assert measured["signer_certificate_sha256"] == SIGNER
    verified = release_data.verify_native_stage(
        root,
        expected_mode=release_data.STANDARD_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
    )
    assert verified["signer_certificate_sha256"] == SIGNER
    monkeypatch.setenv("DUPEZ_RELEASE_MODE", release_data.STANDARD_MODE)
    binaries = release_data.pyinstaller_binaries(
        str(root),
        stage_root=stage,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
    )
    assert {Path(source).name for source, _destination in binaries} == {
        "clumsy.exe",
        "iup.dll",
    }


def test_standard_cli_prepare_finalize_verify_needs_no_external_signer_pin(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv(release_data.EXPECTED_SIGNER_ENV, raising=False)
    root, manifest, provenance, clumsy, _iup = _write_repository(tmp_path)
    original_prepare = release_data.prepare_native_stage
    original_finalize = release_data.finalize_native_stage
    original_verify = release_data.verify_native_stage
    monkeypatch.setattr(release_data, "HERE", root / "packaging")
    monkeypatch.setattr(
        release_data,
        "prepare_native_stage",
        lambda cli_root: original_prepare(
            cli_root,
            manifest_path=manifest,
            provenance_path=provenance,
        ),
    )
    monkeypatch.setattr(
        release_data,
        "finalize_native_stage",
        lambda cli_root, mode: original_finalize(
            cli_root,
            mode,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=_valid_signature,
        ),
    )
    monkeypatch.setattr(
        release_data,
        "verify_native_stage",
        lambda cli_root, expected_mode: original_verify(
            cli_root,
            expected_mode=expected_mode,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=_valid_signature,
        ),
    )

    monkeypatch.setattr(sys, "argv", ["release_data.py", "prepare"])
    assert release_data.main() == 0
    stage = root / release_data.NATIVE_STAGE_RELATIVE
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(
        _authenticode_signed(clumsy)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_data.py",
            "finalize",
            "--mode",
            release_data.STANDARD_MODE,
        ],
    )
    assert release_data.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_data.py",
            "verify",
            "--mode",
            release_data.STANDARD_MODE,
        ],
    )
    assert release_data.main() == 0


def test_standard_finalize_rejects_validly_signed_substitution(tmp_path) -> None:
    root, stage, manifest, provenance, _clumsy, _iup = _prepare(tmp_path)
    substituted = _authenticode_signed(_unsigned_pe(b"different-program"))
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(substituted)

    with pytest.raises(ValueError, match="not source-equivalent"):
        release_data.finalize_native_stage(
            root,
            release_data.STANDARD_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=_valid_signature,
            expected_signer_certificate_sha256=SIGNER,
        )


def test_standard_finalize_and_verify_reject_wrong_signer(tmp_path) -> None:
    root, stage, manifest, provenance, clumsy, _iup = _prepare(tmp_path)
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(
        _authenticode_signed(clumsy)
    )

    with pytest.raises(ValueError, match="pinned release signer"):
        release_data.finalize_native_stage(
            root,
            release_data.STANDARD_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=lambda _path: ("Valid", "b" * 64),
            expected_signer_certificate_sha256=SIGNER,
        )


def test_verify_recomputes_signed_transform_and_rejects_manifest_tampering(
    tmp_path,
) -> None:
    root, stage, manifest, provenance, clumsy, _iup = _prepare(tmp_path)
    (stage / "app" / "firewall" / "clumsy.exe").write_bytes(
        _authenticode_signed(clumsy)
    )
    output = release_data.finalize_native_stage(
        root,
        release_data.STANDARD_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=_valid_signature,
        expected_signer_certificate_sha256=SIGNER,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["signer_certificate_sha256"] = "b" * 64
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="pinned release signer"):
        release_data.verify_native_stage(
            root,
            expected_mode=release_data.STANDARD_MODE,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=_valid_signature,
            expected_signer_certificate_sha256=SIGNER,
        )


def test_pyinstaller_binaries_use_verified_snapshot_and_reject_later_tamper(
    tmp_path, monkeypatch
) -> None:
    root, stage, manifest, provenance, _clumsy, iup = _prepare(tmp_path)
    release_data.finalize_native_stage(
        root,
        release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
    )
    monkeypatch.setenv("DUPEZ_RELEASE_MODE", release_data.UNSIGNED_MODE)
    binaries = release_data.pyinstaller_binaries(
        str(root),
        stage_root=stage,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
    )

    by_name = {Path(source).name: Path(source) for source, _dest in binaries}
    assert stage not in by_name["iup.dll"].parents
    assert by_name["iup.dll"].read_bytes() == iup
    (stage / "app" / "firewall" / "iup.dll").write_bytes(b"tampered later")
    assert by_name["iup.dll"].read_bytes() == iup
    with pytest.raises(ValueError, match="does not match provenance"):
        release_data.pyinstaller_binaries(
            str(root),
            stage_root=stage,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=lambda _path: ("NotSigned", None),
        )


def test_pyinstaller_binaries_reject_tampered_tracked_source(tmp_path) -> None:
    root, manifest, provenance, _clumsy, _iup = _write_repository(tmp_path)
    (root / "app" / "firewall" / "iup.dll").write_bytes(b"substitution")

    with pytest.raises(ValueError, match="source binary size mismatch"):
        release_data.pyinstaller_binaries(
            str(root),
            manifest_path=manifest,
            provenance_path=provenance,
        )


def test_emit_uses_verified_payload_not_reread_manifest(
    tmp_path, monkeypatch
) -> None:
    root, stage, manifest, provenance, _clumsy, _iup = _prepare(tmp_path)
    release_data.finalize_native_stage(
        root,
        release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
    )
    original = release_data.verify_native_stage

    def verify_then_replace(*args, **kwargs):
        payload = original(
            *args,
            manifest_path=manifest,
            provenance_path=provenance,
            **kwargs,
        )
        (stage / release_data.NATIVE_STAGE_MANIFEST).write_text(
            '{"forged": true}',
            encoding="utf-8",
        )
        return payload

    monkeypatch.setattr(
        release_data,
        "verify_native_stage",
        verify_then_replace,
    )
    output = tmp_path / "dist-binary-provenance.json"
    release_data.write_distribution_provenance(
        root,
        output,
        expected_mode=release_data.UNSIGNED_MODE,
        stage_root=stage,
        signature_inspector=lambda _path: ("NotSigned", None),
    )

    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["schema"] == release_data.DIST_PROVENANCE_SCHEMA
    assert "forged" not in emitted


def test_installer_compiler_receives_only_verified_private_snapshot(
    tmp_path,
) -> None:
    root, stage, manifest, provenance, _clumsy, iup = _prepare(tmp_path)
    release_data.finalize_native_stage(
        root,
        release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
    )
    installer_definition = root / "packaging" / "installer.iss"
    installer_definition.parent.mkdir()
    installer_definition.write_text("[Setup]\n", encoding="utf-8")
    observed: dict[str, Path] = {}

    class SuccessfulCompiler:
        returncode = 0

    def inspect_compiler(command, **kwargs):
        snapshot = Path(
            kwargs["env"][release_data.INSTALLER_NATIVE_SNAPSHOT_ENV]
        )
        observed["snapshot"] = snapshot
        assert snapshot != stage
        assert stage not in snapshot.parents
        assert command == ["ISCC.exe", str(installer_definition.resolve())]
        assert kwargs["cwd"] == str(root.resolve())
        assert kwargs["check"] is False
        assert kwargs["shell"] is False
        snapshotted_iup = snapshot / "app" / "firewall" / "iup.dll"
        assert snapshotted_iup.read_bytes() == iup

        # A later mutation of the public build stage cannot affect ISCC input.
        (stage / "app" / "firewall" / "iup.dll").write_bytes(b"later")
        assert snapshotted_iup.read_bytes() == iup
        return SuccessfulCompiler()

    release_data.compile_installer(
        root,
        expected_mode=release_data.UNSIGNED_MODE,
        iscc="ISCC.exe",
        installer_definition=installer_definition,
        runner=inspect_compiler,
        stage_root=stage,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
        tool_verifier=lambda _name, path: Path(path),
    )

    assert not observed["snapshot"].exists()


def test_installer_compiler_rejects_snapshot_mutation(tmp_path) -> None:
    root, stage, manifest, provenance, _clumsy, _iup = _prepare(tmp_path)
    release_data.finalize_native_stage(
        root,
        release_data.UNSIGNED_MODE,
        manifest_path=manifest,
        provenance_path=provenance,
        signature_inspector=lambda _path: ("NotSigned", None),
    )
    observed: dict[str, Path] = {}

    class SuccessfulCompiler:
        returncode = 0

    def mutate_snapshot(_command, **kwargs):
        snapshot = Path(
            kwargs["env"][release_data.INSTALLER_NATIVE_SNAPSHOT_ENV]
        )
        observed["snapshot"] = snapshot
        target = snapshot / "app" / "firewall" / "iup.dll"
        target.chmod(0o600)
        target.write_bytes(b"substituted")
        return SuccessfulCompiler()

    with pytest.raises(ValueError, match="verified native binary"):
        release_data.compile_installer(
            root,
            expected_mode=release_data.UNSIGNED_MODE,
            iscc="ISCC.exe",
            runner=mutate_snapshot,
            stage_root=stage,
            manifest_path=manifest,
            provenance_path=provenance,
            signature_inspector=lambda _path: ("NotSigned", None),
            tool_verifier=lambda _name, path: Path(path),
        )

    assert not observed["snapshot"].exists()


def _write_release_tool_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    program_files = tmp_path / "Program Files (x86)"
    iscc = program_files / "Inno Setup 6" / "ISCC.exe"
    iscc.parent.mkdir(parents=True)
    iscc.write_bytes(b"pinned-iscc-bytes")
    manifest = tmp_path / "release-tools.json"
    manifest.write_text(
        json.dumps({
            "schema": "dupez.release-tools.v1",
            "iscc": {
                "version": "6.7.1",
                "default_base": "ProgramFilesX86",
                "relative_path": r"Inno Setup 6\ISCC.exe",
                "sha256": _sha256(iscc.read_bytes()),
                "signer_certificate_sha256": SIGNER,
                "signer_subject": "CN=Fixture Signer",
                "signer_thumbprint": "b" * 40,
            },
            "signtool": {
                "version": "10.0.19041.5609",
                "sdk_version": "10.0.19041.0",
                "default_base": "ProgramFilesX86",
                "relative_path": (
                    r"Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe"
                ),
                "sha256": "c" * 64,
                "signer_certificate_sha256": "d" * 64,
                "signer_subject": "CN=Fixture SDK Signer",
                "signer_thumbprint": "e" * 40,
            },
        }),
        encoding="utf-8",
    )
    return program_files, iscc, manifest


def test_release_tool_verifier_accepts_only_exact_pinned_program_files_path(
    tmp_path: Path,
) -> None:
    program_files, iscc, manifest = _write_release_tool_fixture(tmp_path)

    verified = release_data.verify_release_tool(
        "iscc",
        iscc,
        manifest_path=manifest,
        program_files_x86=program_files,
        signature_inspector=lambda _path: ("Valid", SIGNER),
    )

    assert verified == iscc

    alternate = tmp_path / "operator-writable" / "ISCC.exe"
    alternate.parent.mkdir()
    alternate.write_bytes(iscc.read_bytes())
    with pytest.raises(ValueError, match="path does not match"):
        release_data.verify_release_tool(
            "iscc",
            alternate,
            manifest_path=manifest,
            program_files_x86=program_files,
            signature_inspector=lambda _path: ("Valid", SIGNER),
        )


def test_release_tool_verifier_rejects_byte_or_signer_substitution(
    tmp_path: Path,
) -> None:
    program_files, iscc, manifest = _write_release_tool_fixture(tmp_path)
    iscc.write_bytes(b"substituted-after-review")
    with pytest.raises(ValueError, match="hash does not match"):
        release_data.verify_release_tool(
            "iscc",
            iscc,
            manifest_path=manifest,
            program_files_x86=program_files,
            signature_inspector=lambda _path: ("Valid", SIGNER),
        )

    iscc.write_bytes(b"pinned-iscc-bytes")
    with pytest.raises(ValueError, match="signer does not match"):
        release_data.verify_release_tool(
            "iscc",
            iscc,
            manifest_path=manifest,
            program_files_x86=program_files,
            signature_inspector=lambda _path: ("Valid", "f" * 64),
        )


def test_release_tool_verifier_rejects_unknown_manifest_fields(
    tmp_path: Path,
) -> None:
    program_files, iscc, manifest = _write_release_tool_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["iscc"]["unreviewed"] = "value"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="pin structure"):
        release_data.verify_release_tool(
            "iscc",
            iscc,
            manifest_path=manifest,
            program_files_x86=program_files,
            signature_inspector=lambda _path: ("Valid", SIGNER),
        )
