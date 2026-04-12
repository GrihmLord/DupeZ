# DupeZ v5.4.0 — Account Tracker Overhaul + UI Polish + Bug Fixes

Feature release focused on the **Account Tracker**, theme stability, and overall UI polish. The tracker is now a full-featured multi-account management tool. Six bugs from v5.3.0 are fixed, and the Help panel and About dialog have been rewritten.

---

## Highlights

### Account Tracker Overhaul
- **Notes field** — New per-account column for private reminders, coordinates, or anything else. Stored, exported, and imported alongside all other fields.
- **Multi-select** — Ctrl+click and Shift+click to select multiple rows. Delete and status changes work across the selection.
- **Right-click context menu** — Edit, Duplicate, Set Status (submenu), and Delete directly from the table. Works on single or multi-selected rows.
- **Quick-filter status chips** — One-click toggle buttons above the table to filter by Ready, Dead, Storage, Blood Infection, or Offline. Combines with the search bar for compound filtering.
- **Duplicate account** — Clone any account with auto-incrementing "(copy)" suffix.
- **Row numbering** — `#` column for easy reference.
- **Last modified display** — Select an account to see when it was last changed.
- **Editable dropdowns** — Status and Station combos accept custom values beyond the preset list.
- **Upgraded bulk operations** — Scope by All / Selected / Filtered-by-Status. Operations: Change Status, Set Location, Clear Notes, Delete, Export Matching.
- **Export subset** — Bulk ops can export only matching accounts to XLSX or CSV.

### UI Polish
- **About dialog rewritten.** Broader tagline (no longer DayZ-specific), dynamic ARCH info row showing Split vs In-process mode, condensed credits, "View on GitHub" + "Close" button pair, subtle cyan separators.
- **Help panel rewritten.** All 11 sections updated with accurate content matching the actual codebase — keyboard shortcuts, troubleshooting messages, feature descriptions.
- **Account dialog styled.** Dark-themed modal with better placeholder text and multi-line Notes input.
- **Device panel splitter fix.** Left and right panels now have minimum widths (320px / 300px) so the splitter can't crush either side into an unreadable sliver.

### Bug Fixes
- **"Engine unavailable no admin" status bar message.** `_BUILD_DEFAULT_ARCH` was `'inproc'` in the GPU variant; changed to `'split'`.
- **Map slow despite GPU.** Same root cause — split arch wasn't defaulting correctly. Added GPU auto-detect fallback in `get_arch()`.
- **Theme switching breaks sidebar button layout.** App-level `QPushButton` stylesheet selectors were overriding widget-level inline styles. Fixed with `#nav_btn` object name and explicit re-application after theme change.
- **Rainbow theme doesn't animate.** `apply_theme("rainbow")` loaded the static QSS but never started the animation timer. Now auto-starts.
- **Overlapping sections in Clumsy Control.** Increased section spacing and added content margins.
- **Account Tracker: duplicate imports, signal stacking, reference-sharing mutation.** Three separate bugs causing double entries, exponentially increasing callbacks, and cross-list mutations. All fixed.

---

## Upgrade Notes

- **No settings file migration required.** `%APPDATA%\DupeZ` schema is unchanged from v5.3.0.
- Existing accounts without a `notes` field are automatically backfilled with an empty string on load.
- **In-place upgrade from v5.3.0 works.** Settings and saved accounts are preserved.

---

## Downloads

- **`DupeZ-GPU.exe`** — recommended single-binary download
- **`DupeZ-Compat.exe`** — fallback single-binary download
- **`DupeZ_v5.4.0_Setup.exe`** — Windows installer (bundles both variants, Add/Remove Programs integration, Start Menu shortcuts)

---

Full change history: [`CHANGELOG.md`](https://github.com/GrihmLord/DupeZ/blob/v5.4.0/CHANGELOG.md)

Got a feature request or bug report? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
