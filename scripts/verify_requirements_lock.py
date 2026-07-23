#!/usr/bin/env python3
"""Verify that the committed hashed lock satisfies requirements.in.

Re-resolving broad version ranges against the live package index is not a
stable lockfile check: a new upstream release can rewrite the entire graph even
when the source requirements did not change. This verifier checks the contract
that matters for a committed release lock without silently upgrading anything:

* every direct requirement has exactly one locked distribution;
* the locked version satisfies the declared specifier;
* platform markers remain attached to platform-specific direct requirements;
* every locked distribution has one or more SHA-256 hashes;
* lock entries are exact ``==`` pins rather than ranges.

CI separately performs a ``pip install --dry-run --require-hashes`` against the
lock, which validates dependency closure and artifact availability.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - pip always vendors packaging
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import InvalidVersion, Version


_LOCK_ENTRY_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;\\]+)"
    r"(?:\s*;\s*(?P<marker>.*?))?\s*\\?\s*$"
)
_HASH_RE = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}\b")


@dataclass(frozen=True)
class LockedEntry:
    name: str
    version: str
    marker: str
    hashes: tuple[str, ...]
    line_number: int


def _logical_input_lines(path: Path) -> Iterable[tuple[int, str]]:
    """Yield non-comment requirement lines with continuations joined."""

    buffer = ""
    start_line = 0
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not buffer:
            start_line = line_number
        fragment = stripped[:-1].rstrip() if stripped.endswith("\\") else stripped
        buffer = f"{buffer} {fragment}".strip()
        if stripped.endswith("\\"):
            continue
        yield start_line, buffer
        buffer = ""
    if buffer:
        yield start_line, buffer


def parse_direct_requirements(path: Path) -> list[tuple[int, Requirement]]:
    requirements: list[tuple[int, Requirement]] = []
    for line_number, text in _logical_input_lines(path):
        if text.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            raise ValueError(
                f"nested requirement files are unsupported at {path}:{line_number}"
            )
        if text.startswith("--"):
            continue
        requirement = Requirement(text)
        if requirement.url:
            raise ValueError(
                f"direct URL requirements are not release-lockable: "
                f"{path}:{line_number}"
            )
        requirements.append((line_number, requirement))
    return requirements


def parse_lock(path: Path) -> dict[str, LockedEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: dict[str, LockedEntry] = {}
    index = 0
    while index < len(lines):
        match = _LOCK_ENTRY_RE.match(lines[index].strip())
        if match is None:
            index += 1
            continue

        name = canonicalize_name(match.group("name"))
        if name in entries:
            previous = entries[name]
            raise ValueError(
                f"duplicate lock entry for {name!r} at lines "
                f"{previous.line_number} and {index + 1}"
            )

        hashes: list[str] = []
        cursor = index
        while cursor < len(lines):
            current = lines[cursor].strip()
            hashes.extend(_HASH_RE.findall(current))
            if cursor > index and current and not current.startswith(("--hash=", "#")):
                break
            if cursor > index and not lines[cursor - 1].rstrip().endswith("\\"):
                break
            cursor += 1

        marker = (match.group("marker") or "").rstrip(" \\").strip()
        entries[name] = LockedEntry(
            name=name,
            version=match.group("version"),
            marker=marker,
            hashes=tuple(dict.fromkeys(hashes)),
            line_number=index + 1,
        )
        index += 1
    return entries


def verify(requirements_path: Path, lock_path: Path) -> list[str]:
    errors: list[str] = []
    direct = parse_direct_requirements(requirements_path)
    locked = parse_lock(lock_path)

    if not direct:
        errors.append(f"{requirements_path} contains no direct requirements")
    if not locked:
        errors.append(f"{lock_path} contains no exact lock entries")
        return errors

    for name, entry in sorted(locked.items()):
        try:
            Version(entry.version)
        except InvalidVersion:
            errors.append(
                f"lock entry {name} has invalid version {entry.version!r} "
                f"at line {entry.line_number}"
            )
        if not entry.hashes:
            errors.append(
                f"lock entry {name}=={entry.version} has no SHA-256 hash "
                f"at line {entry.line_number}"
            )

    seen_direct: set[str] = set()
    for line_number, requirement in direct:
        name = canonicalize_name(requirement.name)
        if name in seen_direct:
            errors.append(
                f"duplicate direct requirement {requirement.name!r} "
                f"at {requirements_path}:{line_number}"
            )
            continue
        seen_direct.add(name)
        entry = locked.get(name)
        if entry is None:
            errors.append(
                f"direct requirement {requirement.name!r} is missing from {lock_path}"
            )
            continue

        try:
            locked_version = Version(entry.version)
        except InvalidVersion:
            continue
        if requirement.specifier and locked_version not in requirement.specifier:
            errors.append(
                f"{requirement.name}=={entry.version} does not satisfy "
                f"{requirement.specifier} from {requirements_path}:{line_number}"
            )

        source_marker = str(requirement.marker or "").strip()
        lock_marker = entry.marker.strip()
        if source_marker and not lock_marker:
            errors.append(
                f"platform marker for {requirement.name!r} was lost in the lock: "
                f"{source_marker}"
            )
        elif source_marker and lock_marker:
            # Marker string formatting can differ, but each normalized marker
            # must at least retain the source variables and comparison values.
            source_tokens = set(re.findall(r"[A-Za-z0-9_.-]+", source_marker))
            lock_tokens = set(re.findall(r"[A-Za-z0-9_.-]+", lock_marker))
            missing_tokens = sorted(source_tokens - lock_tokens)
            if missing_tokens:
                errors.append(
                    f"lock marker for {requirement.name!r} does not preserve "
                    f"source marker tokens: {', '.join(missing_tokens)}"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", default="requirements.in")
    parser.add_argument("--lock", default="requirements-locked.txt")
    args = parser.parse_args(argv)

    requirements_path = Path(args.requirements)
    lock_path = Path(args.lock)
    try:
        errors = verify(requirements_path, lock_path)
    except Exception as exc:
        print(f"requirements lock verification error: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    direct_count = len(parse_direct_requirements(requirements_path))
    lock_count = len(parse_lock(lock_path))
    print(
        "Requirements lock contract: PASS "
        f"({direct_count} direct requirements, {lock_count} hashed pins)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
