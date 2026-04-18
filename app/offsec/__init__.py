"""
DupeZ offensive self-test layer.

Scope
-----
This package is a **defensive self-test**: it exercises the security
posture of the DupeZ process on the **local** machine only, producing
findings in a structured format for the project maintainer to review.
It does not, and must not, target remote hosts, third-party
infrastructure, or any asset the runner doesn't own.

The runner is gated on an explicit environment-variable consent marker
(:data:`OFFSEC_CONSENT_ENV`) that the user must set to a specific
value before any module will execute. No module in this package will
perform any offensive action without that consent.

Organization (loosely mapped to MITRE ATT&CK tactics)
-----------------------------------------------------

    * ``recon``           — TA0043 Reconnaissance (local)
    * ``attack_surface``  — TA0007 Discovery (local pipes, files, ports)
    * ``fuzz_ipc``        — TA0008 Lateral Movement (IPC auth under test)
    * ``findings``        — finding registry + CVSS serialisation
    * ``runner``          — CLI entrypoint + tactic dispatch

Every module routes its findings through
:class:`app.offsec.findings.FindingRegistry`, which produces a JSON
document the :mod:`scripts.report_findings` tool can convert into an
HTML report.
"""

from __future__ import annotations

import os

__all__ = [
    "OFFSEC_CONSENT_ENV",
    "OFFSEC_CONSENT_VALUE",
    "consent_granted",
    "require_consent",
]

OFFSEC_CONSENT_ENV = "DUPEZ_OFFSEC_CONSENT"
OFFSEC_CONSENT_VALUE = "i-own-this-machine-and-accept-local-scope"


class OffsecConsentError(RuntimeError):
    """Raised when an offsec module is invoked without explicit consent."""


def consent_granted() -> bool:
    """Return True when the consent environment variable is set correctly."""
    return os.environ.get(OFFSEC_CONSENT_ENV, "") == OFFSEC_CONSENT_VALUE


def require_consent() -> None:
    """Raise :class:`OffsecConsentError` unless consent is granted.

    Every public entrypoint in an offsec submodule MUST call this as
    its first line. The check is intentionally simple and loud — we
    want to make it obvious when someone is trying to invoke the
    offensive path, and we want the failure message to explain
    exactly what they need to do if they really mean it.
    """
    if not consent_granted():
        raise OffsecConsentError(
            "offsec module refuses to run without explicit consent. "
            f"Set {OFFSEC_CONSENT_ENV}={OFFSEC_CONSENT_VALUE!r} in the "
            "environment ONLY if you are running against your own local "
            "machine and accept the local scope."
        )
