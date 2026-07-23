"""Release controls must remain internally consistent."""

import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.update_verify import MANIFEST_SCHEMA, pubkey_fingerprint
from scripts.release_preflight import (
    _check_frozen_dependency_policy,
    _check_frozen_runtime_import_policy,
    _check_hermetic_python_policy,
    _check_signtool_policy,
    _query_authenticode,
    _release_data_archive_names,
    _verify_update_sidecars,
    check_source,
)


def test_release_source_preflight_passes() -> None:
    # Derive the expected version from app/__version__.py so later patch
    # releases do not fail because this test retained an obsolete literal.
    assert check_source() == []


def test_release_data_manifest_is_valid_and_explicit() -> None:
    names, errors = _release_data_archive_names()

    assert errors == []
    assert "app.config.settings.json" in names
    assert "app.resources.dupez.ico" in names
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith(".py") for name in names)
    assert not any(name.endswith(".hmac") for name in names)


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
    assert _check_frozen_runtime_import_policy() == []


def test_hermetic_policy_rejects_ambient_python(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(
        release_preflight,
        "_read",
        lambda _rel: """
set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\\.venv\\Scripts\\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\\.build-venv"
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
    )

    assert any("app.social" in error for error in errors)
    assert any("llvmlite" in error for error in errors)
    assert any("numba" in error for error in errors)
    assert any("unmanaged packaged data" in error for error in errors)


def test_frozen_dependency_policy_accepts_clean_archive(tmp_path) -> None:
    artifact = tmp_path / "DupeZ-Compat.exe"
    artifact.write_bytes(b"fixture")

    class FakeEmbeddedArchive:
        toc = {"app.core": (), "PyQt6.QtCore": ()}

    class FakeArchive:
        toc = {
            "PYZ.pyz": (),
            "python311.dll": (),
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
        )
        == []
    )


def test_frozen_dependency_policy_fails_closed_without_pyz(tmp_path) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"fixture")

    class FakeArchive:
        toc = {"python311.dll": ()}

        def __init__(self, _path):
            pass

    errors = _check_frozen_dependency_policy(
        [artifact],
        archive_reader_cls=FakeArchive,
        release_data_names=set(),
    )

    assert any("exactly one PYZ.pyz" in error for error in errors)


def test_authenticode_query_non_windows_is_explicit(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(release_preflight.os, "name", "posix")

    statuses, error = _query_authenticode([])

    assert statuses == {}
    assert "require Windows" in error


def _write_signed_update_fixture(
    dist,
    *,
    version: str = "5.7.9",
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
        "5.7.9",
        trusted_pubkeys_pem=trusted,
    ) == []


def test_update_sidecars_reject_stale_version(tmp_path) -> None:
    trusted = _write_signed_update_fixture(tmp_path, version="5.7.8")

    errors = _verify_update_sidecars(
        tmp_path,
        "5.7.9",
        trusted_pubkeys_pem=trusted,
    )

    assert any("version mismatch" in error for error in errors)


def test_update_sidecars_reject_installer_changed_after_signing(tmp_path) -> None:
    trusted = _write_signed_update_fixture(tmp_path)
    (tmp_path / "DupeZ_Setup.exe").write_bytes(b"replaced after signing")

    errors = _verify_update_sidecars(
        tmp_path,
        "5.7.9",
        trusted_pubkeys_pem=trusted,
    )

    assert any("does not match installer" in error for error in errors)
