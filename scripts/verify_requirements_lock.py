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
    from packaging.markers import Marker
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - pip always vendors packaging
    from pip._vendor.packaging.markers import Marker
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import InvalidVersion, Version


_HASH_PREFIX = "--hash=sha256:"
RELEASE_TARGET_ID = "windows-cpython-3.13.17-x64"
_RELEASE_TARGET_ENVIRONMENT = {
    "implementation_name": "cpython",
    "implementation_version": "3.13.17",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "platform_system": "Windows",
    "python_full_version": "3.13.17",
    "python_version": "3.13",
    "sys_platform": "win32",
    "extra": "",
}
_PEP508_MARKER_VARIABLES = frozenset({
    "dependency_groups",
    "extra",
    "extras",
    "implementation_name",
    "implementation_version",
    "os_name",
    "platform_machine",
    "platform_python_implementation",
    "platform_release",
    "platform_system",
    "platform_version",
    "python_full_version",
    "python_version",
    "sys_platform",
})


@dataclass(frozen=True)
class LockedEntry:
    name: str
    version: str
    marker: str
    hashes: tuple[str, ...]
    line_number: int


def release_target_environment() -> dict[str, str]:
    """Return the fixed PEP 508 environment for canonical release artifacts."""

    return dict(_RELEASE_TARGET_ENVIRONMENT)


def release_target_metadata() -> dict[str, object]:
    """Return auditable metadata describing the canonical release target."""

    return {
        "id": RELEASE_TARGET_ID,
        "pep508_environment": release_target_environment(),
    }


def _marker_variables(marker: str) -> set[str]:
    """Return PEP 508 variables outside quoted marker values."""

    unquoted: list[str] = []
    quote = ""
    escaped = False
    for character in marker:
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
                unquoted.append(" ")
            continue
        if character in {'"', "'"}:
            quote = character
            unquoted.append(" ")
        else:
            unquoted.append(character)
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", "".join(unquoted)))
    return words & _PEP508_MARKER_VARIABLES


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
        if text.startswith("-"):
            raise ValueError(
                f"requirement directives are unsupported at {path}:{line_number}"
            )
        try:
            requirement = Requirement(text)
        except InvalidRequirement as exc:
            raise ValueError(
                f"invalid direct requirement at {path}:{line_number}: {text!r}"
            ) from exc
        if requirement.url:
            raise ValueError(
                f"direct URL requirements are not release-lockable: "
                f"{path}:{line_number}"
            )
        if requirement.extras:
            raise ValueError(
                f"direct requirement extras are not release-lockable: "
                f"{path}:{line_number}"
            )
        requirements.append((line_number, requirement))
    return requirements


def parse_lock_entries(path: Path) -> list[LockedEntry]:
    """Parse every logical lock line or fail closed.

    Release locks permit only bare distribution names, one exact ``==`` pin,
    an optional PEP 508 marker, and one or more SHA-256 hashes.  Silently
    ignoring an unsupported line would let pip install content that is absent
    from the SBOM and vulnerability review, so every non-comment logical line
    must be consumed by this parser.
    """

    parsed: list[LockedEntry] = []
    entries: dict[str, LockedEntry] = {}
    for line_number, text in _logical_input_lines(path):
        segments = text.split()
        first_hash = next(
            (
                index
                for index, segment in enumerate(segments)
                if segment.startswith("--hash=")
            ),
            None,
        )
        if first_hash is None:
            raise ValueError(
                f"lock entry has no SHA-256 hash at {path}:{line_number}: "
                f"{text!r}"
            )

        requirement_text = " ".join(segments[:first_hash]).strip()
        hash_tokens = segments[first_hash:]
        if not requirement_text:
            raise ValueError(
                f"orphan lock hash at {path}:{line_number}: {text!r}"
            )
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as exc:
            raise ValueError(
                f"unsupported lock requirement at {path}:{line_number}: "
                f"{requirement_text!r}"
            ) from exc
        if requirement.url:
            raise ValueError(
                f"direct URL lock entries are unsupported at "
                f"{path}:{line_number}"
            )
        if requirement.extras:
            raise ValueError(
                f"lock entry extras are unsupported at {path}:{line_number}"
            )

        specifiers = list(requirement.specifier)
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise ValueError(
                f"lock entry must use one non-wildcard exact == pin at "
                f"{path}:{line_number}"
            )

        hashes: list[str] = []
        for token in hash_tokens:
            if not token.startswith(_HASH_PREFIX):
                raise ValueError(
                    f"unsupported lock option at {path}:{line_number}: {token!r}"
                )
            digest = token[len(_HASH_PREFIX):]
            if len(digest) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in digest
            ):
                raise ValueError(
                    f"invalid SHA-256 lock hash at {path}:{line_number}: "
                    f"{token!r}"
                )
            normalized_digest = digest.lower()
            if normalized_digest in hashes:
                raise ValueError(
                    f"duplicate SHA-256 lock hash at {path}:{line_number}"
                )
            hashes.append(normalized_digest)

        name = canonicalize_name(requirement.name)
        if name in entries:
            previous = entries[name]
            raise ValueError(
                f"duplicate lock entry for {name!r} at lines "
                f"{previous.line_number} and {line_number}"
            )
        entry = LockedEntry(
            name=name,
            version=specifiers[0].version,
            marker=str(requirement.marker or "").strip(),
            hashes=tuple(hashes),
            line_number=line_number,
        )
        entries[name] = entry
        parsed.append(entry)
    return parsed


def select_release_target_entries(
    entries: Iterable[LockedEntry],
) -> list[LockedEntry]:
    """Select lock entries applicable to Windows CPython 3.13.17 x64."""

    environment = release_target_environment()
    selected: list[LockedEntry] = []
    for entry in entries:
        if not entry.marker:
            selected.append(entry)
            continue
        undefined = sorted(_marker_variables(entry.marker) - environment.keys())
        if undefined:
            raise ValueError(
                "lock marker depends on variables not defined by release target "
                f"{RELEASE_TARGET_ID}: {entry.name} at line "
                f"{entry.line_number}: {', '.join(undefined)}"
            )
        if Marker(entry.marker).evaluate(environment=environment):
            selected.append(entry)
    return selected


def parse_release_lock_entries(path: Path) -> list[LockedEntry]:
    """Strictly parse *path* and project it onto the canonical release target."""

    return select_release_target_entries(parse_lock_entries(path))


def parse_lock(path: Path) -> dict[str, LockedEntry]:
    entries = parse_lock_entries(path)
    return {entry.name: entry for entry in entries}


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
        if bool(source_marker) != bool(lock_marker):
            if source_marker:
                errors.append(
                    f"platform marker for {requirement.name!r} was lost in the "
                    f"lock: {source_marker}"
                )
            else:
                errors.append(
                    f"lock injects an unexpected marker for "
                    f"{requirement.name!r}: {lock_marker}"
                )
        elif source_marker and source_marker != lock_marker:
            errors.append(
                f"lock marker for {requirement.name!r} does not exactly match "
                f"the source marker: {lock_marker!r} != {source_marker!r}"
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
