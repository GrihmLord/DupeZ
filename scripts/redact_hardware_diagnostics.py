"""Create bounded, identifier-free copies of hardware-smoke diagnostics.

Raw hardware logs remain local to the prepared runner. This helper accepts
only text diagnostics below a plain (non-reparse) source root, removes target
and host identifiers, and writes opaque filenames into a brand-new upload
directory. A successful return means that directory contains exactly the
files named and hashed by ``redaction-summary.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterable, Mapping, Sequence


SCHEMA = "dupez.redacted-hardware-diagnostics.v1"
SUMMARY_NAME = "redaction-summary.json"
ALLOWED_SUFFIXES = frozenset({".json", ".log", ".txt", ".xml"})
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILES = 128
MAX_SUMMARY_BYTES = 256 * 1024

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
_IP_COMPONENT = rf"(?:{_OCTET}|[xX]|\*+)"
_IPV4_OR_MASKED_RE = re.compile(
    rf"(?<![\dA-Za-z.*])(?:{_IP_COMPONENT}\.){{3}}{_IP_COMPONENT}"
    r"(?:/(?:[0-9]|[12]\d|3[0-2]))?(?![\dA-Za-z.*])"
)
_IPV6_CANDIDATE_RE = re.compile(
    r"(?:"
    r"\[(?P<bracketed>[0-9A-Fa-f:.]+(?:%[0-9A-Za-z_.-]+)?)\]"
    r"(?![0-9A-Fa-f])"
    r"|"
    r"(?<![0-9A-Fa-f:])"
    r"(?P<plain>(?:[0-9A-Fa-f]{0,4}:){2,}"
    r"[0-9A-Fa-f:.]*(?:%[0-9A-Za-z_.-]+)?)"
    r"(?![0-9A-Fa-f:])"
    r")"
)
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
    r"(?![0-9A-Fa-f])"
)
_DOTTED_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}"
    r"(?![0-9A-Fa-f])"
)
_WINDOWS_USER_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[A-Za-z]:(?:[\\/]+)Users(?:[\\/]+)"
    r"[^\\/\r\n\"'<>:]+"
)
_HOST_VALUE_RE = re.compile(
    r"(?i)(?P<prefix>\b[\"']?(?:target[_-]?)?host(?:name)?[\"']?"
    r"\s*(?:=|:)\s*)"
    r"(?P<value>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|"
    r"[^\s,;}\]]+)"
)
_HOST_QUOTED_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:target[_-]?)?hostname\b\s+)"
    r"(?P<quote>[\"'])(?P<value>[^\"']+)(?P=quote)"
)
_OUTPUT_NAME_RE = re.compile(
    r"diagnostic-[0-9]{3,}(?:\.json|\.log|\.txt|\.xml)"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SUMMARY_KEYS = frozenset(
    {
        "schema",
        "file_count",
        "total_input_bytes",
        "replacement_count",
        "outputs",
        "output_bytes",
        "output_sha256",
    }
)

_PATH_IDENTIFIERS = (
    ("GITHUB_WORKSPACE", "%GITHUB_WORKSPACE%"),
    ("RUNNER_TOOL_CACHE", "%RUNNER_TOOL_CACHE%"),
    ("RUNNER_TEMP", "%RUNNER_TEMP%"),
    ("LOCALAPPDATA", "%LOCALAPPDATA%"),
    ("APPDATA", "%APPDATA%"),
    ("USERPROFILE", "%USERPROFILE%"),
    ("HOME", "%HOME%"),
    ("TEMP", "%TEMP%"),
    ("TMP", "%TMP%"),
)
_NAME_IDENTIFIERS = (
    ("DUPEZ_SMOKETEST_TARGET_HOSTNAME", "[REDACTED-TARGET-HOST]"),
    ("COMPUTERNAME", "[REDACTED-HOST]"),
    ("RUNNER_NAME", "[REDACTED-RUNNER]"),
    ("USERNAME", "[REDACTED-USER]"),
    ("USERDOMAIN", "[REDACTED-DOMAIN]"),
)
_TARGET_IDENTIFIERS = (
    ("DUPEZ_SMOKETEST_CIDR", "[REDACTED-CIDR]"),
    ("DUPEZ_SMOKETEST_TARGET_IP", "[REDACTED-TARGET-IP]"),
    ("DUPEZ_SMOKETEST_TARGET_MAC", "[REDACTED-TARGET-MAC]"),
)


def _absolute_lexical(path: Path) -> Path:
    """Return an absolute path without following a final reparse point."""
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or Windows reparse point."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _require_plain_directory(path: Path, *, label: str) -> None:
    if not os.path.lexists(path):
        raise ValueError(f"{label} does not exist")
    if _is_reparse_point(path):
        raise ValueError(
            f"{label} must not be a symlink, junction, or reparse point"
        )
    if not path.is_dir():
        raise ValueError(f"{label} must be a directory")


def _require_plain_components(root: Path, path: Path, *, label: str) -> None:
    """Reject reparse points in existing components from *root* through *path*."""
    if not _is_within(path, root):
        raise ValueError(f"{label} escapes the diagnostic root")
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if not os.path.lexists(current):
            break
        if _is_reparse_point(current):
            raise ValueError(
                f"{label} contains a symlink, junction, or reparse point"
            )


def _literal_variants(value: str, *, path_value: bool) -> list[str]:
    value = value.strip()
    if not value or value in {".", "..", "/", "\\"}:
        return []
    variants = {value}
    if path_value:
        if "\\" in value:
            variants.add(value.replace("\\", "\\\\"))
            variants.add(value.replace("\\", "/"))
        if "/" in value:
            variants.add(value.replace("/", "\\"))
            variants.add(value.replace("/", "\\\\"))
    return sorted(variants, key=len, reverse=True)


def _replace_literal(
    text: str,
    value: str,
    marker: str,
    *,
    path_value: bool = False,
) -> tuple[str, int]:
    replacements = 0
    for variant in _literal_variants(value, path_value=path_value):
        text, count = re.subn(
            re.escape(variant),
            lambda _match: marker,
            text,
            flags=re.IGNORECASE,
        )
        replacements += count
    return text, replacements


def _redact_ipv6(text: str) -> tuple[str, int]:
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        candidate = match.group("bracketed") or match.group("plain") or ""
        trailing = ""
        while candidate.endswith("."):
            candidate = candidate[:-1]
            trailing += "."
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            return match.group(0)
        replacements += 1
        return "[REDACTED-IPV6]" + trailing

    return _IPV6_CANDIDATE_RE.sub(replace, text), replacements


def _replace_host_value(match: re.Match[str]) -> str:
    raw = match.group("value")
    if len(raw) >= 2 and raw[0] in {"\"", "'"} and raw[-1] == raw[0]:
        marker = f"{raw[0]}[REDACTED-HOST]{raw[0]}"
    else:
        marker = '"[REDACTED-HOST]"'
    return match.group("prefix") + marker


def _replace_quoted_host(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return match.group("prefix") + quote + "[REDACTED-HOST]" + quote


def redact_text(
    text: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, int]:
    """Remove target, network, MAC, path, and host identifiers from text."""
    env = environment if environment is not None else os.environ
    replacements = 0

    for name, marker in _TARGET_IDENTIFIERS:
        text, count = _replace_literal(text, str(env.get(name) or ""), marker)
        replacements += count

    path_values = sorted(
        (
            (str(env.get(name) or ""), marker)
            for name, marker in _PATH_IDENTIFIERS
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for value, marker in path_values:
        text, count = _replace_literal(text, value, marker, path_value=True)
        replacements += count

    for name, marker in _NAME_IDENTIFIERS:
        value = str(env.get(name) or "").strip()
        if len(value) < 3:
            continue
        text, count = _replace_literal(text, value, marker)
        replacements += count

    text, count = _redact_ipv6(text)
    replacements += count
    text, count = _IPV4_OR_MASKED_RE.subn("[REDACTED-IP]", text)
    replacements += count
    text, count = _MAC_RE.subn("[REDACTED-MAC]", text)
    replacements += count
    text, count = _DOTTED_MAC_RE.subn("[REDACTED-MAC]", text)
    replacements += count
    text, count = _WINDOWS_USER_RE.subn(r"%USERPROFILE%", text)
    replacements += count
    text, count = _HOST_VALUE_RE.subn(_replace_host_value, text)
    replacements += count
    text, count = _HOST_QUOTED_RE.subn(_replace_quoted_host, text)
    replacements += count
    return text, replacements


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _walk_error(error: OSError) -> None:
    raise error


def _source_files(root: Path, sources: Iterable[str]) -> list[Path]:
    files: set[Path] = set()
    for source in sources:
        relative = Path(source)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("diagnostic sources must be root-relative")
        candidate = root / relative
        _require_plain_components(root, candidate, label="diagnostic source")
        if not os.path.lexists(candidate):
            continue
        if _is_reparse_point(candidate):
            raise ValueError(
                "diagnostic source must not be a symlink, junction, or reparse point"
            )

        if candidate.is_file():
            paths = [candidate]
        elif candidate.is_dir():
            paths = []
            for directory, directory_names, file_names in os.walk(
                candidate,
                topdown=True,
                onerror=_walk_error,
                followlinks=False,
            ):
                directory_path = Path(directory)
                if _is_reparse_point(directory_path):
                    raise ValueError(
                        "diagnostic source tree contains a symlink, junction, "
                        "or reparse point"
                    )
                for name in directory_names:
                    child = directory_path / name
                    if _is_reparse_point(child):
                        raise ValueError(
                            "diagnostic source tree contains a symlink, junction, "
                            "or reparse point"
                        )
                    if not child.is_dir():
                        raise ValueError(
                            "diagnostic source tree contains a non-directory entry"
                        )
                for name in file_names:
                    child = directory_path / name
                    if _is_reparse_point(child):
                        raise ValueError(
                            "diagnostic source tree contains a symlink, junction, "
                            "or reparse point"
                        )
                    if not child.is_file():
                        raise ValueError(
                            "diagnostic source tree contains a non-regular file"
                        )
                    if child.suffix.casefold() in ALLOWED_SUFFIXES:
                        paths.append(child)
        else:
            raise ValueError("diagnostic source must be a regular file or directory")

        for path in paths:
            resolved = path.resolve(strict=True)
            if not _is_within(resolved, root):
                raise ValueError("diagnostic source resolves outside the root")
            if resolved.suffix.casefold() in ALLOWED_SUFFIXES:
                files.add(resolved)
                if len(files) > MAX_FILES:
                    raise ValueError("hardware diagnostics exceed the file-count limit")
    return sorted(files, key=lambda item: str(item).casefold())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _valid_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def verify_redacted_output(
    output_directory: Path,
    *,
    expected_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Verify that an upload directory exactly matches its bounded summary."""
    output = _absolute_lexical(output_directory)
    _require_plain_directory(output, label="diagnostic output")
    summary_path = output / SUMMARY_NAME
    if not os.path.lexists(summary_path) or _is_reparse_point(summary_path):
        raise ValueError("redaction summary is missing or is a reparse point")
    if not summary_path.is_file():
        raise ValueError("redaction summary must be a regular file")
    if summary_path.stat().st_size > MAX_SUMMARY_BYTES:
        raise ValueError("redaction summary exceeds its size limit")
    try:
        stored = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("redaction summary is not valid UTF-8 JSON") from exc
    if not isinstance(stored, dict):
        raise ValueError("redaction summary must be a JSON object")
    if expected_summary is not None and stored != dict(expected_summary):
        raise ValueError("redaction summary does not match the generated summary")
    if set(stored) != _SUMMARY_KEYS:
        raise ValueError("redaction summary fields do not match the exact schema")
    if stored.get("schema") != SCHEMA:
        raise ValueError("redaction summary schema mismatch")

    outputs = stored.get("outputs")
    if (
        not isinstance(outputs, list)
        or any(not isinstance(name, str) for name in outputs)
        or len(outputs) != len(set(outputs))
        or any(_OUTPUT_NAME_RE.fullmatch(name) is None for name in outputs)
    ):
        raise ValueError("redaction summary output allowlist is invalid")
    if (
        not _valid_nonnegative_int(stored.get("file_count"))
        or stored["file_count"] != len(outputs)
        or stored["file_count"] > MAX_FILES
        or not _valid_nonnegative_int(stored.get("total_input_bytes"))
        or stored["total_input_bytes"] > MAX_TOTAL_BYTES
        or not _valid_nonnegative_int(stored.get("replacement_count"))
    ):
        raise ValueError("redaction summary counters are invalid")

    hashes = stored.get("output_sha256")
    sizes = stored.get("output_bytes")
    if (
        not isinstance(hashes, dict)
        or set(hashes) != set(outputs)
        or any(
            not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
            for value in hashes.values()
        )
        or not isinstance(sizes, dict)
        or set(sizes) != set(outputs)
        or any(not _valid_nonnegative_int(value) for value in sizes.values())
    ):
        raise ValueError("redaction summary file metadata is invalid")

    entries = list(output.iterdir())
    actual_names = {entry.name for entry in entries}
    expected_names = set(outputs) | {SUMMARY_NAME}
    if len(entries) != len(actual_names) or actual_names != expected_names:
        raise ValueError("diagnostic output does not match its exact upload allowlist")
    for entry in entries:
        if _is_reparse_point(entry) or not entry.is_file():
            raise ValueError("diagnostic output contains a non-regular or reparse entry")
    for name in outputs:
        path = output / name
        if path.stat().st_size != sizes[name] or _sha256(path) != hashes[name]:
            raise ValueError("diagnostic output content does not match its summary")
    return stored


