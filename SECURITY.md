# Security Policy

## Supported version

Security fixes are applied to the latest released version and the `main`
branch. Older releases should be upgraded before reporting a suspected issue.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private
network information, or personal data. Use GitHub's private vulnerability
reporting feature for this repository when available. Include:

- the affected version and Windows version;
- the smallest safe reproduction;
- expected and observed behavior;
- whether elevated privileges, plugins, updater artifacts, or local network
  access are involved.

Please remove secrets, account data, public IP addresses, and device identifiers
from reports. The `python -m app.cli support bundle` command creates a redacted
diagnostic artifact suitable for initial triage.

## Scope

Useful reports include privilege-boundary failures, unsafe update or plugin
verification, path traversal, command execution, secret exposure, audit-log
integrity failures, and unintended access outside an explicitly owned local
test network.

Reports seeking to improve game exploitation, anti-cheat evasion, disruption
of third-party devices, credential capture, or attacks against public services
are out of scope.
