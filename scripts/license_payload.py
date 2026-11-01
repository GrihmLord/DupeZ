#!/usr/bin/env python3
"""Build and verify the deterministic DupeZ distribution license payload.

The generator binds the exact release lock to the license files installed by
those wheels, adds the pinned native/build-runtime notices, and emits only
repository-relative or distribution-relative source labels. It deliberately
records upstream declarations without presenting them as a legal opinion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
# Support the documented recipient interpreter's isolated (-I) mode without
# depending on the caller's current directory or inherited PYTHONPATH.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.sbom import parse_lock, purl_for


INVENTORY_PATH = ROOT / "packaging" / "third-party-components.json"
LOCK_PATH = ROOT / "requirements-locked.txt"
PROJECT_LICENSE_PATH = ROOT / "LICENSE.txt"
SOURCE_INFO_PATH = ROOT / "docs" / "legal" / "SOURCE_AND_RELINK_V5.8.0.md"
DEFAULT_DIST = ROOT / "dist"

INVENTORY_SCHEMA = "dupez.third-party-components.v1"
PAYLOAD_SCHEMA = "dupez.license-payload.v1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_LICENSE_NAME_RE = re.compile(
    r"(?:^|[_-])(licen[cs]e|copying|notice|copyright)(?:[._-]|$)",
    re.IGNORECASE,
)
_LICENSE_SUFFIXES = frozenset({"", ".md", ".rst", ".txt", ".python"})


class LicensePayloadError(RuntimeError):
    """A fail-closed license-payload contract violation."""


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    return bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _read_regular(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LicensePayloadError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(path):
        raise LicensePayloadError(
            f"{label} must be a regular, non-reparse file"
        )
    if metadata.st_size <= 0 or metadata.st_size > MAX_SOURCE_BYTES:
        raise LicensePayloadError(f"{label} has an invalid size")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LicensePayloadError(f"cannot read {label}: {exc}") from exc


def _safe_repository_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
        or relative.as_posix() != value
    ):
        raise LicensePayloadError(f"unsafe repository path: {value!r}")
    return root.joinpath(*relative.parts)


def _normalize_text(data: bytes, *, label: str) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError as exc:  # pragma: no cover - cp1252 maps all
            raise LicensePayloadError(f"cannot decode license text: {label}") from exc
    if "\x00" in text:
        raise LicensePayloadError(f"license text contains NUL bytes: {label}")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise LicensePayloadError(f"license text is empty: {label}")
    return normalized + "\n"


def _load_inventory(root: Path, inventory_path: Path) -> dict[str, Any]:
    raw = _read_regular(inventory_path, label="third-party inventory")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicensePayloadError("third-party inventory is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "runtime_lock",
        "runtime_components",
        "additional_components",
    }:
        raise LicensePayloadError("third-party inventory has an invalid structure")
    if payload["schema"] != INVENTORY_SCHEMA:
        raise LicensePayloadError("third-party inventory has an invalid schema")
    if payload["runtime_lock"] != "requirements-locked.txt":
        raise LicensePayloadError("third-party inventory must bind the release lock")

    runtime = payload["runtime_components"]
    additional = payload["additional_components"]
    if not isinstance(runtime, list) or not runtime:
        raise LicensePayloadError("runtime component inventory is empty")
    if not isinstance(additional, list) or not additional:
        raise LicensePayloadError("additional component inventory is empty")

    runtime_keys = {
        "name",
        "version",
        "declared_license",
        "metadata_license",
        "homepage",
        "fallback_files",
        "supplemental_files",
    }
    seen_runtime: set[str] = set()
    for index, component in enumerate(runtime):
        if not isinstance(component, dict) or set(component) != runtime_keys:
            raise LicensePayloadError(
                f"runtime component {index} has an invalid structure"
            )
        name = component["name"]
        version = component["version"]
        canonical = _canonical_name(name) if isinstance(name, str) else ""
        if not canonical or canonical in seen_runtime:
            raise LicensePayloadError(f"runtime component {index} has an invalid name")
        seen_runtime.add(canonical)
        if not isinstance(version, str) or not version:
            raise LicensePayloadError(f"runtime component {name} has no version")
        if component["metadata_license"] is not None and not isinstance(
            component["metadata_license"], str
        ):
            raise LicensePayloadError(
                f"runtime component {name} has an invalid metadata_license"
            )
        _validate_common_component_fields(component, f"runtime component {name}")
        for field in ("fallback_files", "supplemental_files"):
            _validate_repository_file_list(root, component[field], f"{name} {field}")

    additional_keys = {
        "id",
        "name",
        "version",
        "declared_license",
        "homepage",
        "source",
        "supplemental_files",
    }
    seen_ids: set[str] = set()
    for index, component in enumerate(additional):
        if not isinstance(component, dict) or set(component) != additional_keys:
            raise LicensePayloadError(
                f"additional component {index} has an invalid structure"
            )
        component_id = component["id"]
        if (
            not isinstance(component_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", component_id)
            or component_id in seen_ids
        ):
            raise LicensePayloadError(
                f"additional component {index} has an invalid id"
            )
        seen_ids.add(component_id)
        _validate_common_component_fields(component, f"component {component_id}")
        _validate_repository_file_list(
            root,
            component["supplemental_files"],
            f"{component_id} supplemental_files",
        )
        _validate_additional_source(root, component_id, component["source"])
    return payload


def _validate_common_component_fields(component: dict[str, Any], label: str) -> None:
    for field in ("name", "version", "declared_license", "homepage"):
        value = component.get(field)
        if not isinstance(value, str) or not value.strip():
            raise LicensePayloadError(f"{label} has an invalid {field}")
    homepage = component["homepage"]
    if not homepage.startswith("https://") or any(ch.isspace() for ch in homepage):
        raise LicensePayloadError(f"{label} has an unsafe homepage")


def _validate_repository_file_list(root: Path, value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise LicensePayloadError(f"{label} must be a path list")
    if len(value) != len(set(value)):
        raise LicensePayloadError(f"{label} contains duplicate paths")
    for relative in value:
        _read_regular(
            _safe_repository_path(root, relative),
            label=f"repository license file {relative}",
        )


def _validate_additional_source(root: Path, component_id: str, source: Any) -> None:
    if not isinstance(source, dict) or "type" not in source:
        raise LicensePayloadError(f"component {component_id} has an invalid source")
    source_type = source["type"]
    if source_type == "installed-distribution":
        if set(source) != {"type", "distribution"} or not isinstance(
            source["distribution"], str
        ):
            raise LicensePayloadError(
                f"component {component_id} has an invalid distribution source"
            )
    elif source_type == "repository-files":
        if set(source) != {"type", "paths"}:
            raise LicensePayloadError(
                f"component {component_id} has an invalid repository source"
            )
        _validate_repository_file_list(
            root, source["paths"], f"{component_id} source paths"
        )
    elif source_type == "python-runtime-license":
        if set(source) != {"type", "filename"} or source["filename"] != "LICENSE.txt":
            raise LicensePayloadError(
                f"component {component_id} has an invalid Python source"
            )
    else:
        raise LicensePayloadError(
            f"component {component_id} uses an unsupported source type"
        )


def _is_license_candidate(relative: str, declared: set[str]) -> bool:
    path = PurePosixPath(relative)
    folded = relative.casefold()
    is_declared = False
    for value in declared:
        candidate = value.replace("\\", "/").lstrip("/").casefold()
        if folded == candidate or folded.endswith("/" + candidate):
            is_declared = True
            break
    name = path.name
    suffix = path.suffix.casefold()
    is_named = suffix in _LICENSE_SUFFIXES and bool(
        _LICENSE_NAME_RE.search(name)
    )
    if not is_declared and not is_named:
        return False
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise LicensePayloadError(
            f"installed distribution contains an unsafe license path: {relative!r}"
        )
    return True


def _distribution_documents(
    distribution_name: str,
    expected_version: str,
    *,
    resolver: Callable[[str], Any],
    expected_metadata_license: str | None = None,
    check_metadata_license: bool = False,
) -> list[tuple[str, bytes]]:
    try:
        installed = resolver(distribution_name)
    except PackageNotFoundError as exc:
        raise LicensePayloadError(
            f"required distribution is not installed: {distribution_name}"
        ) from exc
    actual_version = str(installed.version)
    if actual_version != expected_version:
        raise LicensePayloadError(
            f"installed {distribution_name} version {actual_version} does not "
            f"match inventory version {expected_version}"
        )
    metadata_name = installed.metadata.get("Name")
    if _canonical_name(str(metadata_name or "")) != _canonical_name(distribution_name):
        raise LicensePayloadError(
            f"installed distribution identity mismatch for {distribution_name}"
        )
    if check_metadata_license:
        actual_metadata_license = installed.metadata.get(
            "License-Expression"
        ) or installed.metadata.get("License")
        if actual_metadata_license != expected_metadata_license:
            raise LicensePayloadError(
                f"installed {distribution_name} license metadata "
                f"{actual_metadata_license!r} does not match the pinned "
                f"declaration {expected_metadata_license!r}"
            )
    declared = {
        str(value).replace("\\", "/")
        for value in (installed.metadata.get_all("License-File") or [])
    }
    candidates: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for package_path in sorted(installed.files or (), key=lambda item: str(item).casefold()):
        relative = str(package_path).replace("\\", "/")
        if not _is_license_candidate(relative, declared):
            continue
        folded = relative.casefold()
        if folded in seen:
            raise LicensePayloadError(
                f"duplicate license path in {distribution_name}: {relative}"
            )
        seen.add(folded)
        resolved = Path(installed.locate_file(package_path))
        data = _read_regular(
            resolved,
            label=f"installed license file {distribution_name}:{relative}",
        )
        candidates.append((f"installed:{_canonical_name(distribution_name)}:{relative}", data))
    return candidates


def _repository_documents(
    root: Path,
    paths: Iterable[str],
) -> list[tuple[str, bytes]]:
    return [
        (
            f"repository:{relative}",
            _read_regular(
                _safe_repository_path(root, relative),
                label=f"repository license file {relative}",
            ),
        )
        for relative in paths
    ]


def _append_document_records(
    records: list[dict[str, Any]],
    *,
    component_id: str,
    component: dict[str, Any],
    documents: Iterable[tuple[str, bytes]],
) -> None:
    for source, data in documents:
        normalized = _normalize_text(data, label=source)
        records.append({
            "component_id": component_id,
            "component_name": component["name"],
            "component_version": component["version"],
            "declared_license": component["declared_license"],
            "homepage": component["homepage"],
            "source": source,
            "source_sha256": _sha256(data),
            "normalized_text_sha256": _sha256(normalized.encode("utf-8")),
            "source_size": len(data),
            "text": normalized,
        })


def _build_notice_text(records: list[dict[str, Any]]) -> str:
    lines = [
        "DupeZ Third-Party Notices",
        "==========================",
        "",
        "This deterministic inventory reproduces notices and license texts from",
        "the exact release environment and pinned repository records. Declared",
        "license identifiers record upstream metadata; they are not legal advice.",
        "",
    ]
    for record in records:
        lines.extend([
            "=" * 78,
            f"Component: {record['component_name']} {record['component_version']}",
            f"Component ID: {record['component_id']}",
            f"Declared license: {record['declared_license']}",
            f"Homepage: {record['homepage']}",
            f"Source record: {record['source']}",
            f"Source SHA-256: {record['source_sha256']}",
            "=" * 78,
            "",
            record["text"].rstrip("\n"),
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_license_payload(
    *,
    root: Path = ROOT,
    dist: Path = DEFAULT_DIST,
    product_version: str,
    inventory_path: Path | None = None,
    lock_path: Path | None = None,
    project_license_path: Path | None = None,
    source_info_path: Path | None = None,
    distribution_resolver: Callable[[str], Any] = distribution,
    python_license_path: Path | None = None,
) -> dict[str, Any]:
    """Generate the legal payload and return its JSON document."""

    if not _VERSION_RE.fullmatch(product_version):
        raise LicensePayloadError("product version must be semantic x.y.z")
    root = root.resolve()
    inventory_path = inventory_path or root / "packaging" / "third-party-components.json"
    lock_path = lock_path or root / "requirements-locked.txt"
    project_license_path = project_license_path or root / "LICENSE.txt"
    source_info_path = source_info_path or root / "docs" / "legal" / "SOURCE_AND_RELINK_V5.8.0.md"
    inventory = _load_inventory(root, inventory_path)
    lock_bytes = _read_regular(lock_path, label="runtime lock")
    locked = parse_lock(lock_path)
    locked_versions = {
        _canonical_name(package.name): package.version for package in locked
    }
    inventory_versions = {
        _canonical_name(component["name"]): component["version"]
        for component in inventory["runtime_components"]
    }
    if locked_versions != inventory_versions:
        missing = sorted(locked_versions.keys() - inventory_versions.keys())
        extra = sorted(inventory_versions.keys() - locked_versions.keys())
        drift = sorted(
            name
            for name in locked_versions.keys() & inventory_versions.keys()
            if locked_versions[name] != inventory_versions[name]
        )
        raise LicensePayloadError(
            "third-party runtime inventory does not exactly match the release "
            f"lock (missing={missing}, extra={extra}, version_drift={drift})"
        )

    project_license = _read_regular(project_license_path, label="project license")
    source_info = _read_regular(source_info_path, label="source/relink information")
    inventory_bytes = _read_regular(inventory_path, label="third-party inventory")
    records: list[dict[str, Any]] = []
    runtime_payload: list[dict[str, str]] = []
    for component in inventory["runtime_components"]:
        component_id = f"pypi:{_canonical_name(component['name'])}"
        documents = _distribution_documents(
            component["name"],
            component["version"],
            resolver=distribution_resolver,
            expected_metadata_license=component["metadata_license"],
            check_metadata_license=True,
        )
        if not documents:
            documents = _repository_documents(root, component["fallback_files"])
        if not documents:
            raise LicensePayloadError(
                f"no license document found for runtime component {component['name']}"
            )
        documents.extend(_repository_documents(root, component["supplemental_files"]))
        _append_document_records(
            records,
            component_id=component_id,
            component=component,
            documents=documents,
        )
        runtime_payload.append({
            "name": _canonical_name(component["name"]),
            "version": component["version"],
            "purl": purl_for(_canonical_name(component["name"]), component["version"]),
            "declared_license": component["declared_license"],
            "metadata_license": component["metadata_license"],
        })

    additional_payload: list[dict[str, str]] = []
    if python_license_path is None:
        python_license_path = Path(sys.base_prefix) / "LICENSE.txt"
    for component in inventory["additional_components"]:
        source = component["source"]
        if source["type"] == "installed-distribution":
            documents = _distribution_documents(
                source["distribution"],
                component["version"],
                resolver=distribution_resolver,
            )
        elif source["type"] == "repository-files":
            documents = _repository_documents(root, source["paths"])
        else:
            python_bytes = _read_regular(
                python_license_path,
                label="CPython runtime license",
            )
            documents = [("python-runtime:LICENSE.txt", python_bytes)]
        documents.extend(_repository_documents(root, component["supplemental_files"]))
        if not documents:
            raise LicensePayloadError(
                f"no license document found for component {component['id']}"
            )
        _append_document_records(
            records,
            component_id=component["id"],
            component=component,
            documents=documents,
        )
        additional_payload.append({
            "id": component["id"],
            "name": component["name"],
            "version": component["version"],
            "declared_license": component["declared_license"],
        })

    records.sort(key=lambda record: (
        record["component_id"],
        record["source"].casefold(),
        record["source"],
    ))
    if len({(record["component_id"], record["source"]) for record in records}) != len(records):
        raise LicensePayloadError("license payload contains duplicate source records")
    notice_bytes = _build_notice_text(records).encode("utf-8")
    source_output = _normalize_text(source_info, label="source/relink information").encode("utf-8")
    project_output = _normalize_text(project_license, label="project license").encode("utf-8")

    output_documents = {
        "LICENSE.txt": project_output,
        "SOURCE_AND_RELINK.txt": source_output,
        "THIRD_PARTY_NOTICES.txt": notice_bytes,
    }
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "product": {"name": "DupeZ", "version": product_version},
        "disclaimer": (
            "Upstream license declarations and reproduced texts; not a legal opinion."
        ),
        "inputs": {
            "inventory_manifest": {
                "path": "packaging/third-party-components.json",
                "sha256": _sha256(inventory_bytes),
            },
            "runtime_lock": {
                "path": "requirements-locked.txt",
                "sha256": _sha256(lock_bytes),
            },
            "project_license": {
                "path": "LICENSE.txt",
                "sha256": _sha256(project_license),
            },
            "source_and_relink": {
                "path": "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
                "sha256": _sha256(source_info),
            },
        },
        "runtime_components": sorted(runtime_payload, key=lambda item: item["name"]),
        "additional_components": sorted(additional_payload, key=lambda item: item["id"]),
        "documents": [
            {key: value for key, value in record.items() if key != "text"}
            for record in records
        ],
        "outputs": {
            name: {"sha256": _sha256(data), "size": len(data)}
            for name, data in sorted(output_documents.items())
        },
    }
    payload_bytes = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    for name, data in output_documents.items():
        _atomic_write(dist / name, data)
    _atomic_write(dist / "license-payload.json", payload_bytes)
    return payload


def validate_license_payload(
    *,
    root: Path = ROOT,
    dist: Path = DEFAULT_DIST,
    expected_version: str,
) -> list[str]:
    """Validate generated files using only repository inputs and payload hashes."""

    errors: list[str] = []
    payload_path = dist / "license-payload.json"
    try:
        payload_bytes = _read_regular(payload_path, label="license payload manifest")
        payload = json.loads(payload_bytes)
    except (LicensePayloadError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"license payload manifest is invalid: {exc}"]
    expected_root_keys = {
        "schema",
        "product",
        "disclaimer",
        "inputs",
        "runtime_components",
        "additional_components",
        "documents",
        "outputs",
    }
    if not isinstance(payload, dict) or set(payload) != expected_root_keys:
        return ["license payload manifest has an invalid structure"]
    if payload.get("schema") != PAYLOAD_SCHEMA:
        errors.append("license payload manifest has an invalid schema")
    if payload.get("product") != {"name": "DupeZ", "version": expected_version}:
        errors.append("license payload product/version binding is invalid")

    inputs = payload.get("inputs")
    expected_inputs = {
        "inventory_manifest": "packaging/third-party-components.json",
        "runtime_lock": "requirements-locked.txt",
        "project_license": "LICENSE.txt",
        "source_and_relink": "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
    }
    if not isinstance(inputs, dict) or set(inputs) != set(expected_inputs):
        errors.append("license payload input binding is invalid")
    else:
        for key, relative in expected_inputs.items():
            record = inputs[key]
            if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
                errors.append(f"license payload {key} input has an invalid structure")
                continue
            if record.get("path") != relative or not _HASH_RE.fullmatch(
                str(record.get("sha256", ""))
            ):
                errors.append(f"license payload {key} input binding is invalid")
                continue
            try:
                actual = _sha256(
                    _read_regular(
                        _safe_repository_path(root, relative),
                        label=f"license payload input {relative}",
                    )
                )
            except LicensePayloadError as exc:
                errors.append(str(exc))
                continue
            if actual != record["sha256"]:
                errors.append(f"license payload {key} input hash does not match")

    try:
        locked = parse_lock(root / "requirements-locked.txt")
        expected_runtime = sorted(
            (
                _canonical_name(package.name),
                package.version,
                purl_for(_canonical_name(package.name), package.version),
            )
            for package in locked
        )
    except Exception as exc:
        errors.append(f"cannot parse runtime lock for license payload: {exc}")
        expected_runtime = []
    runtime = payload.get("runtime_components")
    if not isinstance(runtime, list):
        errors.append("license payload runtime component list is invalid")
        runtime = []
    actual_runtime: list[tuple[str, str, str]] = []
    for component in runtime:
        if not isinstance(component, dict) or set(component) != {
            "name",
            "version",
            "purl",
            "declared_license",
            "metadata_license",
        }:
            errors.append("license payload runtime component has an invalid structure")
            continue
        actual_runtime.append((component["name"], component["version"], component["purl"]))
        if not isinstance(component["declared_license"], str) or not component["declared_license"]:
            errors.append("license payload runtime component has no license declaration")
        if component["metadata_license"] is not None and not isinstance(
            component["metadata_license"], str
        ):
            errors.append("license payload runtime component has invalid license metadata")
    if sorted(actual_runtime) != expected_runtime:
        errors.append("license payload runtime inventory does not match the release lock")

    outputs = payload.get("outputs")
    expected_outputs = {"LICENSE.txt", "SOURCE_AND_RELINK.txt", "THIRD_PARTY_NOTICES.txt"}
    if not isinstance(outputs, dict) or set(outputs) != expected_outputs:
        errors.append("license payload output inventory is invalid")
    else:
        for name in sorted(expected_outputs):
            record = outputs[name]
            if not isinstance(record, dict) or set(record) != {"sha256", "size"}:
                errors.append(f"license payload output {name} has an invalid record")
                continue
            try:
                data = _read_regular(dist / name, label=f"license payload output {name}")
            except LicensePayloadError as exc:
                errors.append(str(exc))
                continue
            if record.get("sha256") != _sha256(data) or record.get("size") != len(data):
                errors.append(f"license payload output {name} does not match its record")

    documents = payload.get("documents")
    component_ids = {f"pypi:{name}" for name, _, _ in expected_runtime}
    additional = payload.get("additional_components")
    if not isinstance(additional, list):
        errors.append("license payload additional component list is invalid")
        additional = []
    for component in additional:
        if not isinstance(component, dict) or set(component) != {
            "id",
            "name",
            "version",
            "declared_license",
        }:
            errors.append("license payload additional component has an invalid structure")
            continue
        component_ids.add(str(component["id"]))
    seen_documents: set[tuple[str, str]] = set()
    represented: set[str] = set()
    if not isinstance(documents, list) or not documents:
        errors.append("license payload has no document records")
        documents = []
    document_keys = {
        "component_id",
        "component_name",
        "component_version",
        "declared_license",
        "homepage",
        "source",
        "source_sha256",
        "normalized_text_sha256",
        "source_size",
    }
    notices_text = ""
    try:
        notices_text = (dist / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    for record in documents:
        if not isinstance(record, dict) or set(record) != document_keys:
            errors.append("license payload document has an invalid structure")
            continue
        component_id = str(record["component_id"])
        source = str(record["source"])
        identity = (component_id, source)
        if component_id not in component_ids:
            errors.append("license payload document references an unknown component")
        if identity in seen_documents:
            errors.append("license payload document inventory contains a duplicate")
        seen_documents.add(identity)
        represented.add(component_id)
        if not source.startswith(("installed:", "repository:", "python-runtime:")):
            errors.append("license payload document has an unsafe source label")
        for field in ("source_sha256", "normalized_text_sha256"):
            if not _HASH_RE.fullmatch(str(record.get(field, ""))):
                errors.append(f"license payload document has an invalid {field}")
        if str(record.get("source_sha256", "")) not in notices_text:
            errors.append("third-party notices omit a recorded source hash")
    missing_components = sorted(component_ids - represented)
    if missing_components:
        errors.append(
            "license payload has no document for components: "
            + ", ".join(missing_components)
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            errors = validate_license_payload(
                root=ROOT,
                dist=args.dist,
                expected_version=args.version,
            )
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print("License payload verification: PASS")
            return 0
        payload = build_license_payload(
            root=ROOT,
            dist=args.dist,
            product_version=args.version,
        )
    except (LicensePayloadError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote deterministic license payload: {args.dist}")
    print(f"  runtime components: {len(payload['runtime_components'])}")
    print(f"  notice documents:   {len(payload['documents'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