def redact_diagnostics(
    *,
    root: Path,
    sources: Sequence[str],
    output_directory: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Write redacted diagnostic copies and return a verified safe summary."""
    root_input = _absolute_lexical(root)
    _require_plain_directory(root_input, label="diagnostic root")
    root_resolved = root_input.resolve(strict=True)

    requested_output = _absolute_lexical(output_directory)
    if _is_within(requested_output, root_input):
        output = root_resolved / requested_output.relative_to(root_input)
    else:
        output = requested_output
    if not _is_within(output, root_resolved) or output == root_resolved:
        raise ValueError("diagnostic output must be a root subdirectory")
    _require_plain_components(root_resolved, output.parent, label="diagnostic output")
    _require_plain_directory(output.parent, label="diagnostic output parent")
    if os.path.lexists(output):
        raise ValueError("diagnostic output must be a new directory")

    files = _source_files(root_resolved, sources)
    try:
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("diagnostic output must be a new directory") from exc
    if _is_reparse_point(output) or not output.is_dir():
        raise ValueError("diagnostic output must be a plain directory")

    total_bytes = 0
    replacement_count = 0
    outputs: list[str] = []
    output_hashes: dict[str, str] = {}
    output_sizes: dict[str, int] = {}
    for index, source in enumerate(files, start=1):
        if _is_reparse_point(source):
            raise ValueError("diagnostic source became a reparse point")
        before_open = source.lstat()
        with source.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (before_open.st_dev, before_open.st_ino)
            ):
                raise ValueError("diagnostic source changed before it was read")
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("a hardware diagnostic exceeds the per-file size limit")
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("hardware diagnostics exceed the aggregate size limit")

        text = data.decode("utf-8", errors="replace")
        redacted, count = redact_text(text, environment=environment)
        replacement_count += count
        destination = output / f"diagnostic-{index:03d}{source.suffix.casefold()}"
        _write_text_exclusive(destination, redacted)
        if _is_reparse_point(destination) or not destination.is_file():
            raise ValueError("redacted diagnostic destination is not a regular file")
        outputs.append(destination.name)
        output_sizes[destination.name] = destination.stat().st_size
        output_hashes[destination.name] = _sha256(destination)

    summary: dict[str, object] = {
        "schema": SCHEMA,
        "file_count": len(outputs),
        "total_input_bytes": total_bytes,
        "replacement_count": replacement_count,
        "outputs": outputs,
        "output_bytes": output_sizes,
        "output_sha256": output_hashes,
    }
    _write_text_exclusive(
        output / SUMMARY_NAME,
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    return verify_redacted_output(output, expected_summary=summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    root = _absolute_lexical(args.root)
    output = args.output if args.output.is_absolute() else root / args.output
    summary = redact_diagnostics(
        root=root,
        sources=args.source,
        output_directory=output,
    )
    print(
        "Redacted hardware diagnostics: "
        f"{summary['file_count']} file(s), "
        f"{summary['replacement_count']} replacement(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
