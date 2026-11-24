#!/usr/bin/env python3
"""Collect hash-pinned upstream source inputs without running or extracting them.

This is a source-input inventory, not a license approval or proof of complete
corresponding source. A version-matching upstream archive does not establish
which patches/build configuration produced a distributed third-party wheel.
Unresolved delivery mappings remain explicit in both plans and bundle receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import struct
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "dupez.source-inputs.v1"
RECEIPT_SCHEMA = "dupez.source-input-receipt.v1"
MAX_MANIFEST_BYTES = 1024 * 1024
DEFAULT_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 8 * 1024 * 1024 * 1024
MAX_MEMBERS = 1_000_000
MAX_METADATA_HEADER_BYTES = 64 * 1024
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_ZIP_DIRECTORY_BYTES = 64 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?\Z", re.I)
# SourceForge names this exact published IUP source directory with spaces.
# Admit only these reviewed full URLs; never decode arbitrary escapes.
_IUP_SOURCE_PATH = "/project/iup/3.30/Docs%20and%20Sources/iup-3.30_Sources.zip"
_ENCODED_SOURCE_URLS = frozenset({
    "https://downloads.sourceforge.net" + _IUP_SOURCE_PATH,
    "https://sourceforge.net/projects/iup/files/3.30/Docs%20and%20Sources/iup-3.30_Sources.zip/download",
})
_DOWNLOAD_ROUTES = {
    "files.pythonhosted.org": re.compile(r"/packages/[a-zA-Z0-9/_.-]+\Z"),
    "www.python.org": re.compile(r"/ftp/python/[0-9.]+/Python-[0-9.]+\.tar\.(?:gz|xz)\Z"),
    "download.qt.io": re.compile(
        r"/official_releases/qt/[0-9.]+/[0-9.]+/(?:single|submodules)/"
        r"[a-z0-9.-]+\.(?:tar\.xz|zip)\Z"
    ),
    "codeload.github.com": re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/zip/[0-9a-f]{40}\Z"),
    # Stable official source locator. SourceForge currently redirects to a
    # signed mirror URL, so collection requires a separately reviewed cache
    # acquisition. Redirects and expiring query tokens remain prohibited here.
    "downloads.sourceforge.net": re.compile(re.escape(_IUP_SOURCE_PATH) + r"\Z"),
    # Direct HTTPS mirror advertised by Qt's official .mirrorlist, 2026-10-24.
    # Official digests are pinned independently; redirects remain forbidden.
    "qt.mirror.constant.com": re.compile(
        r"/archive/qt/[0-9.]+/[0-9.]+/(?:single|submodules)/"
        r"[a-z0-9.-]+\.(?:tar\.xz|zip)\Z"
    ),
}


class SourceInputError(RuntimeError):
    """An unsafe or unverified source input must not be distributed."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _is_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def checked_path(path: Path, *, directory: bool = False) -> Path:
    """Reject junctions/symlinks in every existing path component before resolve."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            continue
        if _is_reparse(metadata):
            raise SourceInputError(f"reparse path is not allowed: {part}")
    if path.exists():
        metadata = path.lstat()
        valid_type = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
        if not valid_type or (not directory and metadata.st_nlink != 1):
            raise SourceInputError(f"expected ordinary {'directory' if directory else 'file'}: {path}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    path = checked_path(path)
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_MANIFEST_BYTES + 1)
        if not data or len(data) > MAX_MANIFEST_BYTES:
            raise SourceInputError("JSON input has an invalid size")
        result = json.loads(data, object_pairs_hook=_no_duplicates)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceInputError(f"cannot read JSON input: {path}") from exc
    if not isinstance(result, dict):
        raise SourceInputError("JSON input must be an object")
    return result


def _https_url(value: Any) -> urllib.parse.SplitResult:
    if not isinstance(value, str) or not value or any(
        ord(char) < 33 or ord(char) > 126 for char in value
    ) or "\\" in value or ("%" in value and value not in _ENCODED_SOURCE_URLS):
        raise SourceInputError("URL must be plain HTTPS without escapes or controls")
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.query or parsed.fragment
            or parsed.hostname != parsed.netloc or ".." in parsed.path.split("/")
        ):
            raise ValueError("noncanonical HTTPS URL")
    except ValueError as exc:
        raise SourceInputError("URL must be canonical HTTPS without credentials or ports") from exc
    return parsed


def validate_download_url(url: str) -> None:
    parsed = _https_url(url)
    route = _DOWNLOAD_ROUTES.get(parsed.hostname or "")
    if route is None or not route.fullmatch(parsed.path):
        raise SourceInputError("download URL is not an approved immutable source route")


def _text_list(value: Any, label: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ) or len(set(value)) != len(value):
        raise SourceInputError(f"invalid {label}")


def load_manifest(path: Path, inventory_path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if set(payload) != {"schema", "reviewed_on", "scope", "delivery_gaps", "components"}:
        raise SourceInputError("invalid source manifest structure")
    if payload["schema"] != SCHEMA or payload["scope"] != "third-party-source-inputs":
        raise SourceInputError("invalid source manifest schema/scope")
    if not isinstance(payload["reviewed_on"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["reviewed_on"]):
        raise SourceInputError("invalid source manifest review date")
    _text_list(payload["delivery_gaps"], "delivery gaps")
    inventory = _read_json(inventory_path)
    expected = {item["name"]: item["version"] for item in inventory["runtime_components"]}
    expected.update({item["id"]: item["version"] for item in inventory["additional_components"]})
    components = payload["components"]
    if not isinstance(components, list) or not components:
        raise SourceInputError("source components must be a nonempty list")
    seen: dict[str, str] = {}
    filenames: set[str] = set()
    for item in components:
        if not isinstance(item, dict) or set(item) != {
            "id", "version", "source_status", "evidence_urls", "gaps", "artifacts"
        }:
            raise SourceInputError("invalid source component structure")
        name, version = item["id"], item["version"]
        if not isinstance(name, str) or not _ID.fullmatch(name) or name in seen:
            raise SourceInputError("invalid or duplicate source component ID")
        if not isinstance(version, str) or expected.get(name) != version:
            raise SourceInputError(f"source version differs from inventory: {name}")
        seen[name] = version
        _text_list(item["evidence_urls"], f"{name} evidence URLs", nonempty=True)
        for url in item["evidence_urls"]:
            _https_url(url)
        _text_list(item["gaps"], f"{name} gaps")
        artifacts = item["artifacts"]
        if not isinstance(artifacts, list):
            raise SourceInputError(f"invalid artifacts: {name}")
        if item["source_status"] not in {"upstream-source-pinned", "unresolved"}:
            raise SourceInputError(f"invalid source status: {name}")
        if bool(artifacts) != (item["source_status"] == "upstream-source-pinned"):
            raise SourceInputError(f"source status disagrees with artifacts: {name}")
        if not artifacts and not item["gaps"]:
            raise SourceInputError(f"unresolved source requires an explanation: {name}")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {"filename", "url", "size", "sha256"}:
                raise SourceInputError(f"invalid artifact structure: {name}")
            filename = artifact["filename"]
            if (
                not isinstance(filename, str) or not _FILENAME.fullmatch(filename)
                or filename.endswith((".", " ")) or _RESERVED.fullmatch(filename)
                or filename.casefold() in filenames
                or not filename.endswith((".zip", ".tar.gz", ".tar.xz"))
            ):
                raise SourceInputError(f"unsafe or duplicate source filename: {name}")
            filenames.add(filename.casefold())
            if type(artifact["size"]) is not int or not 0 < artifact["size"] <= MAX_ARTIFACT_BYTES:
                raise SourceInputError(f"invalid artifact size: {name}")
            if not isinstance(artifact["sha256"], str) or not _HASH.fullmatch(artifact["sha256"]):
                raise SourceInputError(f"invalid artifact SHA-256: {name}")
            validate_download_url(artifact["url"])
    if seen != expected:
        raise SourceInputError("source manifest must cover every inventory component exactly")
    return payload


def delivery_gaps(manifest: dict[str, Any]) -> list[str]:
    return [*manifest["delivery_gaps"], *(
        f"{item['id']}: {gap}" for item in manifest["components"] for gap in item["gaps"]
    )]


def _member_path(name: str) -> str:
    """Reject names that could escape or alias on either Windows or POSIX."""
    name = name.rstrip("/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or path.as_posix() != name or any(
        part in {".", ".."} or part.endswith((".", " ")) or _RESERVED.fullmatch(part)
        or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
        for part in path.parts
    ):
        raise SourceInputError("archive contains an unsafe member path")
    return name


class _BoundedTarInfo(tarfile.TarInfo):
    """Guard extension records before tarfile reads/parses their payloads.

    _proc_member is tarfile's documented subclass dispatch point. Counting only
    yielded TarInfo objects misses PAX/GNU headers and their recursive parsing.
    """

    def _proc_member(self, archive: Any) -> tarfile.TarInfo:
        metadata_types = {
            tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
            tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK,
        }
        is_metadata = self.type in metadata_types
        ceiling = min(MAX_METADATA_HEADER_BYTES, MAX_MEMBER_BYTES) if is_metadata else MAX_MEMBER_BYTES
        if not 0 <= self.size <= ceiling:
            raise SourceInputError("TAR parser input exceeds member/metadata size limit")
        total = getattr(archive, "_source_parser_bytes", 0) + self.size
        metadata = getattr(archive, "_source_metadata_bytes", 0) + (self.size if is_metadata else 0)
        count = getattr(archive, "_source_header_count", 0) + 1
        depth = getattr(archive, "_source_header_depth", 0) + 1
        if total > MAX_EXPANDED_BYTES or metadata > MAX_METADATA_BYTES or count > MAX_MEMBERS * 2 or depth > 32:
            raise SourceInputError("TAR parser input exceeds aggregate or recursion limits")
        archive._source_parser_bytes = total
        archive._source_metadata_bytes = metadata
        archive._source_header_count = count
        archive._source_header_depth = depth
        try:
            if self.type == tarfile.GNUTYPE_SPARSE:
                raise SourceInputError("sparse TAR records are not supported")
            return super()._proc_member(archive)
        finally:
            archive._source_header_depth -= 1

    def _proc_gnusparse_00(self, *args: Any) -> None:
        raise SourceInputError("sparse PAX records are not supported")

    _proc_gnusparse_01 = _proc_gnusparse_00
    _proc_gnusparse_10 = _proc_gnusparse_00


def _check_zip_directory(path: Path) -> None:
    """Bound central-directory allocation before ZipFile reads that directory."""
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - (65535 + 22)))
        tail = handle.read(65535 + 22)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise SourceInputError("ZIP end-of-directory record is missing")
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, comment_size = struct.unpack_from("<4s4H2LH", tail, position)
    if (
        disk or directory_disk or disk_entries != entries or entries == 0xFFFF
        or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF
        or directory_size > MAX_ZIP_DIRECTORY_BYTES or entries > MAX_MEMBERS
        or directory_offset + directory_size > size
        or len(tail) - position != 22 + comment_size
    ):
        raise SourceInputError("ZIP central directory exceeds bounds or uses unsupported disk/ZIP64 metadata")


def inspect_archive(path: Path, filename: str) -> dict[str, int]:
    """Inspect bounded metadata only. Never call extract/extractall or execute."""
    names: set[str] = set()
    links: dict[str, str] = {}
    count, expanded = 0, 0

    def accept(name: str, size: int, ordinary: bool) -> None:
        nonlocal count, expanded
        canonical = _member_path(name)
        if canonical in names or not ordinary or not 0 <= size <= MAX_MEMBER_BYTES:
            raise SourceInputError(f"archive contains duplicate, special, linked, or oversized member: {canonical}")
        names.add(canonical)
        count += 1
        expanded += size
        if count > MAX_MEMBERS or expanded > MAX_EXPANDED_BYTES:
            raise SourceInputError(f"archive exceeds inspection limits: {count} entries, {expanded} bytes")

    def accept_link(name: str, target: str, *, hard: bool = False) -> None:
        canonical = _member_path(name)
        if not target or target.startswith("/") or "\\" in target or ":" in target:
            raise SourceInputError("archive contains an absolute or drive-qualified link")
        resolved = posixpath.normpath(target if hard else posixpath.join(posixpath.dirname(canonical), target))
        resolved = _member_path(resolved)
        if resolved.split("/")[0] != canonical.split("/")[0]:
            raise SourceInputError("archive link leaves its source root")
        accept(name, 0, True)
        links[canonical] = resolved

    try:
        if filename.endswith(".zip"):
            _check_zip_directory(path)
            with zipfile.ZipFile(path) as archive:
                if len(archive.infolist()) > MAX_MEMBERS:
                    raise SourceInputError("archive has too many entries")
                for member in archive.infolist():
                    # ZipInfo normalizes Windows backslashes and truncates NUL
                    # names. Validate the original central-directory spelling.
                    if member.orig_filename != member.filename:
                        raise SourceInputError("archive member path was normalized")
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind == stat.S_IFLNK and member.file_size <= 4096 and not member.flag_bits & 1:
                        accept_link(member.filename, archive.read(member).decode("utf-8"))
                    else:
                        accept(member.filename, member.file_size, not member.flag_bits & 1 and kind in {0, stat.S_IFREG, stat.S_IFDIR})
        elif filename.endswith((".tar.gz", ".tar.xz")):
            with tarfile.open(path, mode="r|*", stream=True, tarinfo=_BoundedTarInfo) as archive:
                for member in archive:
                    if member.issym() or member.islnk():
                        accept_link(member.name, member.linkname, hard=member.islnk())
                    else:
                        accept(member.name, member.size, member.isfile() or member.isdir())
        else:
            raise SourceInputError("unsupported source archive format")
    except (OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise SourceInputError("source archive is malformed") from exc
    if not count:
        raise SourceInputError("source archive is empty")
    # A lexically internal link can escape once a link in an ancestor path is
    # followed by an extractor (for example a -> '.', a/b -> '../outside').
    # We never extract; reject those ambiguous layouts rather than pretending
    # simple lexical normalization proves their eventual filesystem target.
    for name in (*names, *links.values()):
        if any(parent.as_posix() in links for parent in PurePosixPath(name).parents):
            raise SourceInputError("archive member or link target has a linked ancestor")
    for name, target in links.items():
        visited = {name}
        while target in links:
            if target in visited or len(visited) > 100:
                raise SourceInputError("archive contains a cyclic or excessive link chain")
            visited.add(target)
            target = links[target]
        if target not in names:
            raise SourceInputError("archive contains a dangling link")
    return {"members": count, "declared_expanded_bytes": expanded, "internal_links": len(links)}


def verify_artifact(path: Path, artifact: dict[str, Any]) -> dict[str, int]:
    path = checked_path(path)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > artifact["size"]:
                    raise SourceInputError("source archive exceeds pinned size")
                digest.update(chunk)
    except OSError as exc:
        raise SourceInputError(f"source archive is unavailable: {path.name}") from exc
    if total != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
        raise SourceInputError("source archive hash/size differs from reviewed pin")
    return inspect_archive(path, artifact["filename"])


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise SourceInputError("source redirects are forbidden; review and pin the direct origin")


def _download_to(handle: BinaryIO, artifact: dict[str, Any]) -> None:
    validate_download_url(artifact["url"])
    # Do not inherit credential-bearing proxy environment variables or cookies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirect())
    request = urllib.request.Request(artifact["url"], headers={"Accept-Encoding": "identity", "User-Agent": "DupeZ-source-input-verifier/1"})
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or response.geturl() != artifact["url"]:
                raise SourceInputError("source origin changed or returned a non-success status")
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            length = response.headers.get("Content-Length")
            if encoding != "identity" or (length is not None and (not length.isdecimal() or int(length) != artifact["size"])):
                raise SourceInputError("source transfer metadata differs from pinned input")
            total = 0
            while chunk := response.read(min(1024 * 1024, artifact["size"] - total + 1)):
                total += len(chunk)
                if total > artifact["size"]:
                    raise SourceInputError("source download exceeds pinned size")
                handle.write(chunk)
            if total != artifact["size"]:
                raise SourceInputError("source download was truncated")
    except (OSError, urllib.error.URLError) as exc:
        raise SourceInputError("source download failed") from exc


def collect_artifact(cache: Path, artifact: dict[str, Any], *, max_bytes: int) -> dict[str, int]:
    if artifact["size"] > max_bytes:
        raise SourceInputError(f"{artifact['filename']} exceeds the explicit download budget ({artifact['size']} bytes)")
    cache = checked_path(cache, directory=True)
    cache.mkdir(parents=True, exist_ok=True)
    checked_path(cache, directory=True)
    target = checked_path(cache / artifact["filename"])
    if target.exists():
        return verify_artifact(target, artifact)
    with tempfile.NamedTemporaryFile(prefix=".source-input-", suffix=".part", dir=cache, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            _download_to(handle, artifact)
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        inspection = verify_artifact(temporary, artifact)
        # Hard-link creation fails if the destination appeared meanwhile; no overwrite.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return inspection


def make_receipt(manifest: dict[str, Any], selected: list[dict[str, Any]], inspections: dict[str, dict[str, int]]) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "source_manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
        "claim": "Verified upstream source inputs only; not a release or license approval.",
        "delivery_gaps": delivery_gaps(manifest),
        "uncollected_components": sorted(item["id"] for item in manifest["components"] if item not in selected),
        "artifacts": sorted([
            {"component": item["id"], "version": item["version"], **artifact, **inspections[artifact["filename"]]}
            for item in selected for artifact in item["artifacts"]
        ], key=lambda item: item["filename"]),
    }


def create_bundle(path: Path, cache: Path, manifest: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Create a deterministic, no-overwrite ZIP with archives and honest gaps."""
    path = checked_path(path)
    checked_path(path.parent, directory=True)
    if path.exists():
        raise SourceInputError("bundle already exists; choose a new output path")
    with tempfile.NamedTemporaryFile(prefix=".source-bundle-", suffix=".part", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        _write_bundle(temporary, cache, manifest, receipt)
        # Publish only after every input has been rehashed during copying. Link
        # creation is atomic/no-overwrite; unlike replace(), it cannot clobber.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bundle(path: Path, cache: Path, manifest: dict[str, Any], receipt: dict[str, Any]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, content in (("source-inputs.json", canonical_json(manifest)), ("source-receipt.json", canonical_json(receipt))):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, content)
        for artifact in receipt["artifacts"]:
            source = checked_path(cache / artifact["filename"])
            info = zipfile.ZipInfo("archives/" + artifact["filename"], (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            digest, total = hashlib.sha256(), 0
            with source.open("rb") as original, bundle.open(info, "w", force_zip64=True) as output:
                for chunk in iter(lambda: original.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > artifact["size"]:
                        raise SourceInputError("source changed during bundling")
                    digest.update(chunk)
                    output.write(chunk)
            if total != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
                raise SourceInputError("source changed during bundling")


def verify_bundle(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Rehash every embedded archive against reviewed pins, without extraction.

    Inspection counts are retained as collection evidence, not trusted as proof
    of completeness. The byte hashes bind them to the previously inspected
    archives. Gaps and uncollected components must match the current manifest.
    """
    path = checked_path(path)
    try:
        _check_zip_directory(path)
        with zipfile.ZipFile(path) as bundle:
            members = bundle.infolist()
            if len(members) > 512 or bundle.comment:
                raise SourceInputError("invalid source bundle envelope")
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise SourceInputError("source bundle contains duplicate entries")
            for member in members:
                _member_path(member.orig_filename)
                if member.orig_filename != member.filename or member.flag_bits & 1 or member.compress_type != zipfile.ZIP_STORED or stat.S_IFMT(member.external_attr >> 16) != stat.S_IFREG:
                    raise SourceInputError("source bundle contains unsupported members")
            for name in ("source-inputs.json", "source-receipt.json"):
                if bundle.getinfo(name).file_size > MAX_MANIFEST_BYTES:
                    raise SourceInputError("source bundle metadata exceeds limit")
            if bundle.read("source-inputs.json") != canonical_json(manifest):
                raise SourceInputError("source bundle manifest differs from reviewed manifest")
            receipt = json.loads(bundle.read("source-receipt.json"), object_pairs_hook=_no_duplicates)
            if not isinstance(receipt, dict) or set(receipt) != {
                "schema", "source_manifest_sha256", "claim", "delivery_gaps", "uncollected_components", "artifacts"
            } or receipt["schema"] != RECEIPT_SCHEMA or not isinstance(receipt["artifacts"], list):
                raise SourceInputError("invalid source bundle receipt")
            selected, inspections, seen = [], {}, set()
            components = {item["id"]: item for item in manifest["components"]}
            for artifact in receipt["artifacts"]:
                if not isinstance(artifact, dict) or set(artifact) != {
                    "component", "version", "filename", "url", "size", "sha256", "members", "declared_expanded_bytes", "internal_links"
                }:
                    raise SourceInputError("invalid bundled artifact receipt")
                component = components.get(artifact["component"])
                pin = {key: artifact[key] for key in ("filename", "url", "size", "sha256")}
                if not component or component["version"] != artifact["version"] or pin not in component["artifacts"] or artifact["filename"] in seen:
                    raise SourceInputError("bundled artifact differs from reviewed source pin")
                seen.add(artifact["filename"])
                if component not in selected:
                    selected.append(component)
                inspection = {key: artifact[key] for key in ("members", "declared_expanded_bytes", "internal_links")}
                if any(type(value) is not int or value < 0 for value in inspection.values()) or not 0 < inspection["members"] <= MAX_MEMBERS or inspection["declared_expanded_bytes"] > MAX_EXPANDED_BYTES or inspection["internal_links"] > inspection["members"]:
                    raise SourceInputError("invalid source inspection metadata")
                inspections[artifact["filename"]] = inspection
                member = bundle.getinfo("archives/" + artifact["filename"])
                if member.file_size != artifact["size"]:
                    raise SourceInputError("bundled source size differs from reviewed pin")
                digest = hashlib.sha256()
                with bundle.open(member) as original:
                    for chunk in iter(lambda: original.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != artifact["sha256"]:
                    raise SourceInputError("bundled source hash differs from reviewed pin")
            if not selected or set(names) != {"source-inputs.json", "source-receipt.json", *("archives/" + name for name in seen)}:
                raise SourceInputError("source bundle has missing or unexpected members")
            if receipt != make_receipt(manifest, selected, inspections):
                raise SourceInputError("source bundle receipt omits or misstates delivery gaps")
            return receipt
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise SourceInputError("source bundle is malformed") from exc


def emit_receipt(receipt: dict[str, Any], path: Path | None) -> None:
    data = canonical_json(receipt)
    if path is not None:
        path = checked_path(path)
        checked_path(path.parent, directory=True)
        if path.exists():
            raise SourceInputError("receipt already exists; choose a new output path")
        with tempfile.NamedTemporaryFile(prefix=".source-receipt-", suffix=".part", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(data)
                handle.close()
                os.link(temporary, path)
            finally:
                handle.close()
                temporary.unlink(missing_ok=True)
    print(data.decode(), end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "collect", "verify", "verify-bundle"))
    parser.add_argument("--manifest", type=Path, default=ROOT / "packaging/source-inputs.json")
    parser.add_argument("--inventory", type=Path, default=ROOT / "packaging/third-party-components.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/corresponding-source/archives")
    parser.add_argument("--component", action="append", default=[])
    parser.add_argument("--max-artifact-bytes", type=int, default=DEFAULT_ARTIFACT_BYTES)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--require-delivery-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 0 < args.max_artifact_bytes <= MAX_ARTIFACT_BYTES:
            raise SourceInputError("download budget is outside supported bounds")
        manifest = load_manifest(args.manifest, args.inventory)
        if args.receipt and checked_path(args.receipt).exists():
            raise SourceInputError("receipt already exists; choose a new output path")
        components = {item["id"]: item for item in manifest["components"]}
        if len(args.component) != len(set(args.component)) or set(args.component) - components.keys():
            raise SourceInputError("unknown or repeated component selection")
        selected = [components[key] for key in sorted(args.component or components)]
        if args.require_delivery_ready and (delivery_gaps(manifest) or args.component):
            raise SourceInputError("source delivery is incomplete; unresolved mappings or partial selection remain")
        if args.command == "verify-bundle":
            if not args.bundle or args.component:
                raise SourceInputError("verify-bundle requires --bundle and forbids partial selection")
            emit_receipt(verify_bundle(args.bundle, manifest), args.receipt)
            return 0
        if args.command == "plan":
            if args.bundle or args.receipt:
                raise SourceInputError("plan cannot create a source bundle or receipt")
            print(canonical_json({"schema": SCHEMA, "delivery_gaps": delivery_gaps(manifest), "components": selected}).decode(), end="")
            return 0
        if any(not item["artifacts"] for item in selected):
            raise SourceInputError("selection contains unresolved source inputs; select pinned components explicitly")
        inspections = {}
        for item in selected:
            for artifact in item["artifacts"]:
                if args.command == "collect":
                    inspections[artifact["filename"]] = collect_artifact(args.cache, artifact, max_bytes=args.max_artifact_bytes)
                else:
                    inspections[artifact["filename"]] = verify_artifact(args.cache / artifact["filename"], artifact)
        receipt = make_receipt(manifest, selected, inspections)
        if args.bundle:
            create_bundle(args.bundle, args.cache, manifest, receipt)
        emit_receipt(receipt, args.receipt)
        return 0
    except (SourceInputError, OSError, KeyError, TypeError) as exc:
        print(f"Source input verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
