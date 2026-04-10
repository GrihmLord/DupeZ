# scripts/

Operational helpers and one-off diagnostics. Not part of the shipped
application — these are developer / support tools.

| File | Purpose |
| --- | --- |
| `fix_webengine.bat` | Repair broken PyQt6 / PyQt6-WebEngine installs when the iZurvive map shows a placeholder. Wipes every PyQt6/Qt6 wheel, clears the pip cache, reinstalls the package set in a single resolver pass, and verifies `QWebEngineView` can actually import before exiting. |
| `diagnose_webengine.py` | Minimal smoke test that bypasses DupeZ entirely and opens iZurvive in a bare `QWebEngineView`. Prints every load event, renderer-process crash, and JS console message. Use when the map fails inside DupeZ to isolate whether the bug is in QtWebEngine itself or in DupeZ's wiring. |

## Usage

Both scripts assume they are run from the DupeZ repo root (so relative
module imports resolve), not from inside `scripts/`.

```powershell
cd C:\path\to\DupeZ

# Repair QtWebEngine install
.\scripts\fix_webengine.bat

# Smoke-test QtWebEngine against iZurvive
python scripts\diagnose_webengine.py
```
