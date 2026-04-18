#!/usr/bin/env python
"""
report_findings.py — render an offsec findings JSON document to HTML.

Produces a single self-contained HTML report (no external CSS/JS, no
CDN references) suitable for emailing or attaching to a security
ticket. The layout is a severity-bucketed table of findings with
inline evidence and remediation.

Usage::

    python scripts/report_findings.py dist/offsec-findings.json
    python scripts/report_findings.py in.json --out report.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Dict, List


_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

_SEVERITY_COLOR = {
    "CRITICAL": "#7f1d1d",
    "HIGH":     "#b45309",
    "MEDIUM":   "#a16207",
    "LOW":      "#365314",
    "INFO":     "#334155",
}

_CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  margin: 0; padding: 24px; color: #0f172a; background: #f8fafc;
}
h1 { margin: 0 0 4px; font-size: 22px; }
.meta { color: #475569; font-size: 13px; margin-bottom: 20px; }
.buckets {
  display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap;
}
.bucket {
  padding: 6px 12px; border-radius: 999px; color: white; font-size: 13px;
  font-weight: 600;
}
.finding {
  background: white; border: 1px solid #e2e8f0; border-radius: 8px;
  padding: 16px 20px; margin-bottom: 12px;
}
.finding h2 { margin: 0 0 4px; font-size: 16px; }
.finding .row {
  font-size: 12px; color: #64748b; margin-bottom: 8px;
}
.finding .sev {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  color: white; font-weight: 600; margin-right: 6px;
}
.finding pre {
  background: #0f172a; color: #e2e8f0; padding: 10px 12px;
  border-radius: 4px; font-size: 12px; overflow-x: auto; margin: 8px 0;
}
.finding .rem {
  background: #ecfeff; border-left: 3px solid #0891b2;
  padding: 8px 12px; margin: 8px 0 0; font-size: 13px; color: #164e63;
}
"""


def render(doc: Dict) -> str:
    findings: List[Dict] = doc.get("findings", [])
    summary = doc.get("summary", {"total": 0, "by_severity": {}})
    by_sev = summary.get("by_severity", {})
    generated = doc.get("generated_at_iso", "")
    product_version = doc.get("product_version", "")
    schema = doc.get("schema", "")

    # Sort findings by severity then by id.
    def key(f):
        sev = f.get("severity", "INFO")
        try:
            order = _SEVERITY_ORDER.index(sev)
        except ValueError:
            order = len(_SEVERITY_ORDER)
        return (order, f.get("id", ""))
    findings = sorted(findings, key=key)

    lines: List[str] = []
    lines.append("<!doctype html><html lang='en'><head>")
    lines.append("<meta charset='utf-8'>")
    lines.append(f"<title>DupeZ offsec report — {html.escape(product_version)}</title>")
    lines.append(f"<style>{_CSS}</style></head><body>")
    lines.append(f"<h1>DupeZ offsec self-test report</h1>")
    lines.append(
        "<div class='meta'>"
        f"Product version: <b>{html.escape(product_version or '(unset)')}</b> "
        f"&nbsp;·&nbsp; generated {html.escape(generated)} "
        f"&nbsp;·&nbsp; schema <code>{html.escape(schema)}</code>"
        "</div>"
    )

    lines.append("<div class='buckets'>")
    lines.append(
        f"<div class='bucket' style='background:#334155'>Total: {int(summary.get('total', 0))}</div>"
    )
    for sev in _SEVERITY_ORDER:
        count = int(by_sev.get(sev, 0))
        if count == 0:
            continue
        lines.append(
            f"<div class='bucket' style='background:{_SEVERITY_COLOR[sev]}'>"
            f"{sev}: {count}</div>"
        )
    lines.append("</div>")

    for f in findings:
        sev = f.get("severity", "INFO")
        color = _SEVERITY_COLOR.get(sev, "#334155")
        lines.append("<div class='finding'>")
        lines.append(
            f"<h2><span class='sev' style='background:{color}'>{sev}</span>"
            f"{html.escape(f.get('title', '(no title)'))}</h2>"
        )
        row_bits: List[str] = [f"ID: <b>{html.escape(f.get('id', ''))}</b>"]
        if f.get("cvss_base"):
            row_bits.append(f"CVSS {f['cvss_base']}")
        if f.get("cvss_vector"):
            row_bits.append(html.escape(f["cvss_vector"]))
        if f.get("attack_technique"):
            row_bits.append(f"ATT&CK {html.escape(f['attack_technique'])}")
        if f.get("discovered_at_iso"):
            row_bits.append(html.escape(f["discovered_at_iso"]))
        lines.append(f"<div class='row'>{' &nbsp;·&nbsp; '.join(row_bits)}</div>")
        lines.append(
            f"<div>{html.escape(f.get('description', ''))}</div>"
        )
        ev = f.get("evidence")
        if ev:
            ev_json = json.dumps(ev, indent=2, ensure_ascii=False, sort_keys=False)
            lines.append(f"<pre>{html.escape(ev_json)}</pre>")
        rem = f.get("remediation")
        if rem:
            lines.append(f"<div class='rem'><b>Remediation.</b> {html.escape(rem)}</div>")
        lines.append("</div>")

    lines.append("</body></html>")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", type=Path, help="findings JSON (from app.offsec.runner)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output HTML path (default: input with .html suffix)")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        doc = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 1

    out = args.out or args.input.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(doc), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
