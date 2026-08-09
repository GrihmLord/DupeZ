---
name: universal-assurance-orchestrator
description: "Use when running the Universal Software Assurance Application QA/Due-Diligence framework for this repo, especially when asked to follow the PDF plan in full, execute phase-based release assurance, generate Section-16 assessment artifacts, or run blocked release gates for DupeZ v5.8.0 without re-pasting the PDF path."
---

# Universal Assurance Orchestrator (DupeZ)

## Canonical framework source
- Primary document: `C:/Users/Owner/Downloads/Universal_Software_Assurance_Application_QA_Due_Diligence_Orchestrator_v2.pdf`
- Extracted workspace copy: `docs/release-notes/QA_DUE_DILIGENCE_ORCHESTRATOR_v2_extracted.txt`

Always use the extracted copy for deterministic line-referenced execution. If it is missing, regenerate it from the canonical PDF path before continuing.

## Required execution behavior
- Follow phases 0-22 with explicit statuses: `COMPLETE`, `PARTIAL`, `BLOCKED`, `NOT_APPLICABLE`.
- Apply Section 17 integrity rules: no fabricated evidence/results and no over-claiming.
- Ensure Section 18 starting outputs are present before substantive conclusions.
- Keep Section 16 artifact tree under `assessment/` fully populated.
- For blocked release gates, run only the blocked sequence in the order defined by:
  - `scripts/blocked_release_gates_sequence.ps1`
  - `docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md`

## Repo-specific outputs
- Main report: `assessment/FINAL_REPORT.md`
- Roadmap status: `assessment/governance/ROADMAP_STATUS.md`
- Gate matrix: `assessment/technical/RELEASE_GATE_MATRIX.csv`
- Findings: `assessment/findings/FINDINGS.md` and `assessment/findings/findings.json`

## When user asks to "follow the PDF plan"
1. Confirm extracted framework file exists and is current.
2. Execute/update only required phases based on current mandate and available evidence.
3. Run available verifications; label unavailable checks as `BLOCKED`/`PARTIAL` with explicit blockers.
4. Update assessment artifacts and gate matrix with concrete evidence paths and command outcomes.
5. If release gates are blocked by admin/main-clean/signing constraints, switch to the blocked-gates sequence script and continue immediately from the next blocked step.
