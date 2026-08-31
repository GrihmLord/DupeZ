#!/usr/bin/env python3
"""Fail-closed source and artifact checks for DupeZ releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PACKAGING_MODULE_DIR = str(ROOT / "packaging")
sys.path.insert(0, _PACKAGING_MODULE_DIR)
try:
    from release_data import (
        verify_authenticode_source_equivalence as _verify_authenticode_source_equivalence,
    )
finally:
    sys.path.remove(_PACKAGING_MODULE_DIR)

from app.core.update_verify import (
    SigVerifyError,
    UpdateManifest,
    verify_installer_sha256,
    verify_manifest as verify_update_manifest,
)

try:
    from scripts.verify_bundled_binaries import verify_manifest
except ImportError:  # direct `python scripts/release_preflight.py`
    from verify_bundled_binaries import verify_manifest

try:
    from scripts.sbom import (
        PEP508_MARKER_PROPERTY,
        RELEASE_TARGET_PROPERTY,
        parse_lock,
        purl_for,
        release_target_property_value,
    )
except ImportError:  # direct `python scripts/release_preflight.py`
    from sbom import (
        PEP508_MARKER_PROPERTY,
        RELEASE_TARGET_PROPERTY,
        parse_lock,
        purl_for,
        release_target_property_value,
    )

try:
    from scripts.verify_requirements_lock import release_target_metadata
except ImportError:  # direct `python scripts/release_preflight.py`
    from verify_requirements_lock import release_target_metadata

try:
    from scripts.license_payload import validate_license_payload
except ImportError:  # direct `python scripts/release_preflight.py`
    from license_payload import validate_license_payload

_POWERSHELL = Path(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)
_LICENSE_POLICY_PATH = ROOT / "packaging" / "license-policy.json"
_LICENSE_POLICY_SCHEMA = "dupez.license-policy.v1"
_LICENSE_POLICY_DECISION_IDS = frozenset({
    "project-distribution-terms",
    "pyqt-distribution-basis",
    "qt-qtwebengine-distribution-basis",
    "third-party-notices-delivery",
    "source-and-relink-delivery",
    "inno-setup-commercial-use-basis",
})
_LICENSE_POLICY_STATES = frozenset({"unresolved", "evidence-recorded"})
_LICENSE_POLICY_EVIDENCE_KINDS = frozenset({
    "repository-file",
    "external-record",
})


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _is_reparse_point(path: Path) -> bool:
    """Recognize symlinks, junctions, and other Windows reparse points."""

    metadata = path.lstat()
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    return bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _check_license_policy(
    policy_text: str | None = None,
    *,
    distribution: bool = False,
) -> tuple[list[str], list[str]]:
    """Validate owner evidence without making a licensing determination.

    Unresolved decisions are warnings during source-only checks and hard
    errors at distribution boundaries. ``evidence-recorded`` means only that
    an owner determination and pinned evidence exist; it is not a legal
    compliance opinion.
    """

    errors: list[str] = []
    warnings: list[str] = []
    if policy_text is None:
        try:
            metadata = _LICENSE_POLICY_PATH.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_reparse_point(_LICENSE_POLICY_PATH)
            ):
                return [
                    "packaging/license-policy.json must be a regular, "
                    "non-reparse file"
                ], []
            policy_text = _LICENSE_POLICY_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            return [f"cannot read packaging/license-policy.json: {exc}"], []

    try:
        payload = json.loads(policy_text)
    except (TypeError, json.JSONDecodeError) as exc:
        return [f"packaging/license-policy.json is malformed: {exc}"], []
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "reviewed_on",
        "release_state",
        "decisions",
    }:
        return ["packaging/license-policy.json has an invalid structure"], []
    if payload.get("schema") != _LICENSE_POLICY_SCHEMA:
        errors.append("packaging/license-policy.json has an invalid schema")
    reviewed_on = payload.get("reviewed_on")
    try:
        datetime.strptime(str(reviewed_on), "%Y-%m-%d")
    except ValueError:
        errors.append(
            "packaging/license-policy.json reviewed_on must use YYYY-MM-DD"
        )

    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return errors + [
            "packaging/license-policy.json decisions must be a list"
        ], []

    seen: set[str] = set()
    unresolved: list[str] = []
    for index, decision in enumerate(decisions):
        label = f"license-policy decision {index}"
        if not isinstance(decision, dict) or set(decision) != {
            "id",
            "state",
            "determination",
            "evidence",
            "required_owner_action",
        }:
            errors.append(f"{label} has an invalid structure")
            continue
        decision_id = decision.get("id")
        if not isinstance(decision_id, str):
            errors.append(f"{label} has an invalid id")
            continue
        label = f"license-policy decision {decision_id}"
        if decision_id not in _LICENSE_POLICY_DECISION_IDS:
            errors.append(f"unexpected {label}")
        elif decision_id in seen:
            errors.append(f"duplicate {label}")
        seen.add(decision_id)

        action = decision.get("required_owner_action")
        if not isinstance(action, str) or not action.strip():
            errors.append(f"{label} has no required_owner_action")

        state = decision.get("state")
        if state not in _LICENSE_POLICY_STATES:
            errors.append(f"{label} has an invalid state")
            continue
        determination = decision.get("determination")
        evidence = decision.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{label} evidence must be a list")
            continue

        if state == "unresolved":
            unresolved.append(decision_id)
            if determination is not None or evidence:
                errors.append(
                    f"{label} unresolved state must not claim a determination "
                    "or evidence"
                )
            continue

        if not isinstance(determination, str) or not determination.strip():
            errors.append(f"{label} has no owner determination")
        if not evidence:
            errors.append(f"{label} has no pinned evidence")
        for evidence_index, record in enumerate(evidence):
            evidence_label = f"{label} evidence {evidence_index}"
            if not isinstance(record, dict) or set(record) != {
                "kind",
                "reference",
                "sha256",
            }:
                errors.append(f"{evidence_label} has an invalid structure")
                continue
            kind = record.get("kind")
            reference = record.get("reference")
            digest = record.get("sha256")
            if kind not in _LICENSE_POLICY_EVIDENCE_KINDS:
                errors.append(f"{evidence_label} has an invalid kind")
            if not isinstance(reference, str) or not reference.strip():
                errors.append(f"{evidence_label} has no reference")
                continue
            if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                errors.append(f"{evidence_label} has an invalid SHA-256")
                continue
            if kind != "repository-file":
                continue
            relative = PurePosixPath(reference)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in reference
                or relative.as_posix() != reference
            ):
                errors.append(f"{evidence_label} has an unsafe repository path")
                continue
            evidence_path = ROOT.joinpath(*relative.parts)
            try:
                metadata = evidence_path.lstat()
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or _is_reparse_point(evidence_path)
                ):
                    raise OSError("not a regular, non-reparse file")
                actual_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"{evidence_label} is unavailable: {exc}")
                continue
            if actual_digest != digest:
                errors.append(f"{evidence_label} SHA-256 does not match")

    missing = sorted(_LICENSE_POLICY_DECISION_IDS - seen)
    if missing:
        errors.append(
            "packaging/license-policy.json omits required decisions: "
            + ", ".join(missing)
        )
    expected_release_state = "blocked" if unresolved else "evidence-recorded"
    if payload.get("release_state") != expected_release_state:
        errors.append(
            "packaging/license-policy.json release_state does not match its "
            "decision states"
        )

    for decision_id in sorted(unresolved):
        finding = f"license/IP owner decision unresolved: {decision_id}"
        if distribution:
            errors.append(f"distribution release blocked: {finding}")
        else:
            warnings.append(finding)
    return errors, warnings


def _match_version(rel: str, pattern: str) -> str:
    match = re.search(pattern, _read(rel), re.MULTILINE)
    if not match:
        raise ValueError(f"could not extract version from {rel}")
    return match.group(1)


def _match_fixed_file_version(rel: str, field: str) -> str:
    """Return a normalized four-part PyInstaller ``FixedFileInfo`` version."""
    raw = _match_version(
        rel,
        rf"\b{re.escape(field)}\s*=\s*\(\s*((?:\d+\s*,\s*){{3}}\d+)\s*\)",
    )
    return ".".join(str(int(part.strip())) for part in raw.split(","))


def _check_signtool_policy(rel: str) -> list[str]:
    """Ensure Authenticode signing commands use modern digest/timestamp flags."""
    errors: list[str] = []
    for line_no, line in enumerate(_read(rel).splitlines(), start=1):
        lowered = line.lower()
        if " sign " not in lowered:
            continue
        if "signtool" not in lowered and "_signtool" not in lowered:
            continue
        missing = [
            flag
            for flag in ("/tr", "/td sha256", "/fd sha256")
            if flag not in lowered
        ]
        if missing:
            errors.append(
                f"weak Authenticode signing command: {rel}:{line_no} "
                f"missing {', '.join(missing)}"
            )
    return errors


def _check_hermetic_python_policy(rel: str) -> list[str]:
    """Require a freshly recreated, isolated release-build interpreter."""
    errors: list[str] = []
    text = _read(rel)
    required = (
        'set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\\.venv\\Scripts\\python.exe"',
        'set "DUPEZ_BUILD_VENV=%CD%\\.release-venv"',
        'set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\\Scripts\\python.exe"',
        'set "PYTHONHOME="',
        'set "PYTHONPATH="',
        'set "PYTHONNOUSERSITE=1"',
        'set "PIP_REQUIRE_VIRTUALENV=true"',
        'if not exist "%DUPEZ_BOOTSTRAP_PYTHON%"',
        'if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q '
        '"%DUPEZ_BUILD_VENV%"',
        '"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -m venv '
        '"%DUPEZ_BUILD_VENV%"',
        '"%DUPEZ_PYTHON%" -I -m pip',
        "--only-binary=:all:",
        "--require-hashes -r packaging\\requirements-build-locked.txt",
        "--require-hashes -r requirements-locked.txt",
        '"%DUPEZ_PYTHON%" -I -m PyInstaller',
        "scripts\\release_preflight.py",
        "--frozen-artifact",
    )
    for snippet in required:
        if snippet not in text:
            errors.append(
                f"non-hermetic Python build policy in {rel}: "
                f"missing {snippet}"
            )

    import_checks = (
        "import PyInstaller",
        "import PyQt6.sip",
        "QtCore",
        "QtWidgets",
        "QtWebEngineWidgets",
    )
    prebuild_lines = [
        line
        for line in text.splitlines()
        if '"%DUPEZ_PYTHON%" -I -c ' in line
    ]
    combined_checks = "\n".join(prebuild_lines)
    for required_import in import_checks:
        if required_import not in combined_checks:
            errors.append(
                f"build import preflight missing in {rel}: "
                f"{required_import}"
            )

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        lowered = stripped.lower()
        if (
            not stripped
            or stripped.startswith("::")
            or lowered.startswith("rem ")
            or lowered.startswith("echo ")
        ):
            continue
        if re.match(r"(?i)^(?:python|pip)(?:\.exe)?\b", stripped):
            errors.append(
                f"ambient Python command in {rel}:{line_no}: {stripped}"
            )
        if re.search(r"(?i)\bscripts\\[^ ]+\.py\b", stripped):
            if not stripped.startswith('"%DUPEZ_PYTHON%" '):
                errors.append(
                    f"project script bypasses isolated build interpreter in "
                    f"{rel}:{line_no}: {stripped}"
                )
    return errors


def _check_build_entrypoint_policy(
    legacy_rel: str = "packaging/build.bat",
    canonical_rel: str = "packaging/build_variants.bat",
) -> list[str]:
    """Keep the compatibility portable separate from release artifacts."""
    errors: list[str] = []
    legacy = _read(legacy_rel)
    legacy_lower = legacy.lower()

    forbidden_legacy_tokens = {
        "iscc": "invoke the Inno Setup compiler",
        "installer.iss": "invoke the installer definition",
        "dupez_installer": "declare a versioned installer output",
        "dupez_setup": "create or reference a stable installer alias",
    }
    for token, action in forbidden_legacy_tokens.items():
        if token in legacy_lower:
            errors.append(
                f"legacy portable build must not {action}: "
                f"{legacy_rel} contains {token!r}"
            )

    for marker in (
        r"NON-RELEASE: emits only dist\dupez.exe",
        r"Canonical releases use packaging\build_variants.bat.",
        "echo [1/3]",
        "echo [2/3]",
        "echo [3/3]",
        "popd",
        "endlocal & exit /b %DUPEZ_EXIT_CODE%",
    ):
        if marker not in legacy:
            errors.append(
                f"legacy portable build policy missing from {legacy_rel}: "
                f"{marker}"
            )

    exact_unblock = (
        r"Unblock-File -LiteralPath 'dist\dupez.exe' "
        "-ErrorAction SilentlyContinue"
    )
    if exact_unblock not in legacy:
        errors.append(
            "legacy portable build must limit Mark-of-the-Web removal to "
            r"dist\dupez.exe"
        )
    if "get-childitem" in legacy_lower or "-recurse" in legacy_lower:
        errors.append(
            "legacy portable build must not remove Mark-of-the-Web from the "
            "whole dist tree"
        )

    canonical = _read(canonical_rel)
    for marker in (
        r'"%DUPEZ_PYTHON%" -I scripts\release_preflight.py '
        r'--license-distribution',
        r'packaging\compile_installer.py --mode "%DUPEZ_RELEASE_MODE%" '
        r'--iscc "%_ISCC%"',
        r'copy /Y "dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe"',
    ):
        if marker not in canonical:
            errors.append(
                f"canonical release build policy missing from {canonical_rel}: "
                f"{marker}"
            )
    if r'"%_iscc%" packaging\installer.iss' in canonical.casefold():
        errors.append(
            "canonical release build must invoke ISCC only through the "
            "verified native-snapshot wrapper"
        )

    return errors


def _check_renderer_flag_policy(
    paths: list[Path] | None = None,
) -> list[str]:
    """Reject Chromium flags removed by the packaged QtWebEngine runtime."""

    if paths is None:
        paths = [ROOT / "dupez.py", *(ROOT / "app").rglob("*.py")]
    errors: list[str] = []
    obsolete = "--use-gl=swiftshader"
    for path in paths:
        if not path.is_file():
            continue
        if obsolete in path.read_text(encoding="utf-8", errors="replace").casefold():
            try:
                relative = path.relative_to(ROOT)
            except ValueError:
                relative = path
            errors.append(
                "obsolete QtWebEngine SwiftShader flag is forbidden: "
                f"{relative}"
            )
    return errors


_FORBIDDEN_FROZEN_PREFIXES = (
    # Scapy is deliberately absent from the production lock. Reject it even
    # when an ambient build environment makes it visible to PyInstaller.
    "scapy",
    # v5.8.0 does not ship Group Finder. Revise this explicit release policy
    # when the feature and its dependency boundary are approved for release.
    "anyio",
    "app.social",
    "httpcore",
    "httpx",
    "pydantic",
    "pydantic_core",
    "typing_inspection",
    # Historical exploit/evasion implementation is retained only as source
    # archaeology and must not be reachable or bundled in public artifacts.
    "app.firewall.modules.godmode",
    "app.firewall.recorder_hotkeys",
    # Optional voice/scientific stacks are deliberately excluded from the
    # production lock and must not leak in from a developer environment.
    "fsspec",
    "ipython",
    "jinja2",
    "llvmlite",
    "numba",
    "torch",
    "triton",
    "whisper",
)
_FORBIDDEN_FROZEN_PATHS = (
    "_sounddevice_data/portaudio-binaries/libportaudio64bit-asio.dll",
)
_RELEASE_DATA_MANIFEST = ROOT / "packaging" / "release-data.json"
_BINARY_PROVENANCE_MANIFEST = (
    ROOT / "packaging" / "binary-provenance.json"
)
_DIST_BINARY_PROVENANCE_SCHEMA = "dupez.distribution-binaries.v1"
_SOURCE_BINARY_PROVENANCE_SCHEMA = "dupez.bundled-binaries.v1"
_STANDARD_RELEASE_MODE = "standard-authenticode"
_UNSIGNED_RELEASE_MODE = "explicit-unsigned"
_AUTHENTICODE_TRANSFORM = "pe-authenticode-certificate-table-v1"
_VULNERABILITY_REVIEW_MAX_AGE = timedelta(hours=24)
_VULNERABILITY_REVIEW_FUTURE_SKEW = timedelta(minutes=5)
_RELEASE_DATA_SCHEMA = "dupez.release-data.v1"
_MANAGED_RELEASE_DATA_ROOTS = (
    PurePosixPath("app/assets"),
    PurePosixPath("app/config"),
    PurePosixPath("app/resources"),
    PurePosixPath("app/themes"),
)
_INSTALLER_BINARY_ROOT = PurePosixPath("app/firewall")
_INSTALLER_BINARY_SUFFIXES = {".dll", ".exe", ".sys"}
_REQUIRED_INSTALLER_BINARIES = {
    "app/firewall/clumsy.exe",
    "app/firewall/iup.dll",
    "app/firewall/windivert.dll",
    "app/firewall/windivert64.sys",
}
_INSTALLER_DIST_SOURCES = {
    "dist/dupez-compat.exe",
    "dist/dupez-gpu.exe",
    "dist/license.txt",
    "dist/source_and_relink.txt",
    "dist/third_party_notices.txt",
    "dist/license-payload.json",
}
_INSTALLER_NATIVE_SNAPSHOT = "{#dupeznativesnapshot}"
_MANAGED_FROZEN_DATA_PREFIXES = (
    "app.assets.",
    "app.config.",
    "app.resources.",
    "app.themes.",
)


def _normalise_frozen_name(name: object) -> str:
    return str(name).replace("\\", ".").replace("/", ".").casefold()


def _normalise_frozen_path(name: object) -> str:
    return str(name).replace("\\", "/").strip("/").casefold()


def _matches_frozen_prefix(name: str, prefix: str) -> bool:
    return (
        name == prefix
        or name.startswith(f"{prefix}.")
        or name.startswith(f"{prefix}-")
    )


def _release_payload_paths() -> tuple[set[str], set[str], list[str]]:
    """Return canonical data/binary paths from the release manifest."""
    errors: list[str] = []
    try:
        payload = json.loads(
            _RELEASE_DATA_MANIFEST.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return set(), set(), [
            f"invalid packaging/release-data.json: {exc}"
        ]
    if payload.get("schema") != _RELEASE_DATA_SCHEMA:
        errors.append("unsupported packaging/release-data.json schema")

    paths_by_field: dict[str, set[str]] = {
        "files": set(),
        "binaries": set(),
    }
    for field in paths_by_field:
        values = payload.get(field)
        if not isinstance(values, list) or not values:
            errors.append(
                f"packaging/release-data.json contains no {field}"
            )
            continue
        for value in values:
            if not isinstance(value, str):
                errors.append(
                    f"release-data {field} paths must be strings"
                )
                continue
            relative = PurePosixPath(value)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in value
                or relative.as_posix() != value
            ):
                errors.append(
                    f"unsafe release-data {field} path: {value!r}"
                )
                continue
            canonical = relative.as_posix().casefold()
            if canonical in paths_by_field[field]:
                errors.append(
                    f"duplicate release-data {field} path: {value}"
                )
                continue
            paths_by_field[field].add(canonical)
            source = ROOT.joinpath(*relative.parts)
            if not source.is_file():
                errors.append(
                    f"release-data {field} source missing: {value}"
                )
            if field == "files":
                if not any(
                    root in relative.parents
                    for root in _MANAGED_RELEASE_DATA_ROOTS
                ):
                    errors.append(
                        "release-data path outside managed roots: "
                        f"{value}"
                    )
                lowered_parts = {
                    part.casefold() for part in relative.parts
                }
                lowered_name = relative.name.casefold()
                if (
                    "__pycache__" in lowered_parts
                    or lowered_name.endswith(
                        (".py", ".pyc", ".pyo", ".hmac")
                    )
                    or lowered_name.startswith("patch_monitor_state")
                ):
                    errors.append(
                        "forbidden runtime/source release data: "
                        f"{value}"
                    )
            elif (
                relative.parent != _INSTALLER_BINARY_ROOT
                or relative.suffix.casefold()
                not in _INSTALLER_BINARY_SUFFIXES
            ):
                errors.append(
                    "release binary must be a direct DLL/EXE/SYS child of "
                    f"app/firewall: {value}"
                )

    missing_required = sorted(
        _REQUIRED_INSTALLER_BINARIES - paths_by_field["binaries"]
    )
    if missing_required:
        errors.append(
            "release binary manifest omits required runtime files: "
            + ", ".join(missing_required)
        )
    return paths_by_field["files"], paths_by_field["binaries"], errors


def _release_data_archive_names() -> tuple[set[str], list[str]]:
    data_paths, _, errors = _release_payload_paths()
    archive_names = {
        _normalise_frozen_name(path) for path in data_paths
    }
    return archive_names, errors


def _release_binary_archive_expectations(
    release_binary_paths: set[str] | None = None,
    *,
    provenance_path: Path | None = None,
    expected_mode: str | None = None,
    expected_signer_certificate_sha256: str | None = None,
) -> tuple[dict[str, tuple[int, str]], list[str]]:
    """Return frozen binary hashes from validated source/distribution metadata."""
    errors: list[str] = []
    if release_binary_paths is None:
        _, release_binary_paths, manifest_errors = _release_payload_paths()
        errors.extend(manifest_errors)
    expected_paths = {
        _normalise_frozen_path(path) for path in release_binary_paths
    }

    source_provenance_path = _BINARY_PROVENANCE_MANIFEST
    try:
        source_payload = json.loads(
            source_provenance_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {}, errors + [f"invalid packaging/binary-provenance.json: {exc}"]
    if source_payload.get("schema") != _SOURCE_BINARY_PROVENANCE_SCHEMA:
        errors.append("unsupported packaging/binary-provenance.json schema")
    source_artifacts = source_payload.get("artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        return {}, errors + ["binary provenance manifest contains no artifacts"]

    source_records: dict[str, dict] = {}
    for entry in source_artifacts:
        if not isinstance(entry, dict):
            errors.append("binary provenance artifact must be an object")
            continue
        path = _normalise_frozen_path(entry.get("path") or "")
        if path not in expected_paths:
            errors.append(
                "binary provenance contains a non-release path: "
                f"{entry.get('path')!r}"
            )
            continue
        if path in source_records:
            errors.append(f"duplicate binary provenance path: {path}")
            continue
        size = entry.get("size")
        sha256 = str(entry.get("sha256") or "").casefold()
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            errors.append(f"invalid binary provenance size: {path}")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            errors.append(f"invalid binary provenance SHA-256: {path}")
            continue
        record = dict(entry)
        record["sha256"] = sha256
        source_records[path] = record

    missing = sorted(expected_paths - source_records.keys())
    if missing:
        errors.append(
            "release binaries lack usable provenance: " + ", ".join(missing)
        )
    if errors:
        return {}, errors

    if provenance_path is None or provenance_path == source_provenance_path:
        return {
            path: (entry["size"], entry["sha256"])
            for path, entry in source_records.items()
        }, []

    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"invalid dist/binary-provenance.json: {exc}"]
    if not isinstance(payload, dict) or payload.get("schema") != (
        _DIST_BINARY_PROVENANCE_SCHEMA
    ):
        errors.append("unsupported dist/binary-provenance.json schema")
    mode = payload.get("release_mode") if isinstance(payload, dict) else None
    if mode not in {_STANDARD_RELEASE_MODE, _UNSIGNED_RELEASE_MODE}:
        errors.append("dist binary provenance has an invalid release mode")
    if expected_mode is not None and mode != expected_mode:
        errors.append(
            f"dist binary provenance release mode mismatch: {mode!r} != "
            f"{expected_mode!r}"
        )
    if payload.get("source_provenance_schema") != (
        _SOURCE_BINARY_PROVENANCE_SCHEMA
    ):
        errors.append("dist binary provenance source schema is invalid")

    signer = payload.get("signer_certificate_sha256")
    if mode == _STANDARD_RELEASE_MODE:
        if not re.fullmatch(r"[0-9a-f]{64}", str(signer or "")):
            errors.append("dist binary provenance has no valid signer pin")
        if (
            expected_signer_certificate_sha256 is None
            or signer != expected_signer_certificate_sha256.casefold()
        ):
            errors.append(
                "dist binary provenance signer does not match the authenticated "
                "release signer"
            )
    elif signer is not None:
        errors.append("unsigned dist binary provenance unexpectedly binds a signer")

    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return {}, errors + ["dist binary provenance contains no artifacts"]

    expectations: dict[str, tuple[int, str]] = {}
    for entry in artifacts:
        if not isinstance(entry, dict):
            errors.append("dist binary provenance artifact must be an object")
            continue
        path_value = entry.get("path")
        path = _normalise_frozen_path(path_value or "")
        relative = (
            PurePosixPath(path_value)
            if isinstance(path_value, str)
            else PurePosixPath()
        )
        if (
            not isinstance(path_value, str)
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in path_value
            or relative.as_posix() != path_value
            or path not in expected_paths
        ):
            errors.append(
                f"dist binary provenance contains a non-release path: {path_value!r}"
            )
            continue
        if path in expectations:
            errors.append(f"duplicate dist binary provenance path: {path}")
            continue
        source = source_records[path]
        size = entry.get("size")
        sha256 = str(entry.get("sha256") or "").casefold()
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            errors.append(f"invalid dist binary provenance size: {path}")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            errors.append(f"invalid dist binary provenance SHA-256: {path}")
            continue
        if (
            entry.get("source_size") != source["size"]
            or entry.get("source_sha256") != source["sha256"]
        ):
            errors.append(f"dist binary provenance source binding is invalid: {path}")
        for key in (
            "version",
            "source",
            "source_commit",
            "release_asset",
            "release_asset_sha256",
        ):
            if entry.get(key) != source.get(key):
                errors.append(
                    f"dist binary provenance metadata binding is invalid: "
                    f"{path}: {key}"
                )

        is_clumsy = path == "app/firewall/clumsy.exe"
        signed_transform = is_clumsy and mode == _STANDARD_RELEASE_MODE
        expected_transform = (
            "authenticode-signed-staged-copy"
            if signed_transform
            else "source-exact"
        )
        if entry.get("transform") != expected_transform:
            errors.append(f"dist binary provenance transform is invalid: {path}")
        if signed_transform:
            if entry.get("source_equivalence") != _AUTHENTICODE_TRANSFORM:
                errors.append(
                    "dist Clumsy provenance has no Authenticode source-equivalence "
                    "proof"
                )
            signature = entry.get("authenticode")
            if not isinstance(signature, dict) or (
                signature.get("status") != "Valid"
                or signature.get("signer_certificate_sha256") != signer
            ):
                errors.append(
                    "dist Clumsy provenance does not bind the valid release signer"
                )
        else:
            if size != source["size"] or sha256 != source["sha256"]:
                errors.append(f"source-exact dist binary changed: {path}")
            if entry.get("source_equivalence") is not None:
                errors.append(
                    f"source-exact dist binary has a transform proof: {path}"
                )
            if is_clumsy:
                signature = entry.get("authenticode")
                if not isinstance(signature, dict) or (
                    signature.get("status") != "NotSigned"
                    or signature.get("signer_certificate_sha256") is not None
                ):
                    errors.append(
                        "unsigned dist Clumsy provenance has a signature"
                    )
        expectations[path] = (size, sha256)

    missing = sorted(expected_paths - expectations.keys())
    if missing:
        errors.append(
            "dist release binaries lack usable provenance: "
            + ", ".join(missing)
        )
    return (expectations if not errors else {}), errors


def _check_independent_child_signing_policy(
    *,
    allow_unsigned: bool,
    provenance_path: Path = _BINARY_PROVENANCE_MANIFEST,
    artifacts: Iterable[Path] | None = None,
    archive_reader_cls: object | None = None,
    signature_verifier: object | None = None,
    expected_signer_certificate_sha256: str | None = None,
    source_clumsy_path: Path | None = None,
    source_equivalence_verifier: object | None = None,
) -> list[str]:
    """Measure the Authenticode signature on each packaged Clumsy child.

    Provenance metadata is deliberately not an authority for code-signing
    status: a text-field edit cannot make the independently executed bytes
    trusted. ``provenance_path`` remains accepted for caller compatibility but
    is not consulted for this decision.
    """
    if allow_unsigned:
        return []
    del provenance_path
    expected_signer = str(expected_signer_certificate_sha256 or "").casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_signer):
        return [
            "production release blocked: authenticated release signer identity "
            "is unavailable for packaged Clumsy"
        ]
    source_path = source_clumsy_path or (
        ROOT / "app" / "firewall" / "clumsy.exe"
    )
    try:
        source_payload = source_path.read_bytes()
    except OSError as exc:
        return [
            "production release blocked: cannot read provenance-pinned source "
            f"Clumsy bytes: {exc}"
        ]
    if source_equivalence_verifier is None:
        source_equivalence_verifier = _verify_authenticode_source_equivalence
    frozen_artifacts = list(artifacts or (
        DIST / "DupeZ-GPU.exe",
        DIST / "DupeZ-Compat.exe",
    ))
    if archive_reader_cls is None:
        try:
            from PyInstaller.archive.readers import CArchiveReader
        except Exception as exc:
            return [
                "cannot inspect packaged Clumsy Authenticode signature: "
                f"{exc}"
            ]
        archive_reader_cls = CArchiveReader
    if signature_verifier is None:
        from app.core.update_verify import authenticode_signer_sha256

        signature_verifier = authenticode_signer_sha256

    errors: list[str] = []
    signer_fingerprints: set[str] = set()
    for artifact in frozen_artifacts:
        if not artifact.is_file():
            errors.append(
                "production release blocked: frozen artifact unavailable for "
                f"nested signing measurement: {artifact.name}"
            )
            continue
        try:
            archive = archive_reader_cls(str(artifact))
            matching = [
                name
                for name in archive.toc
                if _normalise_frozen_path(name)
                == "app/firewall/clumsy.exe"
            ]
            if len(matching) != 1:
                errors.append(
                    "production release blocked: expected exactly one packaged "
                    f"app/firewall/clumsy.exe in {artifact.name}; found "
                    f"{len(matching)}"
                )
                continue
            extracted = archive.extract(matching[0])
            if not isinstance(extracted, (bytes, bytearray, memoryview)):
                raise TypeError("archive extraction returned non-bytes")
            packaged_payload = bytes(extracted)
            source_equivalence_verifier(source_payload, packaged_payload)
            with tempfile.TemporaryDirectory(
                prefix="dupez-nested-signature-"
            ) as temp_dir:
                child = Path(temp_dir) / "clumsy.exe"
                child.write_bytes(packaged_payload)
                fingerprint = signature_verifier(str(child))
            measured_signer = str(fingerprint).casefold()
            if measured_signer != expected_signer:
                raise ValueError(
                    "signer certificate does not match the authenticated release "
                    "signer"
                )
            signer_fingerprints.add(measured_signer)
        except Exception as exc:
            errors.append(
                "production release blocked: independently executed packaged "
                f"app/firewall/clumsy.exe in {artifact.name} is not "
                "Authenticode-valid; signing the outer executable or installer "
                f"does not cover the child process: {exc}"
            )
    if not errors and len(signer_fingerprints) != 1:
        errors.append(
            "production release blocked: packaged Clumsy signer identity is "
            "not identical across frozen variants"
        )
    return errors


def _vulnerability_review_timestamp_errors(
    value: object,
    *,
    now: datetime | None = None,
) -> list[str]:
    raw = str(value or "").strip()
    try:
        generated = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return [
            "vulnerability review generated_at_utc must use UTC "
            "YYYY-MM-DDTHH:MM:SSZ"
        ]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    if generated > current + _VULNERABILITY_REVIEW_FUTURE_SKEW:
        return ["vulnerability review timestamp is unacceptably in the future"]
    if current - generated > _VULNERABILITY_REVIEW_MAX_AGE:
        return ["vulnerability review is older than the 24-hour release window"]
    return []


def _check_installer_setup_policy(
    installer_text: str | None = None,
) -> list[str]:
    """Enforce the elevated installer architecture and redirection boundary."""

    text = (
        _read("packaging/installer.iss")
        if installer_text is None
        else installer_text
    )
    errors: list[str] = []
    section = ""
    setup_values: dict[str, list[str]] = {}
    driver_entries: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        section_match = re.fullmatch(r"\[([^]]+)]", stripped)
        if section_match:
            section = section_match.group(1).casefold()
            continue
        if not stripped or stripped.startswith((";", "#")):
            continue
        if section == "setup" and "=" in stripped:
            key, value = stripped.split("=", 1)
            setup_values.setdefault(key.strip().casefold(), []).append(
                value.strip().casefold()
            )
        if section == "files" and re.search(
            r'\bSource\s*:\s*"[^"]+\.sys"',
            stripped,
            re.IGNORECASE,
        ):
            driver_entries.append(f"{line_no}:{stripped}")

    required_directives = {
        "architecturesallowed": ["x64os"],
        "architecturesinstallin64bitmode": ["x64os"],
        "redirectionguard": ["yes"],
    }
    for key, expected in required_directives.items():
        if setup_values.get(key) != expected:
            errors.append(
                "installer setup directive must be exact: "
                f"{key}={expected[0]}"
            )
    if "x64compatible" in text.casefold():
        errors.append(
            "x64compatible is forbidden because the bundled driver requires "
            "native x64 Windows"
        )
    if (
        len(driver_entries) != 1
        or "windivert64.sys" not in driver_entries[0].casefold()
    ):
        errors.append(
            "installer must contain exactly one native-x64 WinDivert64.sys "
            "driver entry"
        )
    return errors


def _check_release_tool_pin_policy(
    manifest_text: str | None = None,
) -> list[str]:
    """Require exact, structured release-tool pins and no ambient discovery."""

    errors: list[str] = []
    if manifest_text is None:
        manifest_path = ROOT / "packaging" / "release-tools.json"
        try:
            metadata = manifest_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_reparse_point(manifest_path)
            ):
                return [
                    "release tool pin manifest must be a regular, "
                    "non-reparse file"
                ]
            raw = _read("packaging/release-tools.json")
        except OSError:
            return ["release tool pin manifest is unavailable"]
    else:
        raw = manifest_text
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ["release tool pin manifest is malformed"]
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "iscc",
        "signtool",
    }:
        return ["release tool pin manifest structure is invalid"]
    if payload.get("schema") != "dupez.release-tools.v1":
        errors.append("release tool pin manifest schema is invalid")

    expected_fields = {
        "iscc": {
            "version",
            "default_base",
            "relative_path",
            "sha256",
            "signer_certificate_sha256",
            "signer_subject",
            "signer_thumbprint",
        },
        "signtool": {
            "version",
            "sdk_version",
            "default_base",
            "relative_path",
            "sha256",
            "signer_certificate_sha256",
            "signer_subject",
            "signer_thumbprint",
        },
    }
    for name, fields in expected_fields.items():
        pin = payload.get(name)
        if not isinstance(pin, dict) or set(pin) != fields:
            errors.append(f"{name} release tool pin structure is invalid")
            continue
        path = str(pin["relative_path"])
        path_parts = PureWindowsPath(path).parts
        if (
            pin["default_base"] != "ProgramFilesX86"
            or PureWindowsPath(path).is_absolute()
            or any(part in {".", ".."} for part in path_parts)
            or "*" in path
            or "?" in path
        ):
            errors.append(f"{name} release tool path pin is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(pin["sha256"])):
            errors.append(f"{name} release tool SHA-256 pin is invalid")
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(pin["signer_certificate_sha256"]),
        ):
            errors.append(
                f"{name} release tool certificate SHA-256 pin is invalid"
            )
        if not re.fullmatch(
            r"[0-9a-f]{40}", str(pin["signer_thumbprint"])
        ):
            errors.append(f"{name} release tool signer pin is invalid")
        if not str(pin["signer_subject"]).startswith("CN="):
            errors.append(f"{name} release tool signer subject is invalid")

    iscc = payload.get("iscc")
    if isinstance(iscc, dict) and (
        not re.fullmatch(r"\d+\.\d+\.\d+", str(iscc.get("version", "")))
        or iscc.get("relative_path") != r"Inno Setup 6\ISCC.exe"
    ):
        errors.append("ISCC release tool version/path binding is invalid")
    signtool = payload.get("signtool")
    if isinstance(signtool, dict):
        sdk_version = str(signtool.get("sdk_version", ""))
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", sdk_version)
            or not re.fullmatch(
                r"\d+\.\d+\.\d+\.\d+",
                str(signtool.get("version", "")),
            )
            or signtool.get("relative_path")
            != rf"Windows Kits\10\bin\{sdk_version}\x64\signtool.exe"
        ):
            errors.append("SignTool release tool version/path binding is invalid")

    finalizer = _read("scripts/finalize_release.ps1")
    for marker in (
        r"packaging\release-tools.json",
        "Read-ReleaseToolPins",
        "Resolve-PinnedReleaseTool",
        "Get-FileHash",
        "Get-AuthenticodeSignature",
        "signer_thumbprint",
    ):
        if marker not in finalizer:
            errors.append(f"release tool verification policy is missing: {marker}")
    for forbidden in (
        "Get-WindowsSdkSignToolCandidates",
        "Sort-Object FullName -Descending",
    ):
        if forbidden in finalizer:
            errors.append(f"ambient release tool discovery is forbidden: {forbidden}")

    build = _read("packaging/build_variants.bat").casefold()
    for forbidden in ("where signtool", "where iscc"):
        if forbidden in build:
            errors.append(f"ambient release tool lookup is forbidden: {forbidden}")
    sign_scope_start = build.find("\n:sign_file")
    sign_scope_end = build.find("\n:force_delete", sign_scope_start + 1)
    sign_verify = (
        '"%dupez_python%" -i packaging\\release_data.py verify-tool '
        '--name signtool --path "%_signtool%"'
    )
    sign_invoke = '"%_signtool%" sign '
    sign_scope = (
        build[sign_scope_start:sign_scope_end]
        if sign_scope_start >= 0 and sign_scope_end > sign_scope_start
        else ""
    )
    if (
        sign_verify not in sign_scope
        or sign_invoke not in sign_scope
        or sign_scope.find(sign_verify) > sign_scope.find(sign_invoke)
    ):
        errors.append(
            "SignTool must be re-verified from repository pins immediately "
            "before signing"
        )
    release_data = _read("packaging/release_data.py")
    iscc_verify = 'verified_iscc = tool_verifier("iscc", iscc)'
    iscc_invoke = "[str(verified_iscc), str(definition)]"
    if (
        "def verify_release_tool(" not in release_data
        or 'subparsers.add_parser("verify-tool")' not in release_data
        or iscc_verify not in release_data
        or iscc_invoke not in release_data
        or release_data.find(iscc_verify) > release_data.find(iscc_invoke)
    ):
        errors.append(
            "ISCC must be re-verified from repository pins immediately "
            "before compilation"
        )
    return errors


def _check_installer_payload_policy(
    installer_text: str | None = None,
    *,
    release_data_paths: set[str] | None = None,
    release_binary_paths: set[str] | None = None,
) -> list[str]:
    """Require the Inno installer to use only manifest-approved files."""
    errors: list[str] = []
    if release_data_paths is None or release_binary_paths is None:
        (
            manifest_data,
            manifest_binaries,
            manifest_errors,
        ) = _release_payload_paths()
        errors.extend(manifest_errors)
        if release_data_paths is None:
            release_data_paths = manifest_data
        if release_binary_paths is None:
            release_binary_paths = manifest_binaries

    expected_data_sources = {
        str(path).replace("\\", "/").casefold()
        for path in release_data_paths
    }
    logical_binary_by_source = {
        f"{_INSTALLER_NATIVE_SNAPSHOT}/{logical}": logical
        for logical in (
            str(path).replace("\\", "/").casefold()
            for path in release_binary_paths
        )
    }
    expected_sources = expected_data_sources | set(logical_binary_by_source)
    expected_sources.update(_INSTALLER_DIST_SOURCES)
    text = installer_text or _read("packaging/installer.iss")
    folded_text = text.casefold()
    snapshot_markers = (
        '#define dupeznativesnapshot getenv("dupez_installer_native_snapshot")',
        '#if dupeznativesnapshot == ""',
        '#error "dupez_installer_native_snapshot is required;',
    )
    for marker in snapshot_markers:
        if marker not in folded_text:
            errors.append(
                "installer native snapshot policy missing from "
                f"packaging/installer.iss: {marker}"
            )
    actual_sources: dict[str, int] = {}
    section = ""

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        section_match = re.fullmatch(r"\[([^]]+)]", stripped)
        if section_match:
            section = section_match.group(1).casefold()
            continue
        if section != "files" or not stripped or stripped.startswith(";"):
            continue

        source_match = re.search(
            r'(?:^|;)\s*Source\s*:\s*"([^"]+)"',
            stripped,
            re.IGNORECASE,
        )
        if not source_match:
            errors.append(
                "installer [Files] entry must use one explicit quoted "
                f"Source at packaging/installer.iss:{line_no}"
            )
            continue
        source_value = source_match.group(1)
        flags_match = re.search(
            r"(?:^|;)\s*Flags\s*:\s*([^;]+)",
            stripped,
            re.IGNORECASE,
        )
        flags = {
            flag.casefold()
            for flag in (flags_match.group(1).split() if flags_match else [])
        }
        if "recursesubdirs" in flags or "createallsubdirs" in flags:
            errors.append(
                "recursive installer source is forbidden at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )
        if "*" in source_value or "?" in source_value:
            errors.append(
                "installer source wildcards are forbidden at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )

        source_posix = source_value.replace("\\", "/")
        relative = PurePosixPath(source_posix)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or re.match(r"^[a-zA-Z]:", source_posix)
            or relative.as_posix() != source_posix
        ):
            errors.append(
                "unsafe installer source path at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )
            continue
        source = relative.as_posix().casefold()
        if source in actual_sources:
            errors.append(
                "duplicate installer source at packaging/installer.iss:"
                f"{line_no}: {source_value}"
            )
        else:
            actual_sources[source] = line_no

        source_parts = {part.casefold() for part in relative.parts}
        source_name = relative.name.casefold()
        if "clumsy_src" in source_parts or "__pycache__" in source_parts:
            errors.append(
                "forbidden source/cache tree in installer at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )
        if source_name.endswith((".py", ".pyc", ".pyo", ".hmac")):
            errors.append(
                "forbidden source/cache/HMAC file in installer at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )
        if source_name.startswith("patch_monitor_state"):
            errors.append(
                "forbidden patch-monitor runtime state in installer at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )

        destination_match = re.search(
            r'(?:^|;)\s*DestDir\s*:\s*"([^"]+)"',
            stripped,
            re.IGNORECASE,
        )
        destination = (
            destination_match.group(1).rstrip("\\/").casefold()
            if destination_match
            else ""
        )
        logical_source = logical_binary_by_source.get(source, source)
        logical_relative = PurePosixPath(logical_source)
        if source in _INSTALLER_DIST_SOURCES:
            expected_destination = "{app}"
        else:
            expected_destination = (
                "{app}\\"
                + str(logical_relative.parent).replace("/", "\\")
            ).casefold()
        if destination != expected_destination:
            errors.append(
                "installer source has an unexpected destination at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )

        destination_name_match = re.search(
            r'(?:^|;)\s*DestName\s*:\s*"([^"]+)"',
            stripped,
            re.IGNORECASE,
        )
        destination_name = (
            destination_name_match.group(1).casefold()
            if destination_name_match
            else ""
        )
        if source == "dist/dupez-gpu.exe":
            if destination_name != "dupez.exe":
                errors.append(
                    "GPU installer source must be renamed to dupez.exe"
                )
        elif destination_name:
            errors.append(
                "installer source renaming is forbidden at "
                f"packaging/installer.iss:{line_no}: {source_value}"
            )

    missing = sorted(expected_sources - actual_sources.keys())
    if missing:
        errors.append(
            "installer omits manifest-approved sources: "
            + ", ".join(missing[:5])
        )
    unmanaged = sorted(actual_sources.keys() - expected_sources)
    if unmanaged:
        errors.append(
            "installer contains unmanaged sources: "
            + ", ".join(unmanaged[:10])
        )
    return errors


def _check_frozen_dependency_policy(
    artifacts: Iterable[Path],
    *,
    archive_reader_cls=None,
    release_data_names: set[str] | None = None,
    release_binary_expectations: dict[str, tuple[int, str]] | None = None,
) -> list[str]:
    """Reject contaminated archives and verify managed native bytes."""
    errors: list[str] = []
    if release_data_names is None:
        release_data_names, manifest_errors = _release_data_archive_names()
        errors.extend(manifest_errors)
        if manifest_errors:
            return errors
    else:
        release_data_names = {
            _normalise_frozen_name(name) for name in release_data_names
        }
    if release_binary_expectations is None:
        (
            release_binary_expectations,
            provenance_errors,
        ) = _release_binary_archive_expectations()
        errors.extend(provenance_errors)
        if provenance_errors:
            return errors
    else:
        release_binary_expectations = {
            _normalise_frozen_path(path): expectation
            for path, expectation in release_binary_expectations.items()
        }
    if archive_reader_cls is None:
        try:
            from PyInstaller.archive.readers import CArchiveReader
        except Exception as exc:
            return [
                "cannot inspect frozen dependency policy because PyInstaller "
                f"archive support is unavailable: {exc}"
            ]
        archive_reader_cls = CArchiveReader

    for artifact in artifacts:
        if not artifact.is_file():
            errors.append(f"frozen artifact missing: {artifact}")
            continue
        try:
            archive = archive_reader_cls(str(artifact))
            outer_entries: dict[str, list[object]] = {}
            for name in archive.toc:
                outer_entries.setdefault(
                    _normalise_frozen_path(name), []
                ).append(name)
            outer_names = {
                _normalise_frozen_name(name) for name in archive.toc
            }
            pyz_keys = [
                name
                for name in archive.toc
                if _normalise_frozen_name(name) == "pyz.pyz"
            ]
            if len(pyz_keys) != 1:
                errors.append(
                    "frozen archive must contain exactly one PYZ.pyz: "
                    f"{artifact.name}: found {len(pyz_keys)}"
                )
                continue
            embedded = archive.open_embedded_archive(pyz_keys[0])
            inner_names = {
                _normalise_frozen_name(name) for name in embedded.toc
            }
        except Exception as exc:
            errors.append(
                f"cannot inspect frozen archive {artifact.name}: {exc}"
            )
            continue

        archive_names = outer_names | inner_names
        for forbidden_path in _FORBIDDEN_FROZEN_PATHS:
            if forbidden_path in outer_entries:
                errors.append(
                    "forbidden frozen native payload in "
                    f"{artifact.name}: {forbidden_path}"
                )
        expected_binary_paths = set(release_binary_expectations)
        actual_managed_binaries = {
            path
            for path in outer_entries
            if path.startswith("app/firewall/")
            and PurePosixPath(path).suffix in _INSTALLER_BINARY_SUFFIXES
        }
        unmanaged_binaries = sorted(
            actual_managed_binaries - expected_binary_paths
        )
        if unmanaged_binaries:
            errors.append(
                "unmanaged packaged native binaries in "
                f"{artifact.name}: {', '.join(unmanaged_binaries[:5])}"
            )
        missing_binaries = sorted(
            expected_binary_paths - outer_entries.keys()
        )
        if missing_binaries:
            errors.append(
                "required packaged native binaries missing from "
                f"{artifact.name}: {', '.join(missing_binaries[:5])}"
            )

        expected_by_basename = {
            PurePosixPath(path).name: path
            for path in expected_binary_paths
        }
        root_duplicates = sorted(
            path
            for path in outer_entries
            if "/" not in path and path in expected_by_basename
        )
        if root_duplicates:
            errors.append(
                "root-level duplicate managed binaries in "
                f"{artifact.name}: {', '.join(root_duplicates[:5])}"
            )

        for binary_path, (expected_size, expected_sha256) in sorted(
            release_binary_expectations.items()
        ):
            matching_entries = outer_entries.get(binary_path, [])
            if len(matching_entries) != 1:
                if len(matching_entries) > 1:
                    errors.append(
                        "duplicate packaged native binary path in "
                        f"{artifact.name}: {binary_path}"
                    )
                continue
            try:
                extracted = archive.extract(matching_entries[0])
            except Exception as exc:
                errors.append(
                    "cannot extract packaged native binary from "
                    f"{artifact.name}: {binary_path}: {exc}"
                )
                continue
            if not isinstance(extracted, (bytes, bytearray, memoryview)):
                errors.append(
                    "packaged native binary extraction returned non-bytes in "
                    f"{artifact.name}: {binary_path}"
                )
                continue
            actual_size = len(extracted)
            if actual_size != expected_size:
                errors.append(
                    "packaged native binary size mismatch in "
                    f"{artifact.name}: {binary_path}: "
                    f"{actual_size} != {expected_size}"
                )
            actual_sha256 = hashlib.sha256(extracted).hexdigest()
            if actual_sha256 != expected_sha256:
                errors.append(
                    "packaged native binary SHA-256 mismatch in "
                    f"{artifact.name}: {binary_path}: {actual_sha256}"
                )

        unmanaged_data = sorted(
            name
            for name in outer_names
            if name.startswith(_MANAGED_FROZEN_DATA_PREFIXES)
            and name not in release_data_names
        )
        if unmanaged_data:
            errors.append(
                "unmanaged packaged data in "
                f"{artifact.name}: {', '.join(unmanaged_data[:5])}"
            )
        missing_data = sorted(release_data_names - outer_names)
        if missing_data:
            errors.append(
                "required packaged data missing from "
                f"{artifact.name}: {', '.join(missing_data[:5])}"
            )
        for prefix in _FORBIDDEN_FROZEN_PREFIXES:
            matches = sorted(
                name
                for name in archive_names
                if _matches_frozen_prefix(name, prefix)
            )
            if matches:
                sample = ", ".join(matches[:3])
                errors.append(
                    "forbidden frozen dependency in "
                    f"{artifact.name}: {prefix} ({sample})"
                )
    return errors


def _check_frozen_runtime_import_policy() -> list[str]:
    """Ensure the packaged executable proves its core Qt imports work."""
    errors: list[str] = []
    launcher = _read("dupez.py")
    for token in (
        "--verify-runtime-imports",
        "import PyQt6.sip",
        "QtCore",
        "QtWidgets",
        "QtWebEngineWidgets",
    ):
        if token not in launcher:
            errors.append(
                f"frozen runtime import verifier missing from dupez.py: {token}"
            )

    variant_build = _read("packaging/build_variants.bat")
    if (
        '"dist\\DupeZ-GPU.exe" --verify-runtime-imports'
        not in variant_build
    ):
        errors.append(
            "GPU build does not run the frozen runtime import verifier"
        )
    return errors


def _powershell_path() -> Path:
    return _POWERSHELL


def _resolve_under(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes release directory: {path}")
    return resolved


def _query_authenticode(
    paths: list[Path],
) -> tuple[dict[str, dict[str, object]], str]:
    """Measure trust, signer identity, and timestamp presence per artifact."""
    if os.name != "nt":
        return {}, "Authenticode dist checks require Windows"
    powershell = _powershell_path()
    if not powershell.is_file():
        return {}, "PowerShell not found for Authenticode dist checks"

    try:
        safe_paths = [_resolve_under(path, DIST) for path in paths]
    except ValueError as exc:
        return {}, str(exc)
    env = os.environ.copy()
    env["DUPEZ_AUTHENTICODE_PATHS"] = json.dumps(
        [str(path) for path in safe_paths]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
# Autoloading Microsoft.PowerShell.Security can fail in Python-launched
# Windows PowerShell when inherited type data is already registered. Loading
# the signed system manifest by its PSHOME path avoids that ambiguous lookup.
$securityModule = Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
Import-Module -Name $securityModule -ErrorAction Stop
$paths = $env:DUPEZ_AUTHENTICODE_PATHS | ConvertFrom-Json
$out = @()
foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $sig = Get-AuthenticodeSignature -LiteralPath $path
    $signerFingerprint = $null
    if ($null -ne $sig.SignerCertificate) {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha256.ComputeHash($sig.SignerCertificate.RawData)
            $signerFingerprint = ([System.BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
        }
        finally { $sha256.Dispose() }
    }
    $out += [pscustomobject]@{
        Name = Split-Path -Leaf $path
        Status = $sig.Status.ToString()
        SignerCertificateSha256 = $signerFingerprint
        TimestampPresent = ($null -ne $sig.TimeStamperCertificate)
    }
}
$out | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
            env=env,
        )
    except Exception as exc:
        return {}, f"Authenticode query failed: {exc}"
    if completed.returncode != 0:
        return {}, f"Authenticode query failed: {completed.stderr.strip()}"
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {}, f"Authenticode query returned invalid JSON: {exc}"
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return {}, "Authenticode query returned unexpected payload"
    measurements: dict[str, dict[str, object]] = {}
    for entry in payload:
        if isinstance(entry, dict):
            name = str(entry.get("Name") or "")
            status = str(entry.get("Status") or "")
            signer_value = entry.get("SignerCertificateSha256")
            signer = (
                str(signer_value).casefold()
                if signer_value is not None
                else None
            )
            if name:
                measurements[name] = {
                    "status": status,
                    "signer_certificate_sha256": signer,
                    "timestamp_present": entry.get("TimestampPresent") is True,
                }
    return measurements, ""


def _check_outer_authenticode_policy(
    paths: list[Path],
    *,
    expected_signer_certificate_sha256: str | None,
    query_fn=None,
) -> list[str]:
    """Bind every standard-mode outer artifact to one trusted signer.

    ``Get-AuthenticodeSignature.Status == Valid`` alone is insufficient: a
    different valid publisher certificate must not satisfy release policy.
    The timestamp check also preserves the build's RFC3161 requirement on the
    exact bytes being approved for distribution.
    """
    query = query_fn or _query_authenticode
    measurements, error = query(paths)
    if error:
        return [error]

    expected_signer = str(
        expected_signer_certificate_sha256 or ""
    ).casefold()
    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-f]{64}", expected_signer):
        errors.append(
            "outer Authenticode policy cannot bind the authenticated "
            "release signer"
        )

    for path in paths:
        measurement = measurements.get(path.name)
        if not isinstance(measurement, dict):
            errors.append(
                "release artifact Authenticode measurement is missing: "
                f"dist/{path.name}"
            )
            continue
        status = measurement.get("status")
        if status != "Valid":
            errors.append(
                "release artifact is not Authenticode-valid: "
                f"dist/{path.name}: {status or 'missing status'}"
            )
        measured_signer = str(
            measurement.get("signer_certificate_sha256") or ""
        ).casefold()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", measured_signer)
            or measured_signer != expected_signer
        ):
            errors.append(
                "release artifact signer does not match the authenticated "
                f"release signer: dist/{path.name}"
            )
        if measurement.get("timestamp_present") is not True:
            errors.append(
                "release artifact has no acceptable Authenticode timestamp: "
                f"dist/{path.name}"
            )
    return errors


def _verify_update_sidecars_and_manifest(
    dist: Path,
    version: str,
    *,
    trusted_pubkeys_pem: Iterable[str] | None = None,
    allow_unsigned: bool = False,
) -> tuple[UpdateManifest | None, list[str]]:
    """Verify that updater sidecars authenticate the exact release installer.

    A caller-supplied trust key is the existing isolated-test seam and never
    occurs in ``check_dist``. Such fixtures may intentionally use unsigned
    dummy bytes; the production path requires both Authenticode trust and the
    certificate fingerprint bound by the manifest.
    """
    installer = dist / "DupeZ_Setup.exe"
    manifest_path = dist / "DupeZ_Setup.exe.manifest.json"
    signature_path = dist / "DupeZ_Setup.exe.manifest.sig"
    if not all(
        path.is_file()
        for path in (installer, manifest_path, signature_path)
    ):
        return None, []

    try:
        manifest_bytes = manifest_path.read_bytes()
        signature_bytes = signature_path.read_bytes()
        kwargs = {}
        if trusted_pubkeys_pem is not None:
            kwargs["trusted_pubkeys_pem"] = trusted_pubkeys_pem
        fixture_trust_override = trusted_pubkeys_pem is not None
        effective_allow_unsigned = allow_unsigned or fixture_trust_override
        manifest: UpdateManifest = verify_update_manifest(
            manifest_bytes,
            signature_bytes,
            allow_unsigned=effective_allow_unsigned,
            **kwargs,
        )
    except (OSError, SigVerifyError, ValueError) as exc:
        return None, [f"update sidecar verification failed: {exc}"]

    errors: list[str] = []
    if manifest.version != version:
        errors.append(
            "update manifest version mismatch: "
            f"{manifest.version} != {version}"
        )
    if manifest.installer_filename != installer.name:
        errors.append(
            "update manifest installer mismatch: "
            f"{manifest.installer_filename!r} != {installer.name!r}"
        )
    try:
        verify_installer_sha256(str(installer), manifest)
    except SigVerifyError as exc:
        errors.append(f"update manifest does not match installer: {exc}")
    try:
        from app.core.update_verify import verify_installer_authenticode

        verify_installer_authenticode(
            str(installer),
            manifest,
            allow_unsigned=effective_allow_unsigned,
        )
    except SigVerifyError as exc:
        errors.append(
            "update manifest Authenticode signer binding failed: "
            f"{exc}"
        )
    return manifest, errors


def _verify_update_sidecars(
    dist: Path,
    version: str,
    *,
    trusted_pubkeys_pem: Iterable[str] | None = None,
    allow_unsigned: bool = False,
) -> list[str]:
    """Compatibility wrapper returning only sidecar validation errors."""
    _, errors = _verify_update_sidecars_and_manifest(
        dist,
        version,
        trusted_pubkeys_pem=trusted_pubkeys_pem,
        allow_unsigned=allow_unsigned,
    )
    return errors


def _check_installer_alias(dist: Path, version: str) -> list[str]:
    """Require the stable installer alias to be an exact byte-for-byte copy."""
    versioned = dist / f"DupeZ_v{version}_Setup.exe"
    stable = dist / "DupeZ_Setup.exe"
    if not versioned.is_file() or not stable.is_file():
        return []
    if versioned.stat().st_size != stable.stat().st_size:
        return [
            "stable installer alias differs from the versioned installer: "
            "size mismatch"
        ]

    def digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    if digest(versioned) != digest(stable):
        return [
            "stable installer alias differs from the versioned installer: "
            "SHA-256 mismatch"
        ]
    return []


def _check_workflow_action_pins(
    workflows_dir: Path | None = None,
) -> list[str]:
    """Require immutable action revisions in both workflow suffix forms."""
    directory = workflows_dir or (ROOT / ".github" / "workflows")
    action_re = re.compile(r"uses:\s*[^@\s]+@([^\s#]+)")
    errors: list[str] = []
    workflows = sorted(
        path
        for pattern in ("*.yml", "*.yaml")
        for path in directory.glob(pattern)
        if path.is_file()
    )
    for workflow in workflows:
        for ref in action_re.findall(workflow.read_text(encoding="utf-8")):
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                errors.append(
                    f"mutable GitHub Action reference: {workflow.name}: {ref}"
                )
    return errors


def _check_workflow_run_context_policy(
    workflows: Iterable[Path] | None = None,
) -> list[str]:
    """Keep GitHub expressions out of protected release shell source.

    GitHub substitutes ``${{ ... }}`` expressions before it hands a ``run``
    scalar to the selected shell.  Values that can vary between dispatches
    therefore belong in step-level ``env`` mappings and must be consumed only
    through the shell's environment-variable syntax.
    """
    workflow_paths = tuple(workflows) if workflows is not None else (
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / ".github" / "workflows" / "unsigned-public-release.yml",
    )
    errors: list[str] = []

    for workflow in workflow_paths:
        if not workflow.is_file():
            errors.append(
                f"protected release workflow is missing: {workflow.name}"
            )
            continue

        try:
            documents = tuple(
                yaml.compose_all(
                    workflow.read_text(encoding="utf-8"),
                    Loader=yaml.BaseLoader,
                )
            )
        except yaml.YAMLError as exc:
            problem = getattr(exc, "problem", None) or type(exc).__name__
            errors.append(
                "invalid protected release workflow YAML: "
                f"{workflow.name}: {problem}"
            )
            continue

        visited: set[int] = set()

        def inspect_node(node: yaml.nodes.Node | None) -> None:
            if node is None or id(node) in visited:
                return
            visited.add(id(node))

            if isinstance(node, yaml.nodes.MappingNode):
                for key_node, value_node in node.value:
                    if (
                        isinstance(key_node, yaml.nodes.ScalarNode)
                        and key_node.value == "run"
                    ):
                        line = value_node.start_mark.line + 1
                        if not isinstance(value_node, yaml.nodes.ScalarNode):
                            errors.append(
                                "non-scalar protected release workflow run "
                                f"block: {workflow.name}:{line}"
                            )
                        elif "${{" in value_node.value:
                            errors.append(
                                "unsafe GitHub context interpolation in "
                                "protected release workflow run block: "
                                f"{workflow.name}:{line}; pass contexts "
                                "through step env"
                            )
                    inspect_node(value_node)
            elif isinstance(node, yaml.nodes.SequenceNode):
                for item in node.value:
                    inspect_node(item)

        for document in documents:
            inspect_node(document)

    return errors


def check_source(expected_version: str | None = None) -> list[str]:
    errors: list[str] = []
    versions = {
        "app/__version__.py": _match_version(
            "app/__version__.py",
            r'__version__\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "packaging/installer.iss": _match_version(
            "packaging/installer.iss",
            r'#define MyAppVersion\s+"(\d+\.\d+\.\d+)"',
        ),
        "packaging/build_variants.bat": _match_version(
            "packaging/build_variants.bat",
            r'set "DUPEZ_VERSION=(\d+\.\d+\.\d+)"',
        ),
        "packaging/build.bat": _match_version(
            "packaging/build.bat",
            r'set "DUPEZ_VERSION=(\d+\.\d+\.\d+)"',
        ),
        "packaging/version_info.py": _match_version(
            "packaging/version_info.py",
            r"StringStruct\('FileVersion',\s+'(\d+\.\d+\.\d+)\.0'\)",
        ),
        "packaging/dupez.manifest": _match_version(
            "packaging/dupez.manifest",
            r'version="(\d+\.\d+\.\d+)\.0"',
        ),
        "packaging/dupez_compat.manifest": _match_version(
            "packaging/dupez_compat.manifest",
            r'version="(\d+\.\d+\.\d+)\.0"',
        ),
        "README.md": _match_version(
            "README.md",
            r"^# DupeZ v(\d+\.\d+\.\d+)$",
        ),
        "scripts/finalize_release.ps1": _match_version(
            "scripts/finalize_release.ps1",
            r'\[string\]\$Version\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "scripts/stage_release.ps1": _match_version(
            "scripts/stage_release.ps1",
            r'\[string\]\$Version\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "scripts/release_gate_launcher.ps1": _match_version(
            "scripts/release_gate_launcher.ps1",
            r'\[string\]\$Version\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "scripts/blocked_release_gates_sequence.ps1": _match_version(
            "scripts/blocked_release_gates_sequence.ps1",
            r'\[string\]\$Version\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "scripts/record_manual_release_validation.ps1": _match_version(
            "scripts/record_manual_release_validation.ps1",
            r'\[string\]\$Version\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "scripts/release_gate_launcher.cmd": _match_version(
            "scripts/release_gate_launcher.cmd",
            r"^set VERSION=(\d+\.\d+\.\d+)$",
        ),
        ".github/workflows/release.yml": _match_version(
            ".github/workflows/release.yml",
            r"default:\s*'(\d+\.\d+\.\d+)'",
        ),
        ".github/workflows/unsigned-public-release.yml": _match_version(
            ".github/workflows/unsigned-public-release.yml",
            r"default:\s*'(\d+\.\d+\.\d+)'",
        ),
    }
    fixed_file_versions = {
        "packaging/version_info.py FixedFileInfo.filevers": (
            _match_fixed_file_version("packaging/version_info.py", "filevers")
        ),
        "packaging/version_info.py FixedFileInfo.prodvers": (
            _match_fixed_file_version("packaging/version_info.py", "prodvers")
        ),
    }
    wanted = expected_version or versions["app/__version__.py"]
    for path, version in versions.items():
        if version != wanted:
            errors.append(f"version mismatch: {path}: {version} != {wanted}")
    wanted_fixed = f"{wanted}.0"
    for field, version in fixed_file_versions.items():
        if version != wanted_fixed:
            errors.append(
                f"version mismatch: {field}: {version} != {wanted_fixed}"
            )
    for rel, marker in (
        ("CHANGELOG.md", f"## v{wanted} "),
        ("ROADMAP.md", f"## v{wanted} "),
        (f"docs/release-notes/v{wanted}.md", f"# DupeZ v{wanted}"),
    ):
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"release-version document missing: {rel}")
        elif marker not in _read(rel):
            errors.append(
                f"release-version marker missing from {rel}: {marker!r}"
            )

    for rel, marker in (
        ("README.md", "badge/python-3.12%20%7C%203.13-green"),
        ("README.md", "Python 3.12 or 3.13 for source use"),
        ("app/gui/dashboard.py", r"Python 3.12\u20133.13"),
    ):
        if marker not in _read(rel):
            errors.append(
                f"supported Python contract missing from {rel}: {marker!r}"
            )

    for required in (
        "SECURITY.md",
        ".github/CODEOWNERS",
        "packaging/binary-provenance.json",
        "packaging/license-policy.json",
        "packaging/third-party-components.json",
        "packaging/licenses/IUP-LICENSE.txt",
        "packaging/licenses/Inno-Setup-LICENSE.txt",
        "packaging/licenses/Qt-WebEngine-NOTICE.txt",
        "packaging/licenses/pyserial-LICENSE.txt",
        "packaging/release-data.json",
        "packaging/release-tools.json",
        "packaging/release_data.py",
        "packaging/requirements-build.in",
        "packaging/requirements-build-locked.txt",
        "requirements-test.in",
        "requirements-test-locked.txt",
        "requirements.txt",
        "requirements-locked.txt",
        "scripts/license_payload.py",
        "docs/legal/DISTRIBUTION_BASIS_V5.8.0.md",
        "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
    ):
        if not (ROOT / required).is_file():
            errors.append(f"required release-control file missing: {required}")

    license_policy_errors, _ = _check_license_policy()
    errors.extend(license_policy_errors)

    if "--hash=sha256:" not in _read("requirements-locked.txt"):
        errors.append("requirements-locked.txt has no SHA-256 hashes")
    if "--hash=sha256:" not in _read("requirements-test-locked.txt"):
        errors.append("requirements-test-locked.txt has no SHA-256 hashes")
    requirements_shim = [
        line.strip()
        for line in _read("requirements.txt").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if requirements_shim != ["-r requirements-locked.txt"]:
        errors.append(
            "requirements.txt must delegate only to requirements-locked.txt"
        )
    if "--hash=sha256:" not in _read(
        "packaging/requirements-build-locked.txt"
    ):
        errors.append(
            "packaging/requirements-build-locked.txt has no SHA-256 hashes"
        )
    (
        release_data_paths,
        release_binary_paths,
        release_data_errors,
    ) = _release_payload_paths()
    errors.extend(release_data_errors)
    errors.extend(_check_installer_setup_policy())
    errors.extend(_check_release_tool_pin_policy())
    errors.extend(
        _check_installer_payload_policy(
            release_data_paths=release_data_paths,
            release_binary_paths=release_binary_paths,
        )
    )
    shared_build_rel = "packaging/build_common.py"
    shared_build_text = _read(shared_build_rel)
    for required_input in ("pyinstaller_datas", "pyinstaller_binaries"):
        if required_input not in shared_build_text:
            errors.append(
                "shared PyInstaller build bypasses an explicit release input: "
                f"{shared_build_rel} omits {required_input}"
            )

    legacy_spec_rel = "packaging/dupez.spec"
    legacy_spec_text = _read(legacy_spec_rel)
    for marker in (
        "import build_common as shared_build",
        "shared_build.build_variant(",
    ):
        if marker not in legacy_spec_text:
            errors.append(
                "legacy PyInstaller spec bypasses the shared hardened builder: "
                f"{legacy_spec_rel} omits {marker!r}"
            )

    for marker in (
        'os.environ["DUPEZ_BUILD_ANALYSIS"] = "1"',
        'os.environ["DUPEZ_FORCE_USER_DATA"] = "1"',
        'os.environ["DUPEZ_USER_ROOT"] = analysis_user_root',
        "_configure_build_analysis_state()",
    ):
        if marker not in shared_build_text:
            errors.append(
                "PyInstaller analysis-state isolation is incomplete: "
                f"{shared_build_rel} omits {marker!r}"
            )

    for rel in ("packaging/build_common.py", "packaging/dupez.spec"):
        if re.search(r"\bupx\s*=\s*True\b", _read(rel)):
            errors.append(
                "UPX must remain disabled for Defender-friendly releases: "
                f"{rel}"
            )

    unsafe_defender_patterns = (
        r"Add-MpPreference",
        r"Set-MpPreference",
        r"DisableRealtimeMonitoring",
        r"Exclude\s+%TEMP%",
        r"add an exception\s+for the DupeZ install folder",
    )
    scanned_text = "\n".join(
        _read(rel)
        for rel in (
            "README.md",
            "app/core/diagnostics.py",
            "app/gui/panels/help_panel.py",
            "packaging/build.bat",
            "packaging/build_variants.bat",
        )
    )
    for pattern in unsafe_defender_patterns:
        if re.search(pattern, scanned_text, re.IGNORECASE):
            errors.append(
                "unsafe Defender-exclusion guidance or policy mutation found: "
                f"{pattern}"
            )

    for rel in ("packaging/build.bat", "packaging/build_variants.bat"):
        errors.extend(_check_signtool_policy(rel))
        errors.extend(_check_hermetic_python_policy(rel))

    errors.extend(_check_build_entrypoint_policy())
    errors.extend(_check_renderer_flag_policy())
    errors.extend(_check_frozen_runtime_import_policy())

    variant_build = _read("packaging/build_variants.bat")
    for artifact in (
        r'call :sign_file "dist\DupeZ-GPU.exe"',
        r'call :sign_file "dist\DupeZ-Compat.exe"',
        r'call :sign_file "dist\%DUPEZ_INSTALLER%"',
    ):
        if artifact not in variant_build:
            errors.append(
                "variant release artifact is not Authenticode-signed when "
                f"DUPEZ_SIGN_CERT is configured: {artifact}"
            )

    errors.extend(_check_workflow_action_pins())
    errors.extend(_check_workflow_run_context_policy())

    errors.extend(verify_manifest())
    return errors


def _validate_supply_chain_metadata(dist: Path, version: str) -> list[str]:
    errors: list[str] = []
    lock_path = ROOT / "requirements-locked.txt"
    lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    packages = parse_lock(lock_path)
    expected_purls = sorted(
        purl_for(package.name, package.version)
        for package in packages
    )
    expected_markers = {
        purl_for(package.name, package.version): package.marker
        for package in packages
    }
    expected_target = release_target_metadata()

    def property_values(owner: object, name: str) -> list[str]:
        if not isinstance(owner, dict):
            return []
        properties = owner.get("properties")
        if not isinstance(properties, list):
            return []
        return [
            str(item.get("value") or "")
            for item in properties
            if isinstance(item, dict) and item.get("name") == name
        ]

    def load(name: str) -> dict | None:
        path = dist / name
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON in dist/{name}: {exc}")
            return None
        if not isinstance(payload, dict):
            errors.append(f"dist/{name} must contain a JSON object")
            return None
        return payload

    sbom = load("DupeZ.sbom.json")
    if sbom is not None:
        if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
            errors.append("dist/DupeZ.sbom.json is not CycloneDX 1.5")
        serial = str(sbom.get("serialNumber") or "")
        try:
            if not serial.startswith("urn:uuid:"):
                raise ValueError
            uuid.UUID(serial.removeprefix("urn:uuid:"))
        except ValueError:
            errors.append("dist/DupeZ.sbom.json has an invalid serialNumber UUID")
        components = sbom.get("components")
        if not isinstance(components, list):
            errors.append("dist/DupeZ.sbom.json contains no components")
        else:
            actual_purls = sorted(
                str(component.get("purl") or "")
                for component in components
                if isinstance(component, dict)
            )
            if actual_purls != expected_purls:
                errors.append(
                    "dist/DupeZ.sbom.json does not exactly cover the runtime lock"
                )
            components_by_purl = {
                str(component.get("purl") or ""): component
                for component in components
                if isinstance(component, dict)
            }
            for purl, expected_marker in expected_markers.items():
                marker_values = property_values(
                    components_by_purl.get(purl),
                    PEP508_MARKER_PROPERTY,
                )
                expected_values = [expected_marker] if expected_marker else []
                if marker_values != expected_values:
                    errors.append(
                        "dist/DupeZ.sbom.json dependency marker metadata does "
                        f"not match the release lock: {purl}"
                    )
        metadata = sbom.get("metadata") or {}
        target_values = property_values(metadata, RELEASE_TARGET_PROPERTY)
        if target_values != [release_target_property_value()]:
            errors.append(
                "dist/DupeZ.sbom.json has the wrong release-target metadata"
            )
        metadata_component = metadata.get("component") or {}
        metadata_version = str(metadata_component.get("version") or "")
        if metadata_version != version:
            errors.append(
                "dist/DupeZ.sbom.json product version does not match the release"
            )
        expected_product_purl = f"pkg:generic/dupez@{version}"
        if (
            metadata_component.get("type") != "application"
            or metadata_component.get("name") != "DupeZ"
            or metadata_component.get("purl") != expected_product_purl
            or metadata_component.get("bom-ref") != expected_product_purl
        ):
            errors.append(
                "dist/DupeZ.sbom.json has an invalid product identity"
            )

    review_path = dist / "DupeZ.vulnerability-review.json"
    review = load(review_path.name)
    review_sha256 = ""
    active_findings: list[dict] | None = None
    reviewed_finding_keys: list[tuple[str, str]] = []
    if review is not None:
        review_sha256 = hashlib.sha256(review_path.read_bytes()).hexdigest()
        if review.get("schema") != "dupez.python-vulnerability-review.v1":
            errors.append("unexpected vulnerability review schema")
        errors.extend(
            _vulnerability_review_timestamp_errors(
                review.get("generated_at_utc")
            )
        )
        if review.get("lock_sha256") != lock_sha256:
            errors.append("vulnerability review does not match the runtime lock")
        if review.get("release_target") != expected_target:
            errors.append("vulnerability review has the wrong release target")
        dependencies = review.get("dependencies")
        if not isinstance(dependencies, list):
            errors.append("vulnerability review dependencies must be a list")
        else:
            reviewed_purls = sorted(
                str(item.get("purl") or "")
                for item in dependencies
                if isinstance(item, dict)
            )
            if reviewed_purls != expected_purls:
                errors.append("vulnerability review does not cover the exact lock")
            for item in dependencies:
                if not isinstance(item, dict):
                    continue
                purl = str(item.get("purl") or "")
                expected_marker = expected_markers.get(purl)
                actual_marker = item.get("marker")
                if expected_marker:
                    if actual_marker != expected_marker:
                        errors.append(
                            "vulnerability review dependency marker metadata "
                            f"is incorrect: {purl}"
                        )
                elif "marker" in item:
                    errors.append(
                        "vulnerability review has unexpected dependency marker "
                        f"metadata: {purl}"
                    )
        if review.get("dependency_count") != len(expected_purls):
            errors.append("vulnerability review dependency count is incorrect")
        active = review.get("active_vulnerabilities")
        if not isinstance(active, list):
            errors.append("vulnerability review active findings must be a list")
        else:
            active_findings = active
            seen_findings: set[tuple[str, str]] = set()
            for finding in active:
                if not isinstance(finding, dict):
                    errors.append(
                        "vulnerability review contains an invalid active finding"
                    )
                    continue
                vulnerability_id = str(finding.get("id") or "").strip()
                dependency = str(finding.get("dependency") or "").strip()
                if not vulnerability_id or not dependency:
                    errors.append(
                        "vulnerability review active finding lacks an id or "
                        "dependency purl"
                    )
                    continue
                if dependency not in expected_purls:
                    errors.append(
                        "vulnerability review active finding dependency is absent "
                        "from the runtime lock"
                    )
                finding_key = (vulnerability_id, dependency)
                if finding_key in seen_findings:
                    errors.append(
                        "vulnerability review contains a duplicate active finding"
                    )
                else:
                    seen_findings.add(finding_key)
                    reviewed_finding_keys.append(finding_key)
            if review.get("active_vulnerability_count") != len(active):
                errors.append(
                    "vulnerability review active finding count is incorrect"
                )
            if active:
                errors.append(
                    "vulnerability review contains active findings; release is "
                    "blocked"
                )

    vex_path = dist / "DupeZ.vex.json"
    vex: dict | None = None
    if active_findings is None:
        if vex_path.exists():
            errors.append(
                "release OpenVEX requires a valid vulnerability review"
            )
    elif not active_findings:
        if vex_path.exists():
            errors.append(
                "zero-finding release must omit dist/DupeZ.vex.json; OpenVEX "
                "documents require vulnerability-specific statements"
            )
    elif not vex_path.is_file():
        errors.append(
            "active vulnerability review requires vulnerability-specific "
            "dist/DupeZ.vex.json"
        )
    else:
        vex = load(vex_path.name)

    if vex is not None:
        if vex.get("@context") != "https://openvex.dev/ns/v0.2.0":
            errors.append("dist/DupeZ.vex.json has an unexpected OpenVEX context")
        for field in ("@id", "author", "role", "timestamp", "tooling"):
            if not str(vex.get(field) or "").strip():
                errors.append(f"dist/DupeZ.vex.json has no {field}")
        if not isinstance(vex.get("version"), int) or vex["version"] < 1:
            errors.append("dist/DupeZ.vex.json has an invalid version")
        statements = vex.get("statements")
        if not isinstance(statements, list):
            errors.append("dist/DupeZ.vex.json statements must be a list")
            statements = []
        elif not statements:
            errors.append(
                "dist/DupeZ.vex.json must contain at least one statement"
            )
        vex_finding_keys: list[tuple[str, str]] = []
        expected_product = f"pkg:generic/dupez@{version}"
        for statement in statements:
            if not isinstance(statement, dict):
                errors.append("dist/DupeZ.vex.json contains an invalid statement")
                continue
            vulnerability = statement.get("vulnerability")
            if not isinstance(vulnerability, dict):
                errors.append("release VEX statement has no vulnerability object")
                vulnerability_id = ""
            else:
                vulnerability_id = str(
                    vulnerability.get("name") or ""
                ).strip()
                if not vulnerability_id:
                    errors.append("release VEX statement has no vulnerability id")
            products = statement.get("products")
            dependency = ""
            if not isinstance(products, list) or len(products) != 1:
                errors.append(
                    "release VEX statement must identify exactly one product"
                )
            elif not isinstance(products[0], dict):
                errors.append("release VEX statement contains an invalid product")
            else:
                product = products[0]
                if product.get("@id") != expected_product:
                    errors.append(
                        "release VEX statement product does not match the release"
                    )
                subcomponents = product.get("subcomponents")
                if (
                    not isinstance(subcomponents, list)
                    or len(subcomponents) != 1
                    or not isinstance(subcomponents[0], dict)
                ):
                    errors.append(
                        "release VEX statement must identify exactly one locked "
                        "dependency"
                    )
                else:
                    dependency = str(
                        subcomponents[0].get("@id") or ""
                    ).strip()
                    if dependency not in expected_purls:
                        errors.append(
                            "release VEX statement dependency is absent from the "
                            "runtime lock"
                        )
            status = statement.get("status")
            if status != "affected":
                errors.append(
                    "release VEX active-finding statement must have affected status"
                )
            if not str(statement.get("action_statement") or "").strip():
                errors.append("affected VEX statement has no action_statement")
            for field in ("timestamp", "action_statement_timestamp"):
                if not str(statement.get(field) or "").strip():
                    errors.append(f"release VEX statement has no {field}")
            if vulnerability_id and dependency:
                vex_finding_keys.append((vulnerability_id, dependency))
        if sorted(vex_finding_keys) != sorted(reviewed_finding_keys):
            errors.append(
                "release VEX statements do not exactly match the active review "
                "findings"
            )
        binding = vex.get("x-dupez-vulnerability-review")
        if not isinstance(binding, dict):
            errors.append("release VEX is not bound to a vulnerability review")
        else:
            if binding.get("schema") != "dupez.python-vulnerability-review.v1":
                errors.append("release VEX has an unexpected review binding schema")
            if binding.get("lock_sha256") != lock_sha256:
                errors.append("release VEX does not match the runtime lock")
            if binding.get("release_target") != expected_target:
                errors.append("release VEX has the wrong release target")
            if review_sha256 and binding.get("review_sha256") != review_sha256:
                errors.append("release VEX does not match the review artifact")
            if binding.get("dependency_count") != len(expected_purls):
                errors.append("release VEX dependency count is incorrect")
            if binding.get("active_vulnerability_count") != len(active_findings):
                errors.append("release VEX statement count does not match the review")
    return errors


def _check_source_archive(dist: Path, version: str) -> list[str]:
    """Require a safe Git-generated source archive with release controls."""

    errors: list[str] = []
    archive_path = dist / f"DupeZ-v{version}-source.zip"
    try:
        metadata = archive_path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_point(archive_path)
        ):
            return ["release source archive must be a regular, non-reparse file"]
        if metadata.st_size <= 0 or metadata.st_size > 1024 * 1024 * 1024:
            return ["release source archive has an invalid size"]
    except OSError as exc:
        return [f"release source archive is unavailable: {exc}"]

    prefix = f"DupeZ-v{version}/"
    required = {
        "LICENSE.txt",
        "README.md",
        "requirements.in",
        "requirements-locked.txt",
        "packaging/build_variants.bat",
        "packaging/installer.iss",
        "packaging/license-policy.json",
        "packaging/requirements-build-locked.txt",
        "packaging/third-party-components.json",
        "scripts/finalize_release.ps1",
        "scripts/license_payload.py",
        "docs/legal/DISTRIBUTION_BASIS_V5.8.0.md",
        "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
    }
    seen: dict[str, str] = {}
    present: set[str] = set()
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            try:
                comment = archive.comment.decode("ascii")
            except UnicodeDecodeError:
                comment = ""
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", comment):
                errors.append(
                    "release source archive omits its Git commit comment"
                )
            infos = archive.infolist()
            if not infos or len(infos) > 20000:
                errors.append("release source archive entry count is invalid")
            for info in infos:
                name = info.filename
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or any(ord(char) < 32 for char in name)
                ):
                    errors.append("release source archive contains an unsafe name")
                    continue
                relative = PurePosixPath(name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or relative.as_posix() != name
                    or not name.startswith(prefix)
                ):
                    errors.append(
                        f"release source archive contains an unsafe entry: {name}"
                    )
                    continue
                folded = name.casefold()
                previous = seen.get(folded)
                if previous is not None:
                    errors.append(
                        "release source archive contains duplicate/colliding "
                        f"entries: {previous}, {name}"
                    )
                else:
                    seen[folded] = name
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode):
                    errors.append(
                        f"release source archive contains a symlink: {name}"
                    )
                if info.flag_bits & 0x1:
                    errors.append(
                        f"release source archive contains an encrypted entry: {name}"
                    )
                if info.file_size < 0 or info.file_size > 256 * 1024 * 1024:
                    errors.append(
                        f"release source archive entry has an invalid size: {name}"
                    )
                total_uncompressed += info.file_size
                if total_uncompressed > 2 * 1024 * 1024 * 1024:
                    errors.append(
                        "release source archive expands beyond the size limit"
                    )
                    break
                if not info.is_dir():
                    present.add(name[len(prefix):])
            corrupt = archive.testzip()
            if corrupt is not None:
                errors.append(
                    f"release source archive has a corrupt entry: {corrupt}"
                )
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return errors + [f"release source archive is invalid: {exc}"]

    missing = sorted(required - present)
    if missing:
        errors.append(
            "release source archive omits required source files: "
            + ", ".join(missing)
        )
    if any(
        part.casefold() == ".git"
        for name in present
        for part in PurePosixPath(name).parts
    ):
        errors.append("release source archive must not contain Git metadata")
    return errors


def check_dist(version: str, *, allow_unsigned: bool = False) -> list[str]:
    errors: list[str] = []
    license_policy_errors, _ = _check_license_policy(distribution=True)
    errors.extend(license_policy_errors)
    required = (
        "DupeZ-GPU.exe",
        "DupeZ-Compat.exe",
        f"DupeZ_v{version}_Setup.exe",
        "DupeZ_Setup.exe",
        "DupeZ_Setup.exe.manifest.json",
        "DupeZ_Setup.exe.manifest.sig",
        "DupeZ.sbom.json",
        "DupeZ.vulnerability-review.json",
        "binary-provenance.json",
        "LICENSE.txt",
        "SOURCE_AND_RELINK.txt",
        "THIRD_PARTY_NOTICES.txt",
        "license-payload.json",
        f"DupeZ-v{version}-source.zip",
    )
    dist = ROOT / "dist"
    for name in required:
        path = dist / name
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"required release artifact missing/empty: dist/{name}")

    update_manifest, sidecar_errors = _verify_update_sidecars_and_manifest(
        dist,
        version,
        allow_unsigned=allow_unsigned,
    )
    errors.extend(sidecar_errors)
    expected_signer = (
        update_manifest.authenticode_signer_sha256
        if update_manifest is not None
        else None
    )
    expected_mode = (
        _UNSIGNED_RELEASE_MODE
        if allow_unsigned
        else _STANDARD_RELEASE_MODE
    )
    binary_expectations, provenance_errors = (
        _release_binary_archive_expectations(
            provenance_path=dist / "binary-provenance.json",
            expected_mode=expected_mode,
            expected_signer_certificate_sha256=expected_signer,
        )
    )
    errors.extend(provenance_errors)
    errors.extend(
        _check_frozen_dependency_policy(
            [
                dist / "DupeZ-GPU.exe",
                dist / "DupeZ-Compat.exe",
            ],
            release_binary_expectations=binary_expectations,
        )
    )
    errors.extend(
        _check_independent_child_signing_policy(
            allow_unsigned=allow_unsigned,
            expected_signer_certificate_sha256=expected_signer,
        )
    )

    errors.extend(_validate_supply_chain_metadata(dist, version))
    errors.extend(
        validate_license_payload(
            root=ROOT,
            dist=dist,
            expected_version=version,
        )
    )
    errors.extend(_check_source_archive(dist, version))
    errors.extend(_check_installer_alias(dist, version))
    signed_artifacts = [
        dist / name
        for name in (
            "DupeZ-GPU.exe",
            "DupeZ-Compat.exe",
            f"DupeZ_v{version}_Setup.exe",
            "DupeZ_Setup.exe",
        )
        if (dist / name).is_file()
    ]
    if signed_artifacts and not allow_unsigned:
        errors.extend(
            _check_outer_authenticode_policy(
                signed_artifacts,
                expected_signer_certificate_sha256=expected_signer,
            )
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--dist", action="store_true")
    parser.add_argument(
        "--allow-unsigned",
        action="store_true",
        help="allow an explicitly disclosed unsigned public-launch build",
    )
    parser.add_argument(
        "--frozen-artifact",
        action="append",
        type=Path,
        help="inspect a PyInstaller executable and exit",
    )
    parser.add_argument(
        "--license-distribution",
        action="store_true",
        help="require evidence for every owner-controlled license/IP decision",
    )
    args = parser.parse_args()

    if args.license_distribution:
        if args.dist or args.frozen_artifact:
            parser.error(
                "--license-distribution cannot be combined with --dist or "
                "--frozen-artifact"
            )
        errors, _ = _check_license_policy(distribution=True)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("License/IP distribution evidence gate passed.")
        return 0

    if args.frozen_artifact:
        errors = _check_frozen_dependency_policy(args.frozen_artifact)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("Frozen dependency preflight passed.")
        return 0

    errors = check_source(args.version)
    _, license_policy_warnings = _check_license_policy()
    for warning in license_policy_warnings:
        print(f"WARNING: {warning}")
    if args.dist:
        if not args.version:
            parser.error("--dist requires --version")
        errors.extend(check_dist(args.version, allow_unsigned=args.allow_unsigned))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
