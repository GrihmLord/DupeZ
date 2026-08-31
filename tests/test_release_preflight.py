"""Release controls must remain internally consistent."""

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import scripts.release_preflight as release_preflight
from app.core.update_verify import (
    MANIFEST_SCHEMA,
    TRUSTED_PUBKEYS_PEM,
    pubkey_fingerprint,
)
from scripts.release_preflight import (
    _check_build_entrypoint_policy,
    _check_frozen_dependency_policy,
    _check_frozen_runtime_import_policy,
    _check_hermetic_python_policy,
    _check_independent_child_signing_policy,
    _check_installer_alias,
    _check_installer_payload_policy,
    _check_installer_setup_policy,
    _check_license_policy,
    _check_outer_authenticode_policy,
    _check_release_tool_pin_policy,
    _check_renderer_flag_policy,
    _check_signtool_policy,
    _check_workflow_action_pins,
    _query_authenticode,
    _release_binary_archive_expectations,
    _release_data_archive_names,
    _release_payload_paths,
    _verify_update_sidecars,
    check_source,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_source_preflight_passes() -> None:
    # Derive the expected version from app/__version__.py so later patch
    # releases do not fail because this test retained an obsolete literal.
    assert check_source() == []


def test_license_policy_warns_for_source_and_blocks_distribution() -> None:
    source_errors, source_warnings = _check_license_policy()
    assert source_errors == []
    assert len(source_warnings) == 6
    assert all("owner decision unresolved" in item for item in source_warnings)

    distribution_errors, distribution_warnings = _check_license_policy(
        distribution=True
    )
    assert distribution_warnings == []
    assert len(distribution_errors) == 6
    assert all(
        "distribution release blocked" in item
        for item in distribution_errors
    )


def test_license_policy_accepts_owner_determinations_with_pinned_evidence() -> None:
    payload = json.loads(
        (ROOT / "packaging" / "license-policy.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_path = ROOT / "SECURITY.md"
    evidence = {
        "kind": "repository-file",
        "reference": "SECURITY.md",
        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    payload["release_state"] = "evidence-recorded"
    for decision in payload["decisions"]:
        decision["state"] = "evidence-recorded"
        decision["determination"] = "owner determination recorded"
        decision["evidence"] = [evidence]

    errors, warnings = _check_license_policy(
        json.dumps(payload),
        distribution=True,
    )

    assert errors == []
    assert warnings == []


def test_license_policy_rejects_unpinned_or_mismatched_evidence() -> None:
    payload = json.loads(
        (ROOT / "packaging" / "license-policy.json").read_text(
            encoding="utf-8"
        )
    )
    payload["decisions"][0].update({
        "state": "evidence-recorded",
        "determination": "owner determination recorded",
        "evidence": [{
            "kind": "repository-file",
            "reference": "SECURITY.md",
            "sha256": "0" * 64,
        }],
    })

    errors, _ = _check_license_policy(json.dumps(payload), distribution=True)

    assert any("SHA-256 does not match" in item for item in errors)
    assert any("owner decision unresolved" in item for item in errors)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    (
        (
            "ArchitecturesAllowed=x64os",
            "ArchitecturesAllowed=x64compatible",
            "architecturesallowed=x64os",
        ),
        (
            "ArchitecturesInstallIn64BitMode=x64os",
            "ArchitecturesInstallIn64BitMode=x64compatible",
            "architecturesinstallin64bitmode=x64os",
        ),
        (
            "RedirectionGuard=yes",
            "RedirectionGuard=no",
            "redirectionguard=yes",
        ),
        (
            'Source: "{#DupeZNativeSnapshot}\\app\\firewall\\WinDivert64.sys"',
            'Source: "{#DupeZNativeSnapshot}\\app\\firewall\\other.sys"',
            "exactly one native-x64 WinDivert64.sys",
        ),
    ),
)
def test_installer_setup_policy_rejects_architecture_or_driver_drift(
    old: str,
    new: str,
    expected: str,
) -> None:
    installer = (ROOT / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )
    assert old in installer

    errors = _check_installer_setup_policy(installer.replace(old, new, 1))

    assert any(expected in error for error in errors)


def test_release_tool_pin_policy_accepts_exact_manifest() -> None:
    assert _check_release_tool_pin_policy() == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    (
        (
            lambda payload: payload.update({"unexpected": {}}),
            "manifest structure",
        ),
        (
            lambda payload: payload["iscc"].update({"sha256": "bad"}),
            "SHA-256 pin",
        ),
        (
            lambda payload: payload["iscc"].update(
                {"signer_certificate_sha256": "bad"}
            ),
            "certificate SHA-256 pin",
        ),
        (
            lambda payload: payload["signtool"].update(
                {"relative_path": r"Windows Kits\\10\\bin\\latest\\signtool.exe"}
            ),
            "version/path binding",
        ),
    ),
)
def test_release_tool_pin_policy_rejects_manifest_drift(
    mutate,
    expected: str,
) -> None:
    payload = json.loads(
        (ROOT / "packaging" / "release-tools.json").read_text(encoding="utf-8")
    )
    mutate(payload)

    errors = _check_release_tool_pin_policy(json.dumps(payload))

    assert any(expected in error for error in errors)


def test_release_tool_pin_policy_rejects_non_object_or_empty_manifest() -> None:
    payload = json.loads(
        (ROOT / "packaging" / "release-tools.json").read_text(encoding="utf-8")
    )

    assert any(
        "manifest structure" in error
        for error in _check_release_tool_pin_policy(json.dumps([payload]))
    )
    assert any(
        "malformed" in error for error in _check_release_tool_pin_policy("")
    )


@pytest.mark.parametrize(
    ("relative", "marker", "expected"),
    (
        (
            "packaging/build_variants.bat",
            '"%DUPEZ_PYTHON%" -I packaging\\release_data.py verify-tool '
            '--name signtool --path "%_SIGNTOOL%"',
            "SignTool must be re-verified",
        ),
        (
            "packaging/release_data.py",
            'verified_iscc = tool_verifier("iscc", iscc)',
            "ISCC must be re-verified",
        ),
    ),
)
def test_release_tool_pin_policy_rejects_use_point_verifier_removal(
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    marker: str,
    expected: str,
) -> None:
    original_read = release_preflight._read
    original = original_read(relative)
    assert marker in original

    def read_without_use_point_verifier(rel: str) -> str:
        if rel == relative:
            return original.replace(marker, "REM verifier removed", 1)
        return original_read(rel)

    monkeypatch.setattr(
        release_preflight,
        "_read",
        read_without_use_point_verifier,
    )

    errors = _check_release_tool_pin_policy()

    assert any(expected in error for error in errors)


@pytest.mark.parametrize("field", ["filevers", "prodvers"])
def test_release_source_preflight_rejects_fixed_pe_version_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    original_read = release_preflight._read
    version_info = original_read("packaging/version_info.py")
    stale_version_info, replacements = re.subn(
        rf"(\b{field}\s*=\s*)\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        rf"\g<1>(0, 0, 0, 0)",
        version_info,
        count=1,
    )
    assert replacements == 1

    def read_with_stale_fixed_version(rel: str) -> str:
        if rel == "packaging/version_info.py":
            return stale_version_info
        return original_read(rel)

    monkeypatch.setattr(release_preflight, "_read", read_with_stale_fixed_version)

    errors = release_preflight.check_source()

    assert any(
        "version mismatch: packaging/version_info.py "
        f"FixedFileInfo.{field}: 0.0.0.0" in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("relative", "marker"),
    (
        ("README.md", "badge/python-3.12%20%7C%203.13-green"),
        ("README.md", "Python 3.12 or 3.13 for source use"),
        ("app/gui/dashboard.py", r"Python 3.12\u20133.13"),
    ),
)
def test_release_source_preflight_rejects_broadened_python_support(
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    marker: str,
) -> None:
    original_read = release_preflight._read
    original = original_read(relative)
    broadened = original.replace(marker, "Python 3.12+", 1)
    assert broadened != original

    def read_with_broadened_support(rel: str) -> str:
        if rel == relative:
            return broadened
        return original_read(rel)

    monkeypatch.setattr(
        release_preflight,
        "_read",
        read_with_broadened_support,
    )

    errors = release_preflight.check_source()

    assert any(
        f"supported Python contract missing from {relative}" in error
        for error in errors
    )


def test_workflow_action_pin_policy_scans_yaml_files(tmp_path) -> None:
    (tmp_path / "pinned.yml").write_text(
        "steps:\n  - uses: actions/checkout@" + "a" * 40 + "\n",
        encoding="utf-8",
    )
    (tmp_path / "mutable.yaml").write_text(
        "steps:\n  - uses: actions/setup-python@v6\n",
        encoding="utf-8",
    )

    errors = _check_workflow_action_pins(tmp_path)

    assert errors == [
        "mutable GitHub Action reference: mutable.yaml: v6"
    ]


def test_v579_recovery_rotation_key_is_pinned() -> None:
    fingerprints = {
        pubkey_fingerprint(public_pem).hex()
        for public_pem in TRUSTED_PUBKEYS_PEM
    }

    assert "4e9c3c6731efbaa8" in fingerprints  # pragma: allowlist secret
    assert "5555f0e8c31a40ed" in fingerprints  # pragma: allowlist secret


def test_release_data_manifest_is_valid_and_explicit() -> None:
    names, errors = _release_data_archive_names()
    data_paths, binary_paths, payload_errors = _release_payload_paths()

    assert errors == []
    assert payload_errors == []
    assert "app.config.settings.json" in names
    assert "app.resources.dupez.ico" in names
    assert "app/config/settings.json" in data_paths
    assert "app/firewall/clumsy.exe" in binary_paths
    assert "app/firewall/windivert.dll" in binary_paths
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith(".py") for name in names)
    assert not any(name.endswith(".hmac") for name in names)
    assert not any("clumsy_src" in name for name in binary_paths)


def test_installer_payload_is_exactly_manifest_managed() -> None:
    data_paths, binary_paths, manifest_errors = _release_payload_paths()
    installer = (ROOT / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )
    normalized_installer = installer.replace("\\", "/").casefold()

    assert manifest_errors == []
    assert _check_installer_payload_policy(
        release_data_paths=data_paths,
        release_binary_paths=binary_paths,
    ) == []
    for binary_path in binary_paths:
        assert (
            f'source: "{{#dupeznativesnapshot}}/{binary_path}"'
            in normalized_installer
        )
        assert f'source: "{binary_path}"' not in normalized_installer


def test_installer_rejects_direct_unmeasured_native_source() -> None:
    data_paths, binary_paths, manifest_errors = _release_payload_paths()
    installer = (ROOT / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    ).replace(
        r"{#DupeZNativeSnapshot}\app\firewall\clumsy.exe",
        r"app\firewall\clumsy.exe",
    )

    assert manifest_errors == []
    errors = _check_installer_payload_policy(
        installer,
        release_data_paths=data_paths,
        release_binary_paths=binary_paths,
    )
    combined = "\n".join(errors)
    assert "installer omits manifest-approved sources" in combined
    assert "installer contains unmanaged sources" in combined


def test_installer_fails_closed_without_release_data_snapshot() -> None:
    data_paths, binary_paths, manifest_errors = _release_payload_paths()
    installer = (ROOT / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )

    assert manifest_errors == []
    assert "GetEnv(\"DUPEZ_INSTALLER_NATIVE_SNAPSHOT\")" in installer
    assert '#if DupeZNativeSnapshot == ""' in installer
    without_guard = installer.replace(
        '#error "DUPEZ_INSTALLER_NATIVE_SNAPSHOT is required; '
        'run packaging\\build_variants.bat"',
        "; snapshot guard removed",
    )
    errors = _check_installer_payload_policy(
        without_guard,
        release_data_paths=data_paths,
        release_binary_paths=binary_paths,
    )

    assert any(
        "installer native snapshot policy missing" in error
        for error in errors
    )


def test_standard_release_measures_unsigned_independent_clumsy(tmp_path) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")
    provenance = tmp_path / "binary-provenance.json"
    provenance.write_text(
        json.dumps({
            "artifacts": [{
                "path": "app/firewall/clumsy.exe",
                # Editable metadata must not be accepted as signature proof.
                "authenticode": "valid",
            }],
        }),
        encoding="utf-8",
    )

    class FakeArchive:
        toc = {r"app\firewall\clumsy.exe": ()}

        def __init__(self, _path):
            pass

        def extract(self, _name):
            return b"unsigned packaged child"

    def reject_unsigned(_path):
        raise ValueError("NotSigned")

    errors = _check_independent_child_signing_policy(
        allow_unsigned=False,
        provenance_path=provenance,
        artifacts=[artifact],
        archive_reader_cls=FakeArchive,
        signature_verifier=reject_unsigned,
        expected_signer_certificate_sha256="a" * 64,
        source_equivalence_verifier=lambda _source, _signed: None,
    )

    assert any("production release blocked" in error for error in errors)
    assert any("outer executable or installer" in error for error in errors)
    assert _check_independent_child_signing_policy(
        allow_unsigned=True,
        provenance_path=provenance,
        artifacts=[artifact],
        archive_reader_cls=FakeArchive,
        signature_verifier=reject_unsigned,
    ) == []


def test_standard_release_accepts_only_measured_packaged_child_signature(
    tmp_path,
) -> None:
    artifacts = [tmp_path / "DupeZ-GPU.exe", tmp_path / "DupeZ-Compat.exe"]
    for artifact in artifacts:
        artifact.write_bytes(b"fixture")

    class FakeArchive:
        toc = {r"app\firewall\clumsy.exe": ()}

        def __init__(self, _path):
            pass

        def extract(self, _name):
            return b"signed packaged child"

    assert _check_independent_child_signing_policy(
        allow_unsigned=False,
        artifacts=artifacts,
        archive_reader_cls=FakeArchive,
        signature_verifier=lambda _path: "a" * 64,
        expected_signer_certificate_sha256="a" * 64,
        source_equivalence_verifier=lambda _source, _signed: None,
    ) == []


def test_shared_pyinstaller_build_uses_exact_release_data_manifest() -> None:
    """Variant builds must not regain recursive config/resource sweeps."""
    build_common = (ROOT / "packaging" / "build_common.py").read_text(
        encoding="utf-8"
    )
    assert "from release_data import (" in build_common
    assert "pyinstaller_binaries," in build_common
    assert "pyinstaller_datas," in build_common
    assert "return pyinstaller_datas(ROOT)" in build_common
    assert "a.binaries = _filter_root_binary_duplicates(a.binaries)" in (
        build_common
    )
    assert 'if "/" not in destination and destination in duplicate_basenames' in (
        build_common
    )
    for directory in ("config", "resources", "assets", "themes"):
        assert f'os.path.join(ROOT, "app", "{directory}")' not in build_common


def test_installer_payload_rejects_recursive_and_runtime_leaks() -> None:
    installer = r'''
[Files]
Source: "dist\DupeZ-GPU.exe"; DestDir: "{app}"; DestName: "dupez.exe"
Source: "dist\DupeZ-Compat.exe"; DestDir: "{app}"
Source: "app\config\*"; DestDir: "{app}\app\config"; Flags: recursesubdirs
Source: "app\firewall\clumsy_src\external\WinDivert-2.2.0-A\x64\netdump.exe"; DestDir: "{app}\app\firewall\clumsy_src\external\WinDivert-2.2.0-A\x64"
Source: "app\firewall\windivertctl.exe"; DestDir: "{app}\app\firewall"
Source: "app\config\__pycache__\settings.pyc"; DestDir: "{app}\app\config\__pycache__"
Source: "app\themes\theme_manager.pyo"; DestDir: "{app}\app\themes"
Source: "app\config\settings.json.hmac"; DestDir: "{app}\app\config"
Source: "app\config\patch_monitor_state.json"; DestDir: "{app}\app\config"
'''

    errors = _check_installer_payload_policy(
        installer,
        release_data_paths=set(),
        release_binary_paths=set(),
    )
    combined = "\n".join(errors)

    assert "recursive installer source" in combined
    assert "source wildcards" in combined
    assert "clumsy_src" in combined
    assert "__pycache__" in combined
    assert "theme_manager.pyo" in combined
    assert "settings.json.hmac" in combined
    assert "patch_monitor_state.json" in combined
    assert "windivertctl.exe" in combined
    assert "unmanaged sources" in combined


def test_signtool_policy_requires_sha256_timestamp(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(
        release_preflight,
        "_read",
        lambda _rel: "signtool sign /f cert.pfx dist\\DupeZ.exe",
    )

    errors = _check_signtool_policy("packaging/build.bat")

    assert errors
    assert "/fd sha256" in errors[0]
    assert "/td sha256" in errors[0]
    assert "/tr" in errors[0]


def test_release_builds_enforce_hermetic_python_and_runtime_imports() -> None:
    for rel in ("packaging/build.bat", "packaging/build_variants.bat"):
        assert _check_hermetic_python_policy(rel) == []
    assert _check_build_entrypoint_policy() == []
    assert _check_frozen_runtime_import_policy() == []
    assert _check_renderer_flag_policy() == []


def test_renderer_policy_rejects_removed_swiftshader_flag(tmp_path) -> None:
    unsafe = tmp_path / "renderer.py"
    unsafe.write_text(
        'FLAGS = "--use-gl=swiftshader --enable-gpu-rasterization"\n',
        encoding="utf-8",
    )

    errors = _check_renderer_flag_policy([unsafe])

    assert len(errors) == 1
    assert "obsolete QtWebEngine SwiftShader flag" in errors[0]


@pytest.mark.parametrize(
    ("unsafe_line", "expected_error"),
    (
        ("where ISCC", "invoke the Inno Setup compiler"),
        (
            r'"%_ISCC%" packaging\installer.iss',
            "invoke the installer definition",
        ),
        (
            r'copy /Y "dist\DupeZ_v5.8.0_Setup.exe" '
            r'"dist\DupeZ_Setup.exe"',
            "create or reference a stable installer alias",
        ),
    ),
)
def test_legacy_build_rejects_installer_release_behavior(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_line: str,
    expected_error: str,
) -> None:
    original_read = release_preflight._read
    legacy = original_read("packaging/build.bat")

    def read_with_unsafe_legacy(rel: str) -> str:
        if rel == "packaging/build.bat":
            return f"{legacy}\n{unsafe_line}\n"
        return original_read(rel)

    monkeypatch.setattr(
        release_preflight,
        "_read",
        read_with_unsafe_legacy,
    )

    errors = _check_build_entrypoint_policy()

    assert any(expected_error in error for error in errors)


def test_canonical_build_remains_the_installer_release_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = release_preflight._read
    canonical = original_read("packaging/build_variants.bat")
    canonical = canonical.replace(
        r'packaging\compile_installer.py --mode "%DUPEZ_RELEASE_MODE%" '
        r'--iscc "%_ISCC%"',
        "rem installer compiler removed",
    ).replace(
        r'copy /Y "dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe"',
        "rem stable installer alias removed",
    )

    def read_without_canonical_release_steps(rel: str) -> str:
        if rel == "packaging/build_variants.bat":
            return canonical
        return original_read(rel)

    monkeypatch.setattr(
        release_preflight,
        "_read",
        read_without_canonical_release_steps,
    )

    errors = _check_build_entrypoint_policy()

    assert sum(
        "canonical release build policy missing" in error for error in errors
    ) == 2


def test_canonical_installer_pipeline_cannot_bypass_verified_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = release_preflight._read
    canonical = original_read("packaging/build_variants.bat")
    assert (
        r'packaging\compile_installer.py --mode "%DUPEZ_RELEASE_MODE%" '
        r'--iscc "%_ISCC%"'
    ) in canonical
    assert r'"%_ISCC%" packaging\installer.iss' not in canonical
    wrapper = (ROOT / "packaging" / "compile_installer.py").read_text(
        encoding="utf-8"
    )
    assert "from release_data import compile_installer" in wrapper
    assert "compile_installer(" in wrapper

    def read_with_direct_iscc(rel: str) -> str:
        if rel == "packaging/build_variants.bat":
            return canonical + '\n"%_ISCC%" packaging\\installer.iss\n'
        return original_read(rel)

    monkeypatch.setattr(release_preflight, "_read", read_with_direct_iscc)
    errors = _check_build_entrypoint_policy()

    assert any("verified native-snapshot wrapper" in error for error in errors)


def test_stable_installer_alias_must_match_versioned_bytes(tmp_path) -> None:
    versioned = tmp_path / "DupeZ_v5.8.0_Setup.exe"
    stable = tmp_path / "DupeZ_Setup.exe"
    versioned.write_bytes(b"signed-installer-a")
    stable.write_bytes(b"signed-installer-a")

    assert _check_installer_alias(tmp_path, "5.8.0") == []

    stable.write_bytes(b"signed-installer-b")
    errors = _check_installer_alias(tmp_path, "5.8.0")

    assert errors
    assert "SHA-256 mismatch" in errors[0]


def test_hermetic_policy_rejects_ambient_python(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(
        release_preflight,
        "_read",
        lambda _rel: """
set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\\.venv\\Scripts\\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\\.release-venv"
set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\\Scripts\\python.exe"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_REQUIRE_VIRTUALENV=true"
if not exist "%DUPEZ_BOOTSTRAP_PYTHON%" exit /b 1
if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q "%DUPEZ_BUILD_VENV%"
"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -m venv "%DUPEZ_BUILD_VENV%"
"%DUPEZ_PYTHON%" -I -m pip install --only-binary=:all: --require-hashes -r packaging\\requirements-build-locked.txt
"%DUPEZ_PYTHON%" -I -m pip install --only-binary=:all: --require-hashes -r requirements-locked.txt
"%DUPEZ_PYTHON%" -I -c "import PyInstaller; import PyQt6.sip; from PyQt6 import QtCore, QtWidgets, QtWebEngineWidgets"
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\\dupez.spec
"%DUPEZ_PYTHON%" scripts\\release_preflight.py --frozen-artifact dist\\dupez.exe
python scripts\\sbom.py
""",
    )

    errors = _check_hermetic_python_policy("packaging/build.bat")

    assert any("ambient Python command" in error for error in errors)
    assert any(
        "project script bypasses isolated build interpreter" in error
        for error in errors
    )


def test_frozen_dependency_policy_checks_outer_and_inner_archives(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {
            "app.core": (),
            "numba.core": (),
            "app.social.client": (),
        }

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            "app\\config\\settings.json": (),
            "app\\config\\settings.json.hmac": (),
            "llvmlite\\binding\\llvmlite.dll": (),
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, name):
            assert name == "PYZ.pyz"
            return FakeEmbeddedArchive()

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names={"app/config/settings.json"},
        release_binary_expectations={},
    )

    assert any("app.social" in error for error in errors)
    assert any("llvmlite" in error for error in errors)
    assert any("numba" in error for error in errors)
    assert any("unmanaged packaged data" in error for error in errors)


def test_frozen_dependency_policy_rejects_scapy_from_ambient_build_environment(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {
            "app.core": (),
            "scapy": (),
            "scapy.layers.inet": (),
        }

    class FakeArchive:
        toc = {"PYZ.pyz": ()}

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations={},
    )

    assert any(
        "forbidden frozen dependency" in error and "scapy" in error
        for error in errors
    )


def test_frozen_dependency_policy_accepts_clean_archive(tmp_path) -> None:
    artifact = tmp_path / "DupeZ-Compat.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {"app.core": (), "PyQt6.QtCore": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            "python313.dll": (),
            "app\\config\\settings.json": (),
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

    assert (
        _check_frozen_dependency_policy(
            [artifact],
            archive_reader_cls=FakeArchive,
            release_data_names={"app/config/settings.json"},
            release_binary_expectations={},
        )
        == []
    )


def test_frozen_dependency_policy_rejects_unused_asio_sdk_binary(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {"app.core": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            (
                r"_sounddevice_data\portaudio-binaries"
                r"\libportaudio64bit-asio.dll"
            ): (),
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations={},
    )

    assert any("libportaudio64bit-asio.dll" in item for item in errors)


def test_frozen_dependency_policy_verifies_managed_native_bytes(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")
    native_bytes = b"managed-native-payload"
    native_path = "app/firewall/clumsy.exe"
    expectations = {
        native_path: (
            len(native_bytes),
            hashlib.sha256(native_bytes).hexdigest(),
        ),
    }

    class FakeEmbeddedArchive:
        toc = {"app.core": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            r"app\firewall\clumsy.exe": (),
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

        def extract(self, name):
            assert name == r"app\firewall\clumsy.exe"
            return native_bytes

    assert _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations=expectations,
    ) == []


def test_distribution_provenance_drives_signed_native_archive_hashes(
    tmp_path, monkeypatch
) -> None:
    from scripts import release_preflight

    signer = "a" * 64
    source_clumsy = b"unsigned-source-clumsy"
    signed_clumsy = b"signed-source-equivalent-clumsy"
    iup = b"source-exact-iup"
    source_path = tmp_path / "source-provenance.json"
    source_records = [
        {
            "path": "app/firewall/clumsy.exe",
            "size": len(source_clumsy),
            "sha256": hashlib.sha256(source_clumsy).hexdigest(),
            "version": "0.3.4",
            "source": "https://example.invalid/clumsy",
            "source_commit": "1" * 40,
        },
        {
            "path": "app/firewall/iup.dll",
            "size": len(iup),
            "sha256": hashlib.sha256(iup).hexdigest(),
            "version": "3.30",
            "source": "https://example.invalid/iup",
        },
    ]
    source_path.write_text(
        json.dumps({
            "schema": "dupez.bundled-binaries.v1",
            "artifacts": source_records,
        }),
        encoding="utf-8",
    )
    dist_path = tmp_path / "binary-provenance.json"
    dist_payload = {
        "schema": "dupez.distribution-binaries.v1",
        "release_mode": "standard-authenticode",
        "source_provenance_schema": "dupez.bundled-binaries.v1",
        "signer_certificate_sha256": signer,
        "artifacts": [
            {
                **source_records[0],
                "size": len(signed_clumsy),
                "sha256": hashlib.sha256(signed_clumsy).hexdigest(),
                "source_size": len(source_clumsy),
                "source_sha256": hashlib.sha256(source_clumsy).hexdigest(),
                "transform": "authenticode-signed-staged-copy",
                "source_equivalence": "pe-authenticode-certificate-table-v1",
                "authenticode": {
                    "status": "Valid",
                    "signer_certificate_sha256": signer,
                },
            },
            {
                **source_records[1],
                "source_size": len(iup),
                "source_sha256": hashlib.sha256(iup).hexdigest(),
                "transform": "source-exact",
            },
        ],
    }
    dist_path.write_text(json.dumps(dist_payload), encoding="utf-8")
    monkeypatch.setattr(
        release_preflight,
        "_BINARY_PROVENANCE_MANIFEST",
        source_path,
    )

    expectations, errors = _release_binary_archive_expectations(
        {
            "app/firewall/clumsy.exe",
            "app/firewall/iup.dll",
        },
        provenance_path=dist_path,
        expected_mode="standard-authenticode",
        expected_signer_certificate_sha256=signer,
    )
    assert errors == []
    assert expectations["app/firewall/clumsy.exe"] == (
        len(signed_clumsy),
        hashlib.sha256(signed_clumsy).hexdigest(),
    )

    class FakeEmbeddedArchive:
        toc = {"app.core": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            r"app\firewall\clumsy.exe": (),
            r"app\firewall\iup.dll": (),
        }
        payloads = {
            r"app\firewall\clumsy.exe": signed_clumsy,
            r"app\firewall\iup.dll": iup,
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

        def extract(self, name):
            return self.payloads[name]

    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")
    assert _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations=expectations,
    ) == []

    FakeArchive.payloads[r"app\firewall\clumsy.exe"] = b"substitution"
    tamper_errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations=expectations,
    )
    assert any("size mismatch" in error for error in tamper_errors)
    assert any("SHA-256 mismatch" in error for error in tamper_errors)

    dist_payload["schema"] = "attacker-controlled"
    dist_path.write_text(json.dumps(dist_payload), encoding="utf-8")
    invalid_expectations, schema_errors = _release_binary_archive_expectations(
        {
            "app/firewall/clumsy.exe",
            "app/firewall/iup.dll",
        },
        provenance_path=dist_path,
        expected_mode="standard-authenticode",
        expected_signer_certificate_sha256=signer,
    )
    assert invalid_expectations == {}
    assert any("unsupported dist" in error for error in schema_errors)


def test_frozen_dependency_policy_rejects_native_tampering_and_root_duplicate(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-Compat.exe"
    artifact.write_bytes(b"fixture")
    expected_bytes = b"reviewed-native-payload"
    expectations = {
        "app/firewall/iup.dll": (
            len(expected_bytes),
            hashlib.sha256(expected_bytes).hexdigest(),
        ),
    }

    class FakeEmbeddedArchive:
        toc = {"app.core": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            r"app\firewall\iup.dll": (),
            "iup.dll": (),
        }

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

        def extract(self, name):
            assert name == r"app\firewall\iup.dll"
            return b"tampered"

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations=expectations,
    )

    assert any("root-level duplicate" in error for error in errors)
    assert any("size mismatch" in error for error in errors)
    assert any("SHA-256 mismatch" in error for error in errors)


def test_frozen_dependency_policy_requires_every_managed_native_path(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {"app.core": ()}

    class FakeArchive:
        toc = {"PYZ.pyz": ()}

        def __init__(self, _path):
            pass

        def open_embedded_archive(self, _name):
            return FakeEmbeddedArchive()

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations={
            "app/firewall/windivert.dll": (3, hashlib.sha256(b"dll").hexdigest()),
        },
    )

    assert any("required packaged native binaries missing" in error for error in errors)


def test_frozen_dependency_policy_fails_closed_without_pyz(tmp_path) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeArchive:
        toc = {"python313.dll": ()}

        def __init__(self, _path):
            pass

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
        release_binary_expectations={},
    )

    assert any("exactly one PYZ.pyz" in error for error in errors)


def test_authenticode_query_non_windows_is_explicit(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(release_preflight.os, "name", "posix")

    statuses, error = _query_authenticode([])

    assert statuses == {}
    assert "require Windows" in error


@pytest.mark.skipif(os.name != "nt", reason="Authenticode is Windows-only")
def test_authenticode_query_preserves_each_artifact(monkeypatch, tmp_path) -> None:
    from scripts import release_preflight

    first = tmp_path / "first.exe"
    second = tmp_path / "second.exe"
    shutil.copyfile(sys.executable, first)
    shutil.copyfile(sys.executable, second)
    monkeypatch.setattr(release_preflight, "DIST", tmp_path)

    measurements, error = _query_authenticode([first, second])

    assert error == ""
    assert measurements.keys() == {"first.exe", "second.exe"}
    for measurement in measurements.values():
        assert measurement.keys() == {
            "status",
            "signer_certificate_sha256",
            "timestamp_present",
        }
        assert measurement["status"]
        signer = measurement["signer_certificate_sha256"]
        assert signer is None or re.fullmatch(r"[0-9a-f]{64}", signer)
        assert isinstance(measurement["timestamp_present"], bool)


def test_outer_authenticode_policy_accepts_bound_signer_and_timestamp(
    tmp_path,
) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    signer = "a" * 64

    errors = _check_outer_authenticode_policy(
        [artifact],
        expected_signer_certificate_sha256=signer,
        query_fn=lambda _paths: ({
            artifact.name: {
                "status": "Valid",
                "signer_certificate_sha256": signer,
                "timestamp_present": True,
            },
        }, ""),
    )

    assert errors == []


@pytest.mark.parametrize(
    ("measured_signer", "timestamp_present", "expected_error"),
    (
        ("b" * 64, True, "signer does not match"),
        ("a" * 64, False, "no acceptable Authenticode timestamp"),
    ),
)
def test_outer_authenticode_policy_rejects_wrong_signer_or_missing_timestamp(
    tmp_path,
    measured_signer: str,
    timestamp_present: bool,
    expected_error: str,
) -> None:
    artifact = tmp_path / "DupeZ-Compat.exe"

    errors = _check_outer_authenticode_policy(
        [artifact],
        expected_signer_certificate_sha256="a" * 64,
        query_fn=lambda _paths: ({
            artifact.name: {
                "status": "Valid",
                "signer_certificate_sha256": measured_signer,
                "timestamp_present": timestamp_present,
            },
        }, ""),
    )

    assert any(expected_error in error for error in errors)


def _write_signed_update_fixture(
    dist,
    *,
    version: str = "5.8.0",
    manifest_payload: bytes | None = None,
):
    installer = dist / "DupeZ_Setup.exe"
    installer.write_bytes(b"verified installer fixture")
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    if manifest_payload is None:
        payload = {
            "schema": MANIFEST_SCHEMA,
            "version": version,
            "released_at": "2026-07-18T00:00:00Z",
            "installer": {
                "filename": installer.name,
                "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
                "size": installer.stat().st_size,
            },
        }
        manifest_payload = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    (dist / "DupeZ_Setup.exe.manifest.json").write_bytes(manifest_payload)
    (dist / "DupeZ_Setup.exe.manifest.sig").write_bytes(
        pubkey_fingerprint(public_pem) + private_key.sign(manifest_payload)
    )
    return [public_pem]


def test_update_sidecars_verify_exact_installer(tmp_path) -> None:
    trusted = _write_signed_update_fixture(tmp_path)

    assert _verify_update_sidecars(
        tmp_path,
        "5.8.0",
        trusted_pubkeys_pem=trusted,
    ) == []


def test_update_sidecars_reject_stale_version(tmp_path) -> None:
    trusted = _write_signed_update_fixture(tmp_path, version="5.7.8")

    errors = _verify_update_sidecars(
        tmp_path,
        "5.8.0",
        trusted_pubkeys_pem=trusted,
    )

    assert any("version mismatch" in error for error in errors)


def test_update_sidecars_reject_installer_changed_after_signing(tmp_path) -> None:
    trusted = _write_signed_update_fixture(tmp_path)
    (tmp_path / "DupeZ_Setup.exe").write_bytes(b"replaced after signing")

    errors = _verify_update_sidecars(
        tmp_path,
        "5.8.0",
        trusted_pubkeys_pem=trusted,
    )

    assert any("does not match installer" in error for error in errors)
