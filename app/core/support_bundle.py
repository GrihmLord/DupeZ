"""Redacted local support bundle generation.

The support bundle is deliberately JSON-only and data-light. It captures
diagnostics, privacy inventory metadata, and secret-store health without
including raw logs, account tracker contents, secrets, MAC addresses, or raw
local IPs. The artifact is safe to attach to a bug report after review.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit

from app.core.diagnostics import CheckStatus, run_all_checks
from app.core.privacy import build_retention_plan, scan_privacy_items
from app.core.storage_status import build_storage_status
from app.core.updater import CURRENT_VERSION
from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

__all__ = [
    "SupportBundleResult",
    "build_support_bundle",
    "default_support_bundle_path",
    "sanitize_support_value",
    "write_support_bundle",
]


@dataclass(frozen=True)
class SupportBundleResult:
    """Generated support bundle payload and optional destination path."""

    payload: Dict[str, Any]
    path: Optional[Path] = None


def _default_data_dir() -> Path:
    from app.core.data_persistence import _resolve_data_directory
    return Path(_resolve_data_directory())


def _utc_stamp(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_support_bundle_path(
    *,
    output_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Return a safe per-user default destination for a support bundle."""
    root = Path(output_dir) if output_dir is not None else _default_data_dir()
    return root / f"support-bundle-{_utc_stamp(now)}.json"


_LOCAL_PATH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    (re.compile(r"(/Users/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    (re.compile(r"(/home/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
)
_BEARER_SECRET_RE = re.compile(
    r"(?i)\b(?P<scheme>bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_LABELED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<label>\b(?:api[_-]?key|password|passwd|secret|token|credential|"
    r"private[_-]?key|auth|authorization)\b\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted>[^\r\n]*?)(?P=quote)"
    r"|(?P<plain>[^\s,;}\]\r\n]+)"
    r")"
)
_STANDALONE_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\b"
    ),
)
_SENSITIVE_FIELD_RE = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|password|passwd|secret|token|bearer|"
    r"credential|private[_-]?key|auth|authorization)(?:$|[_-])"
)


def _builtin_redact_local_paths(text: str) -> str:
    """Redact common user roots without relying on another app module."""
    redacted = text
    replacements: list[tuple[str, str]] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        replacements.append((local_appdata, "%LOCALAPPDATA%"))
    try:
        replacements.append((str(Path.home()), "~"))
    except Exception:
        pass
    for raw, marker in replacements:
        if not raw:
            continue
        redacted = redacted.replace(raw, marker)
        redacted = redacted.replace(raw.replace("\\", "\\\\"), marker)
        redacted = redacted.replace(raw.replace("\\", "/"), marker)
    for pattern, replacement in _LOCAL_PATH_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _redact_local_paths(text: str) -> str:
    """Redact user-specific filesystem roots from support payload strings."""
    try:
        from app.core.secret_store import _redact_local_paths as redact

        redacted = redact(text)
        if not isinstance(redacted, str):
            raise TypeError("local-path redactor returned a non-string value")
    except Exception:
        redacted = text
    return _builtin_redact_local_paths(redacted)


