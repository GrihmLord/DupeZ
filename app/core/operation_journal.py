"""Crash-safe marker for network state that may require restoration."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

SCHEMA = "dupez.operation-journal.v1"


def default_journal_path() -> Path:
    base = Path(
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_STATE_HOME")
        or Path.home()
    )
    return base / "DupeZ" / "recovery" / "active-operation.json"


class OperationJournal:
    """Atomic pending-state marker containing no target identifiers."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_journal_path()

    def _load_payload(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("schema") == SCHEMA:
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _write_payload(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def mark_pending(self, reason: str) -> None:
        payload = self._load_payload()
        reasons = set(payload.get("reasons", []))
        legacy_reason = payload.get("reason")
        if isinstance(legacy_reason, str) and legacy_reason:
            reasons.add(legacy_reason)
        reasons.add(str(reason)[:80])
        payload.update({
            "schema": SCHEMA,
            "pending": True,
            "reasons": sorted(reasons),
            "pid": os.getpid(),
            "marked_at": int(time.time()),
        })
        payload.pop("reason", None)
        self._write_payload(payload)

    def mark_forwarding_change(self, original_enabled: bool) -> None:
        self.mark_pending("ip_forwarding_change")
        payload = self._load_payload()
        payload["forwarding_original_enabled"] = bool(original_enabled)
        self._write_payload(payload)

    def forwarding_original_state(self) -> Optional[bool]:
        payload = self._load_payload()
        value = payload.get("forwarding_original_enabled")
        return value if isinstance(value, bool) else None

    def clear_forwarding_change(self) -> None:
        payload = self._load_payload()
        reasons = set(payload.get("reasons", []))
        reasons.discard("ip_forwarding_change")
        payload.pop("forwarding_original_enabled", None)
        if not reasons:
            self.clear()
            return
        payload["reasons"] = sorted(reasons)
        self._write_payload(payload)

    def is_pending(self) -> bool:
        if not self.path.exists():
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return (
                payload.get("schema") == SCHEMA
                and payload.get("pending") is True
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            # Corruption is treated as pending so recovery fails safe.
            return True

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            # The caller will see is_pending() remain true on the next launch.
            return
