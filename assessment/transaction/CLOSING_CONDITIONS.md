# CLOSING_CONDITIONS

1. Configure and API-verify `main` branch protection or a ruleset that requires pull requests, approving review, up-to-date exact-head checks, and blocks direct push, force push, deletion, and bypass.
2. Configure and API-verify `production-release` protection rules with an independent required reviewer, self-review prevention, and a deployment-branch policy limited to `main`.
3. After both server-side controls are verified, set `DUPEZ_RELEASE_GOVERNANCE_READY` to `protected-main-reviewed-environment`.
4. Produce the exact GPU, Compat, and installer artifacts from protected clean
   `main` under one attested distribution mode: Authenticode-signed by default,
   or the explicitly authorized `-AllowUnsigned` exception with Windows
   publisher-warning disclosure. In either mode, the Ed25519 updater manifest
   and signature sidecars remain mandatory.
5. Complete distribution preflight with all checks passing.
6. Collect frozen runtime evidence for GPU and Compat on CPython 3.13.14 x64.
7. Import passing, exact-commit hardware-smoketest evidence from the canonical
   GitHub Actions workflow and verify its authenticated artifact identity.
8. Record the complete exact-artifact manual walkthrough, including install,
   upgrade, uninstall, lifecycle, safety-stop, recovery, and support paths.
9. Execute draft staging and publication from the protected, reviewed `main`
   release commit with a clean working tree.
