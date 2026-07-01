# DupeZ Documentation Index

Project documentation lives here. Top-level docs (`README.md`, `CHANGELOG.md`, `ROADMAP.md`) stay at the repo root; everything below is supporting material.

## Layout

### `adr/` — Architecture Decision Records

- **ADR-0001-split-elevation-for-gpu-map.md** — Why GPU map + WinDivert need a split-IL process tree. Two-variant build (`DupeZ-GPU.exe` + `DupeZ-Compat.exe`).
- **ADR-0001-QA-matrix.md** — Companion QA matrix for the split-elevation ship-criteria.
- **ADR-0002-key-architectural-decisions.md** — Consolidated v5.5–v5.7 decisions: WiFi peer disruption (§1, current = v5.7.2 model), Ed25519 auto-update (§2), split elevation (§3), local-only telemetry (§4), plugin trust model (§5), fail-closed posture (§6), test policy (§7), feature-creep guard (§8). **Start here.**
- **ADR-0002-map-performance-paths.md** — Map rendering performance paths.

### `release-notes/` — Per-version operator-facing notes

`v5.6.3.md` through `v5.7.7.md` plus older `RELEASE_NOTES_*` and
`DEPLOY_CHECKLIST_*` files. The latest is always `v<current>.md` where
`<current>` matches `app/__version__.py`.

### `audits/` — Deep-audit reports

- **WIFI_DISRUPT_AUDIT_v5.7.4.md** — Audit of `arp_spoof`, `wifi_probe`, `target_profile`, and the `wifi_same_net` end-to-end path. 4 HIGH / 6 MEDIUM / 5 LOW findings, 7 architecture recommendations, 9 test-coverage gaps. Source for hardening tickets after v5.7.4.

Older audit reports (`AUDIT_REPORT_PHASE_C.md`, `AUDIT_v5.7.0.md`) currently live in the docs root for backward link compatibility; future audits land in `audits/`.

### `user_guides/` — End-user how-to docs

- **PRIVACY_FEATURES.md** — IP masking, log retention, opt-in telemetry posture.
- **DEVICE_HEALTH_PROTECTION.md** — Built-in safeguards against bricking targets.
- **ETHERNET_SUPPORT_SUMMARY.md** — Wired-uplink notes (relevant when AP isolation forces self-disrupt fallback).

### `integration/` — Platform integration notes

- **BUILD_SUCCESS_README.md** — Build-pipeline reference.
- **IZURVIVE_INTEGRATION_README.md** — iZurvive embed + ad-blocking layer.

### `reports/` — Historical audit reports (DOCX)

Externally-shared audit deliverables (v4.1.0, v5.3.0, deep-research pass, etc.). Kept as binary DOCX because that's how they were originally shared.

### `archive/` — Quarantined legacy docs

Dated subfolders (e.g. `2026-04-17/`) hold superseded or historically-interesting docs that shouldn't be deleted but shouldn't show up in primary navigation either.

## Standalone docs at this level

- **ROADMAP_v6.md** ? Long-horizon v6.x sketch for trusted-lab diagnostics,
  cross-game profiles, plugin marketplace, mobile companion, privacy lifecycle,
  and performance work. The active short-horizon roadmap lives at
  `../ROADMAP.md`.
- **competitive_audit.md** — Comparison against adjacent tools.
- **AUDIT_REPORT_PHASE_C.md**, **AUDIT_v5.7.0.md** — Historical audits (slated for migration to `audits/` next time they're touched).

Historical DOCX reports are retained as binary artifacts for provenance. The
Markdown README, roadmap, audit, and release-note files are the current
operator-facing documentation source of truth.

## Where things go when you add them

| Adding… | Goes in |
| --- | --- |
| A new architectural decision | `adr/ADR-NNNN-<slug>.md` |
| Per-version release notes | `release-notes/v<version>.md` |
| Deep-audit report | `audits/<slug>_v<version>.md` |
| End-user how-to | `user_guides/<TOPIC>.md` |
| Platform integration write-up | `integration/<SLUG>.md` |
| Anything superseded | `archive/<YYYY-MM-DD>/` |

Top-level project docs (`README.md`, `CHANGELOG.md`, `ROADMAP.md`) stay at the repo root — Markdown viewers and GitHub's repo landing both prefer them there.
