"""Record local recipient-build observations; never issue release approval.

This hashes operator-supplied local files and checks the maintenance report.
It does not execute binaries, authenticate an operator report, prove complete
corresponding source, or substitute for signed exact-artifact release gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile


SCHEMA = "dupez.recipient-rebuild-observation.v1"
MARKER = "dupez-recipient-validation-20261024"


def _regular(path: Path) -> None:
    path = Path(os.path.abspath(path))
    for component in (path, *path.parents):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Evidence paths must not contain links/reparse points")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Evidence inputs must be regular files")


def fingerprint(path: Path) -> dict:
    _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        initial = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        final = os.fstat(stream.fileno())
    if (initial.st_size, initial.st_mtime_ns, initial.st_ino) != (
        final.st_size, final.st_mtime_ns, final.st_ino
    ):
        raise ValueError("Evidence input changed while hashing")
    if not final.st_size:
        raise ValueError("Evidence input is empty")
    return {"name": path.name, "size": final.st_size, "sha256": digest.hexdigest()}


def build_observation(
    *, archive: Path, commit: str, artifact: Path, report: Path,
    variant: str, exit_code: int, modified: bool, inputs: list[Path],
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full source commit is required")
    if variant not in {"gpu", "compat"} or type(exit_code) is not int or exit_code != 0:
        raise ValueError("A successful observed process exit and known variant are required")
    source = fingerprint(archive)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.comment != commit.encode("ascii"):
            raise ValueError("Source archive commit does not match")
        names = bundle.namelist()
        required = {"dupez.py", "app/__version__.py", "requirements-locked.txt"}
        roots = {name.split("/", 1)[0] for name in names}
        if len(roots) == 1 and re.fullmatch(r"DupeZ-v\d+\.\d+\.\d+", next(iter(roots))):
            prefix = next(iter(roots)) + "/"
            normalized = [name[len(prefix):] for name in names if not name.endswith("/")]
        else:
            prefix = ""
            normalized = [name for name in names if not name.endswith("/")]
        if any(re.match(r"DupeZ-v\d+\.\d+\.\d+/", name) for name in normalized):
            raise ValueError("Source archive mixes source roots")
        if len({name.casefold() for name in normalized}) != len(normalized):
            raise ValueError("Source archive contains duplicate or colliding paths")
        if not required.issubset(normalized):
            raise ValueError("Source archive lacks application inputs")
    if fingerprint(archive) != source:
        raise ValueError("Source archive changed during inspection")
    report_fingerprint = fingerprint(report)
    if report_fingerprint["size"] > 4096:
        raise ValueError("Runtime report exceeds the observation limit")
    with report.open("rb") as stream:
        report_bytes = stream.read(4097)
    if len(report_bytes) > 4096 or hashlib.sha256(report_bytes).hexdigest() != report_fingerprint["sha256"]:
        raise ValueError("Runtime report changed during inspection")
    result = json.loads(report_bytes)
    required = {"check": "runtime-imports", "ok": True}
    if modified:
        required.update(application_marker=MARKER, library_marker=MARKER)
    if not isinstance(result, dict) or result.get("ok") is not True or result != required:
        raise ValueError("Runtime report does not demonstrate the requested scenario")
    if modified and len(inputs) < 3:
        raise ValueError("Modified builds require recorded source/library/launcher inputs")
    records = [fingerprint(path) for path in inputs]
    if len({item["name"].casefold() for item in records}) != len(records):
        raise ValueError("Ambiguous evidence input names")
    return {
        "schema": SCHEMA,
        "disposition": "local-operator-observation-not-release-approval",
        "source_commit": commit,
        "source_archive": source,
        "source_prefix": prefix,
        "variant": variant,
        "scenario": "modified-application-and-zeroconf-python-layer" if modified else "baseline-imports",
        "artifact": fingerprint(artifact),
        "observed_exit_code": exit_code,
        "runtime_report": report_fingerprint,
        "runtime_result": result,
        "additional_inputs": sorted(records, key=lambda item: item["name"]),
        "limitations": [
            "Operator-supplied report and exit status are not independently authenticated.",
            "Native Qt/Chromium replacement and complete corresponding source are not demonstrated.",
            "No GUI, renderer, packet engine, hardware or official release validation is asserted.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--variant", choices=("gpu", "compat"), required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--modified", action="store_true")
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_observation(
        archive=args.archive, commit=args.commit, artifact=args.artifact,
        report=args.report, variant=args.variant, exit_code=args.exit_code,
        modified=args.modified, inputs=args.input,
    )
    # Evidence records never replace an earlier observation.
    output = Path(os.path.abspath(args.output))
    for parent in (output.parent, *output.parent.parents):
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Evidence output parents must be ordinary non-reparse directories")
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("Recorded local recipient observation; not release approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