def _redact_url(value: str) -> str:
    """Remove path/query bearer material from a URL-shaped value."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "[REDACTED URL]"
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return "[REDACTED URL]"
    return f"{parsed.scheme}://{parsed.hostname}{port}/[REDACTED]"


_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _redact_urls_in_text(value: str) -> str:
    """Redact path/query material from URLs embedded in diagnostics text."""
    return _URL_IN_TEXT_RE.sub(lambda match: _redact_url(match.group(0)), value)


def _redact_labeled_secret(match: re.Match[str]) -> str:
    quote = match.group("quote") or ""
    return f"{match.group('label')}{quote}[REDACTED]{quote}"


def _builtin_scrub_secrets(text: str) -> str:
    """Apply dependency-free redaction for common credential shapes."""
    scrubbed = _BEARER_SECRET_RE.sub(
        lambda match: f"{match.group('scheme')} [REDACTED]",
        text,
    )
    scrubbed = _LABELED_SECRET_RE.sub(_redact_labeled_secret, scrubbed)
    for pattern in _STANDALONE_SECRET_RES:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    return scrubbed


def _scrub_secrets(text: str) -> str:
    """Scrub known secrets, failing closed if that registry is unavailable."""
    try:
        from app.core.secrets_manager import scrub_message

        scrubbed = scrub_message(text)
        if not isinstance(scrubbed, str):
            raise TypeError("secret scrubber returned a non-string value")
    except Exception:
        # The external scrubber is the only component that knows arbitrary
        # registered values. No regex fallback can prove such a string safe,
        # so discard the whole field when that registry cannot be consulted.
        return "[REDACTED: secret scrubber unavailable]"
    return _builtin_scrub_secrets(scrubbed)


def _sanitize(value: Any, *, field_name: str = "") -> Any:
    """Recursively scrub strings before they enter the bundle."""
    if isinstance(value, str):
        lowered = field_name.lower()
        if _SENSITIVE_FIELD_RE.search(lowered):
            return "[REDACTED]"
        value = _scrub_secrets(value)
        if lowered in {"url", "webhook_url", "endpoint_url"}:
            value = _redact_url(value)
        else:
            value = _redact_urls_in_text(value)
        value = _redact_local_paths(value)
        value = mask_ips_in_text(value)
        value = mask_macs_in_text(value)
        return value
    if isinstance(value, dict):
        return {
            str(k): _sanitize(v, field_name=str(k))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(v, field_name=field_name) for v in value]
    if isinstance(value, tuple):
        return [_sanitize(v, field_name=field_name) for v in value]
    return value


def sanitize_support_value(value: Any) -> Any:
    """Public wrapper for support-safe redaction of arbitrary values."""
    return _sanitize(value)


def _diagnostic_result_dict(result: Any) -> Dict[str, Any]:
    return _sanitize({
        "name": result.name,
        "status": result.status,
        "message": result.message,
        "fix_hint": result.fix_hint,
        "fix_command": result.fix_command,
    })


def build_support_bundle(
    *,
    include_account_data: bool = False,
    include_file_list: bool = False,
    data_dir: Path | str | None = None,
    diagnostic_results: Iterable[Any] | None = None,
) -> Dict[str, Any]:
    """Build a redacted support bundle payload."""
    diagnostics = (
        list(diagnostic_results)
        if diagnostic_results is not None
        else run_all_checks()
    )
    privacy_items = scan_privacy_items(
        data_dir=data_dir,
        include_account_data=include_account_data,
    )
    diagnostic_summary = {
        "pass": sum(1 for item in diagnostics if item.status == CheckStatus.PASS),
        "warn": sum(1 for item in diagnostics if item.status == CheckStatus.WARN),
        "fail": sum(1 for item in diagnostics if item.status == CheckStatus.FAIL),
    }
    privacy_summary: Dict[str, int] = {}
    for item in privacy_items:
        privacy_summary[item.category] = privacy_summary.get(item.category, 0) + 1
    retention_plan = build_retention_plan(
        data_dir=data_dir,
        include_account_data=include_account_data,
    )
    retention_summary: Dict[str, int] = {}
    for item in retention_plan.eligible:
        retention_summary[item.category] = retention_summary.get(item.category, 0) + 1

    payload = {
        "schema": "dupez.support_bundle.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product": {
            "name": "DupeZ",
            "version": CURRENT_VERSION,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "platform": platform.system() or sys.platform,
        },
        "diagnostics": {
            "summary": diagnostic_summary,
            "results": [_diagnostic_result_dict(item) for item in diagnostics],
        },
        "secret_store": {
            "included": False,
            "reason": "use local diagnostics for key-store health",
        },
        "storage": _sanitize(build_storage_status()),
        "privacy_inventory": {
            "include_account_data": include_account_data,
            "include_file_list": include_file_list,
            "total_files": len(privacy_items),
            "total_bytes": sum(item.size_bytes for item in privacy_items),
            "by_category": privacy_summary,
            "omitted_items": 0 if include_file_list else len(privacy_items),
            "items": [
                {
                    "rel_path": item.rel_path,
                    "category": item.category,
                    "size_bytes": item.size_bytes,
                    "reason": item.reason,
                }
                for item in privacy_items
            ] if include_file_list else [],
        },
        "retention": {
            "rules_days": retention_plan.rules,
            "eligible_files": len(retention_plan.eligible),
            "eligible_bytes": retention_plan.eligible_bytes,
            "eligible_by_category": retention_summary,
        },
    }
    return _sanitize(payload)


def write_support_bundle(
    *,
    output_dir: Path | str | None = None,
    include_account_data: bool = False,
    include_file_list: bool = False,
    data_dir: Path | str | None = None,
    diagnostic_results: Iterable[Any] | None = None,
    output_path: Path | str | None = None,
) -> SupportBundleResult:
    """Write a redacted support bundle JSON file without overwriting files."""
    if output_dir is not None and output_path is not None:
        raise ValueError("choose either output_dir or output_path, not both")
    payload = build_support_bundle(
        include_account_data=include_account_data,
        include_file_list=include_file_list,
        data_dir=data_dir,
        diagnostic_results=diagnostic_results,
    )
    explicit_path = output_path is not None
    path = (
        Path(output_path)
        if explicit_path
        else default_support_bundle_path(output_dir=output_dir)
    )
    if not path.name or path.name in {".", ".."}:
        raise ValueError("support bundle destination must name a file")
    if path.suffix.lower() != ".json":
        path = path.with_name(path.name + ".json")
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    safe_payload = sanitize_support_value(payload)
    import json
    rendered = json.dumps(
        safe_payload,
        indent=2,
        sort_keys=True,
    )

    candidates = [path]
    if not explicit_path:
        candidates.extend(
            path.with_name(f"{path.stem}-{index:02d}{path.suffix}")
            for index in range(1, 100)
        )
    for candidate in candidates:
        created = False
        try:
            with candidate.open("x", encoding="utf-8", newline="\n") as handle:
                created = True
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            return SupportBundleResult(payload=safe_payload, path=candidate)
        except FileExistsError:
            if explicit_path:
                raise
        except Exception:
            if created:
                try:
                    candidate.unlink()
                except OSError:
                    pass
            raise
    raise FileExistsError("no unused support bundle filename is available")
