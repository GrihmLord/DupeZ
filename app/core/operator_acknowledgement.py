"""Versioned acknowledgement for authorized, owned-network operation."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

SCHEMA = "dupez.operator-acknowledgement.v1"
POLICY_VERSION = 1

ACKNOWLEDGEMENT_TEXT = (
    "I will use DupeZ only on networks and devices I own or have explicit "
    "permission to test. I will not use it against public servers, third-party "
    "devices, or to evade platform safeguards. I understand that active "
    "operations can interrupt connectivity and that I am responsible for "
    "complying with applicable law and platform terms."
)


def default_acknowledgement_path() -> Path:
    """Return a per-user state path that remains writable after installation."""
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or os.path.expanduser(r"~\AppData\Local")
        )
    else:
        base = Path(
            os.environ.get("XDG_STATE_HOME")
            or os.path.expanduser("~/.local/state")
        )
    return base / "DupeZ" / "operator-acknowledgement.json"


def acknowledgement_status(path: Optional[Path] = None) -> dict:
    """Return a stable, privacy-preserving acknowledgement status."""
    target = Path(path) if path is not None else default_acknowledgement_path()
    status = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "acknowledged": False,
        "acknowledged_at": None,
    }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return status
    if not isinstance(payload, dict):
        return status
    if (
        payload.get("schema") == SCHEMA
        and payload.get("policy_version") == POLICY_VERSION
        and payload.get("acknowledged") is True
    ):
        status["acknowledged"] = True
        timestamp = payload.get("acknowledged_at")
        if isinstance(timestamp, int) and timestamp > 0:
            status["acknowledged_at"] = timestamp
    return status


def is_acknowledged(path: Optional[Path] = None) -> bool:
    return bool(acknowledgement_status(path)["acknowledged"])


def record_acknowledgement(
    path: Optional[Path] = None,
    *,
    acknowledged_at: Optional[int] = None,
) -> Path:
    """Atomically record the current policy version without collecting PII."""
    target = Path(path) if path is not None else default_acknowledgement_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "acknowledged": True,
        "acknowledged_at": int(
            time.time() if acknowledged_at is None else acknowledged_at
        ),
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target


def clear_acknowledgement(path: Optional[Path] = None) -> None:
    """Clear acknowledgement so the current policy is shown again."""
    target = Path(path) if path is not None else default_acknowledgement_path()
    try:
        target.unlink(missing_ok=True)
    except OSError:
        return
