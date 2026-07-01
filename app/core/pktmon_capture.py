"""Bounded, explicit Windows Pktmon diagnostic capture workflow."""

from __future__ import annotations

import ipaddress
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.safe_subprocess import run
from app.utils.helpers import is_admin

MAX_DURATION_SECONDS = 30
MAX_FILE_SIZE_MB = 32
PACKET_BYTES = 64
SCHEMA = "dupez.pktmon-capture-plan.v1"

__all__ = [
    "MAX_DURATION_SECONDS",
    "MAX_FILE_SIZE_MB",
    "PACKET_BYTES",
    "PktmonCapturePlan",
    "build_capture_plan",
    "execute_capture",
]


def _pktmon_path() -> Path:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return root / "System32" / "pktmon.exe"


def _safe_display_path(path: Path) -> str:
    try:
        from app.core.secret_store import _redact_local_paths

        return _redact_local_paths(str(path))
    except Exception:
        return str(path)


def _validate_ip(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError as exc:
        raise ValueError("Pktmon IP filter must be an IP literal") from exc
    if address.is_multicast or address.is_unspecified:
        raise ValueError("Pktmon IP filter must be a unicast address")
    return str(address)


def _validate_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pktmon port filter must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Pktmon port filter must be between 1 and 65535")
    return port


def _validate_protocol(value: str) -> str:
    protocol = str(value or "udp").strip().upper()
    if protocol not in {"TCP", "UDP"}:
        raise ValueError("Pktmon protocol must be TCP or UDP")
    return protocol


@dataclass(frozen=True)
class PktmonCapturePlan:
    pktmon: Path
    ip: Optional[str]
    port: int
    protocol: str
    duration_seconds: int
    output_dir: Path
    etl_path: Path
    pcapng_path: Path

    def as_dict(self, *, redact_paths: bool = True) -> Dict[str, Any]:
        render = _safe_display_path if redact_paths else str
        return {
            "schema": SCHEMA,
            "filter": {
                "ip": self.ip,
                "port": self.port,
                "protocol": self.protocol,
            },
            "limits": {
                "duration_seconds": self.duration_seconds,
                "file_size_mb": MAX_FILE_SIZE_MB,
                "packet_bytes": PACKET_BYTES,
                "component_scope": "nics",
                "log_mode": "circular",
            },
            "output": {
                "directory": render(self.output_dir),
                "etl": render(self.etl_path),
                "pcapng": render(self.pcapng_path),
            },
            "privacy": {
                "contains_network_identifiers": True,
                "may_contain_packet_payload_prefix": True,
                "automatic_upload": False,
                "automatic_capture": False,
                "review_before_sharing": True,
            },
        }


def build_capture_plan(
    *,
    port: Any,
    ip: Optional[str] = None,
    protocol: str = "udp",
    duration_seconds: Any = 15,
    output_dir: Path | str | None = None,
    now: Optional[datetime] = None,
) -> PktmonCapturePlan:
    """Validate a filter-required capture without changing system state."""
    pktmon = _pktmon_path()
    if not pktmon.is_file():
        raise FileNotFoundError(f"Pktmon is unavailable at {pktmon}")
    validated_port = _validate_port(port)
    validated_ip = _validate_ip(ip)
    validated_protocol = _validate_protocol(protocol)
    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pktmon duration must be an integer") from exc
    if not 1 <= duration <= MAX_DURATION_SECONDS:
        raise ValueError(
            f"Pktmon duration must be between 1 and "
            f"{MAX_DURATION_SECONDS} seconds"
        )
    root = (
        Path(output_dir).expanduser()
        if output_dir is not None
        else _default_capture_dir()
    )
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    stem = f"dupez-pktmon-{stamp}"
    return PktmonCapturePlan(
        pktmon=pktmon,
        ip=validated_ip,
        port=validated_port,
        protocol=validated_protocol,
        duration_seconds=duration,
        output_dir=root,
        etl_path=root / f"{stem}.etl",
        pcapng_path=root / f"{stem}.pcapng",
    )


def _default_capture_dir() -> Path:
    from app.core.app_paths import captures_dir

    return captures_dir()


def _run(plan: PktmonCapturePlan, args: list[str], intent: str):
    return run(
        [str(plan.pktmon), *args],
        timeout=20,
        capture_output=True,
        expect_returncode={0},
        intent=intent,
    )


def execute_capture(
    plan: PktmonCapturePlan,
    *,
    apply: bool = False,
    accept_sensitive_capture: bool = False,
) -> Dict[str, Any]:
    """Execute a bounded capture after two explicit operator confirmations."""
    if not apply:
        raise PermissionError("capture is preview-only unless apply=True")
    if not accept_sensitive_capture:
        raise PermissionError(
            "sensitive capture acknowledgement is required"
        )
    if not is_admin():
        raise PermissionError("Pktmon capture requires Administrator rights")

    plan.output_dir.mkdir(parents=True, exist_ok=True)
    if plan.etl_path.exists() or plan.pcapng_path.exists():
        raise FileExistsError("refusing to overwrite an existing capture")

    listing = _run(plan, ["filter", "list"], "pktmon.filter_list")
    filter_text = f"{listing.stdout}\n{listing.stderr}".strip().lower()
    if "no filter" not in filter_text:
        raise RuntimeError(
            "Pktmon already has filters configured; refusing to remove or "
            "modify operator-managed global filters"
        )

    filter_args = [
        "filter",
        "add",
        "DupeZ_Diagnostic",
        "-t",
        plan.protocol,
        "-p",
        str(plan.port),
    ]
    if plan.ip:
        filter_args.extend(["-i", plan.ip])

    filter_added = False
    capture_started = False
    stop_error = ""
    cleanup_error = ""
    try:
        _run(plan, filter_args, "pktmon.filter_add")
        filter_added = True
        _run(
            plan,
            [
                "start",
                "--capture",
                "--comp",
                "nics",
                "--type",
                "all",
                "--pkt-size",
                str(PACKET_BYTES),
                "--file-name",
                str(plan.etl_path),
                "--file-size",
                str(MAX_FILE_SIZE_MB),
                "--log-mode",
                "circular",
            ],
            "pktmon.capture_start",
        )
        capture_started = True
        time.sleep(plan.duration_seconds)
    finally:
        if capture_started:
            try:
                _run(plan, ["stop"], "pktmon.capture_stop")
            except Exception as exc:
                stop_error = str(exc)
        if filter_added:
            try:
                _run(plan, ["filter", "remove"], "pktmon.filter_remove")
            except Exception as exc:
                cleanup_error = str(exc)

    if stop_error or cleanup_error:
        raise RuntimeError(
            "Pktmon cleanup was incomplete: "
            f"stop={stop_error or 'ok'}; filters={cleanup_error or 'ok'}"
        )
    _run(
        plan,
        [
            "etl2pcap",
            str(plan.etl_path),
            "--out",
            str(plan.pcapng_path),
        ],
        "pktmon.etl2pcap",
    )
    return {
        "schema": "dupez.pktmon-capture-result.v1",
        "ok": True,
        "plan": plan.as_dict(),
        "pcapng": _safe_display_path(plan.pcapng_path),
        "etl": _safe_display_path(plan.etl_path),
        "review_before_sharing": True,
    }
