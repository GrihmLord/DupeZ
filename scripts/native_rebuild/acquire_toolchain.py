"""Acquire and inspect the explicitly reviewed portable compiler; never execute it."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import re
import stat
import urllib.parse
import urllib.request
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.native_rebuild import common

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/native-compilation-20261124"
NAME = "llvm-mingw-20261117-ucrt-x86_64.zip"
URL = "https://github.com/mstorsjo/llvm-mingw/releases/download/20261117/" + NAME
SIZE = 191082415
SHA = "4d002e330a0f703625aa5ccbc37e96f8f824413e163bfc7336774aabd2c3a412"
HOPS = []


ordinary = common.ordinary
require = common.require


def approved(url):
    item = urllib.parse.urlsplit(url)
    require(item.scheme == 'https' and item.hostname in {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}, 'Unapproved HTTPS download URL')
    require(item.username is item.password is None and item.port in (None, 443) and (not item.fragment), 'Unapproved HTTPS download URL')
    return item


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        item = approved(newurl)
        require(len(HOPS) < 4, 'Too many download redirects')
        # Do not publish signed CDN query values.
        HOPS.append({"status": code, "host": item.hostname, "path": item.path})
        return super().redirect_request(request, response, code, message, headers, newurl)


def validated_members(container: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], int]:
    """Validate the full central directory before creating any output path."""
    paths = set()
    total = 0
    prefix = NAME[:-4] + "/"
    members = container.infolist()
    require(0 < len(members) <= 100000, 'Unexpected archive member count')
    for member in members:
        name = member.filename
        require(member.orig_filename == name, "ZIP filename was normalized or truncated")
        require(name.startswith(prefix) and len(name) <= 512 and ('\\' not in name) and (':' not in name), 'Unsafe archive member path')
        parts = name.rstrip("/").split("/")
        require(all((part not in {'', '.', '..'} and (not part.endswith(('.', ' '))) and (not re.fullmatch('(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\..*)?', part, re.I)) and (not any((ord(c) < 32 for c in part))) for part in parts)), 'Unsafe archive member path')
        key = "/".join(parts).casefold()
        require(key not in paths, 'Duplicate archive member path')
        paths.add(key)
        mode = stat.S_IFMT(member.external_attr >> 16)
        require(mode in ({0, stat.S_IFDIR} if member.is_dir() else {0, stat.S_IFREG}), 'Unsupported archive member type or flags')
        require(not member.flag_bits & 1 and (not member.external_attr & 1024), 'Unsupported archive member type or flags')
        require(0 <= member.file_size <= 256 * 1024 * 1024, 'Archive size limit exceeded')
        total += member.file_size
        require(total <= 3 * 1024 * 1024 * 1024, 'Archive size limit exceeded')
    return members, total


def main() -> int:
    HOPS.clear()
    inputs = ordinary(BASE / "inputs", missing=True)
    inputs.mkdir(parents=True, exist_ok=True)
    archive = ordinary(inputs / NAME, missing=True)
    if not archive.exists():
        partial = ordinary(inputs / (NAME + ".part"), missing=True)
        approved(URL)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
        request = urllib.request.Request(URL, headers={"User-Agent": "DupeZ-local-source-review", "Accept-Encoding": "identity"})
        total = 0
        digest = hashlib.sha256()
        with opener.open(request, timeout=30) as response, partial.open("xb") as target:
            approved(response.url)
            require(response.status == 200, 'Compiler download did not return HTTP 200')
            length = response.headers.get("Content-Length")
            require(length is None or int(length) == SIZE, 'Compiler download length differs')
            while block := response.read(min(1024 * 1024, SIZE + 1 - total)):
                total += len(block)
                require(total <= SIZE, 'Archive size limit exceeded')
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        require(total == SIZE and digest.hexdigest() == SHA, 'Pinned compiler archive bytes differ')
        require(partial.parent == archive.parent and archive.is_relative_to(BASE) and (not archive.exists()), 'Unsafe or existing extraction destination')
        partial.rename(archive)

    # Parse and extract the same immutable bytes that were hashed.
    with ordinary(archive).open("rb") as stream:
        raw = stream.read(SIZE + 1)
    require(len(raw) == SIZE and hashlib.sha256(raw).hexdigest() == SHA, 'Pinned compiler archive bytes differ')
    destination = ordinary(BASE / "toolchain", missing=True)
    if destination.exists():
        rows = common.toolchain_rows()
        common.verify_toolchain_tree(rows)
        for row in rows:
            require(common.pin(ROOT / row["path"]) == row, "Cached compiler input differs")
        print(json.dumps({"status": "existing-cache-verified", "files": len(rows), "compiler_executed": False}))
        return 0
    require(not destination.exists(), 'Unsafe or existing extraction destination')
    entries = []
    with zipfile.ZipFile(io.BytesIO(raw)) as container:
        members, total = validated_members(container)
        destination.mkdir()
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.filename).parts)
            require(path.is_relative_to(destination), 'Unsafe or existing extraction destination')
            ordinary(path, missing=True)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            actual = 0
            with container.open(member) as source, path.open("xb") as target:
                while block := source.read(1024 * 1024):
                    actual += len(block)
                    require(actual <= member.file_size, 'Archive size limit exceeded')
                    digest.update(block)
                    target.write(block)
            require(actual == member.file_size, 'Archive size limit exceeded')
            entries.append({"path": path.relative_to(ROOT).as_posix(), "size": actual, "sha256": digest.hexdigest()})
    require(common.pin(archive) == {"path": archive.relative_to(ROOT).as_posix(), "size": SIZE, "sha256": SHA},
            'Pinned compiler archive bytes differ')
    inventory = BASE / "toolchain-inventory.json"
    encoded = (json.dumps(entries, indent=2) + "\n").encode()
    with inventory.open("xb") as target:
        target.write(encoded)
    record = {"schema": "dupez.portable-toolchain-acquisition.v1", "observed_on": datetime.now(timezone.utc).date().isoformat(),
              "upstream_url": URL, "github_release_tag": "20261117", "upstream_digest_basis": "GitHub release asset digest",
              "archive": {"path": archive.relative_to(ROOT).as_posix(), "size": SIZE, "sha256": SHA},
              "redirects_without_query": HOPS, "zip_entries": len(members), "files": len(entries), "expanded_bytes": total,
              "inventory": {"path": inventory.relative_to(ROOT).as_posix(), "size": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()},
              "extraction": "Private fresh directory; fixed archive snapshot; paths/types/duplicates/size checked; no native execution",
              "compiler_executed": False, "global_installation_performed": False, "release_approval": False}
    with (BASE / "toolchain-acquisition.json").open("x", encoding="utf-8", newline="\n") as target:
        json.dump(record, target, indent=2)
        target.write("\n")
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
