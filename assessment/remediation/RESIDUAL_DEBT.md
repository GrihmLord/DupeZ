# RESIDUAL_DEBT

- Exact-current-tree distribution artifacts, updater manifest/signature
  sidecars, and validation evidence have not been produced. Authenticode
  certificate/host inputs remain external if the standard signed mode is
  selected; the explicitly authorized unsigned exception still requires its
  attestation and publisher-warning disclosure.
- Server-side release governance is not configured: `main` lacks branch
  protection/rulesets and `production-release` lacks protection and
  deployment-branch policy. Workflow-local guards do not close this gap.
