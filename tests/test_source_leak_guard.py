"""Repository leak guards for secrets and personal network identifiers."""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]

_TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".ini",
    ".iss",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".qss",
    ".sh",
    ".toml",
    ".txt",
    ".yml",
}

_EXCLUDED_PREFIXES = (
    "app/firewall/clumsy_src/",
    "docs/archive/",
)

_HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "discord_webhook": re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
}

_IP_LITERAL = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)

_PUBLIC_IP_ALLOWLIST = {
    "1.1.1.1",  # public DNS example
    "5.1.4.2",  # NIST SP 800-63B section reference, not an address
    "8.8.8.8",  # public DNS reachability probe
    "8.8.4.4",  # public DNS example
}


def _tracked_text_files() -> list[Path]:
    env = dict(os.environ)
    env.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    files: list[Path] = []
    for raw in result.stdout.splitlines():
        rel = raw.replace("\\", "/")
        if rel.startswith(_EXCLUDED_PREFIXES):
            continue
        path = _ROOT / rel
        if path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)
    return files


def _source_tree_text_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("app", "plugins", "scripts", "tools", "tests"):
        for path in (_ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            rel = path.relative_to(_ROOT).as_posix()
            if rel.startswith(_EXCLUDED_PREFIXES):
                continue
            if any(part == "__pycache__" for part in path.parts):
                continue
            if rel.startswith("app/data/"):
                continue
            files.append(path)
    return files


def _leak_scan_files() -> list[Path]:
    return sorted(
        set(_tracked_text_files()).union(_source_tree_text_files()),
        key=lambda path: path.relative_to(_ROOT).as_posix(),
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _is_safe_example_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    if value in _PUBLIC_IP_ALLOWLIST:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def test_tracked_text_files_do_not_contain_high_confidence_secrets() -> None:
    findings: list[str] = []
    for path in _leak_scan_files():
        text = _read_text(path)
        rel = path.relative_to(_ROOT).as_posix()
        for name, pattern in _HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{rel}: {name}")

    assert findings == []


def test_shipped_app_config_has_no_unapproved_public_ipv4_literals() -> None:
    findings: list[str] = []
    for path in _leak_scan_files():
        rel = path.relative_to(_ROOT).as_posix()
        if not rel.startswith(("app/", "plugins/", "scripts/", "tools/")):
            continue
        text = _read_text(path)
        for match in _IP_LITERAL.finditer(text):
            value = match.group(0)
            if not _is_safe_example_ip(value):
                findings.append(f"{rel}: public IPv4 literal")

    assert findings == []
