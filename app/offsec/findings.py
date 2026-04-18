"""
Finding registry for the offsec self-test layer.

Produces structured, reviewable findings with CVSS base scores,
MITRE ATT&CK technique references, and references to the code path
that exposed them. The format is close enough to OCSF / SARIF that
downstream tooling (Defender ASR analysis, security dashboards) can
ingest it without a custom schema.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import threading
import time
from pathlib import Path
from typing import List, Optional

__all__ = [
    "Severity",
    "Finding",
    "FindingRegistry",
]


class Severity(enum.Enum):
    """CVSS v3.1 qualitative severity bands."""

    CRITICAL = "CRITICAL"   # base score 9.0 – 10.0
    HIGH = "HIGH"           # base score 7.0 – 8.9
    MEDIUM = "MEDIUM"       # base score 4.0 – 6.9
    LOW = "LOW"             # base score 0.1 – 3.9
    INFO = "INFO"           # no CVSS — informational observation


@dataclasses.dataclass
class Finding:
    """A single offsec finding.

    Attributes:
        id: stable identifier of the form ``DUPEZ-OFFSEC-####``.
        title: short human-readable title.
        description: full description — what was observed, where, and
            why it matters.
        severity: CVSS band.
        cvss_base: CVSS v3.1 base score (0.0 if Severity.INFO).
        cvss_vector: CVSS v3.1 vector string (empty if Severity.INFO).
        attack_technique: MITRE ATT&CK technique ID (e.g. "T1059")
            or empty string for observations outside the matrix.
        evidence: free-form dict with raw artifacts (command output,
            file paths, pcap snippets). Must be JSON-serialisable.
        remediation: concrete instructions for a reviewer to resolve
            the finding, or empty if the remediation is unclear.
    """

    id: str
    title: str
    description: str
    severity: Severity
    cvss_base: float = 0.0
    cvss_vector: str = ""
    attack_technique: str = ""
    evidence: dict = dataclasses.field(default_factory=dict)
    remediation: str = ""
    discovered_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "cvss_base": round(self.cvss_base, 1),
            "cvss_vector": self.cvss_vector,
            "attack_technique": self.attack_technique,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "discovered_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(self.discovered_at),
            ),
        }


class FindingRegistry:
    """Thread-safe accumulator of findings.

    Modules call :meth:`record` during their checks; at the end of a
    run, :meth:`write_json` emits the full set to disk.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: List[Finding] = []
        self._next_id = 1

    def record(
        self,
        *,
        title: str,
        description: str,
        severity: Severity,
        cvss_base: float = 0.0,
        cvss_vector: str = "",
        attack_technique: str = "",
        evidence: Optional[dict] = None,
        remediation: str = "",
    ) -> Finding:
        with self._lock:
            fid = f"DUPEZ-OFFSEC-{self._next_id:04d}"
            self._next_id += 1
            f = Finding(
                id=fid,
                title=title,
                description=description,
                severity=severity,
                cvss_base=cvss_base,
                cvss_vector=cvss_vector,
                attack_technique=attack_technique,
                evidence=evidence or {},
                remediation=remediation,
            )
            self._items.append(f)
            return f

    def all(self) -> List[Finding]:
        """Return a shallow copy of all findings."""
        with self._lock:
            return list(self._items)

    def summary(self) -> dict:
        """Return a severity-bucket summary for quick triage."""
        buckets = {s.value: 0 for s in Severity}
        with self._lock:
            for f in self._items:
                buckets[f.severity.value] += 1
            total = len(self._items)
        return {"total": total, "by_severity": buckets}

    def write_json(self, path: Path, *, product_version: str = "") -> None:
        """Serialise all findings to *path* as a single JSON document."""
        payload = {
            "schema": "dupez.offsec.findings.v1",
            "generated_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
            "product_version": product_version,
            "summary": self.summary(),
            "findings": [f.to_dict() for f in self.all()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
