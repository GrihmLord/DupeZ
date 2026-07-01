#!/usr/bin/env python3
# app/gui/panels/help_panel.py — DupeZ Help & Getting Started Guide
"""
Comprehensive help panel for new users.

Explains every feature of DupeZ in plain language with step-by-step
instructions, organized into collapsible sections. Designed so someone
who has never used a network tool can understand exactly what to do.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

__all__ = ["HelpPanel"]

# ── Theme tokens (match dark.qss / dashboard) ─────────────────────
_BG           = "#050810"
_SURFACE      = "rgba(10, 15, 26, 0.55)"
_BORDER       = "rgba(30, 41, 59, 0.45)"
_CYAN         = "#00f0ff"
_CYAN_DIM     = "rgba(0, 240, 255, 0.12)"
_TEXT          = "#e2e8f0"
_TEXT_MUTED    = "#94a3b8"
_TEXT_DIM      = "#64748b"
_AMBER        = "#fbbf24"
_GREEN        = "#00ff88"
_RED          = "#ff6b6b"
_PURPLE       = "#a78bfa"

# ── Stylesheet fragments ──────────────────────────────────────────
_SCROLL_QSS = """
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: rgba(15, 23, 42, 0.3);
    width: 6px;
    border-radius: 3px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 240, 255, 0.15);
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 240, 255, 0.3);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

_SECTION_HEADER_QSS = f"""
QPushButton {{
    background: {_SURFACE};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    color: {_CYAN};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    text-align: left;
    padding: 12px 16px;
}}
QPushButton:hover {{
    border-color: rgba(0, 240, 255, 0.3);
    background: rgba(10, 15, 26, 0.7);
}}
"""

_BODY_QSS = f"""
QLabel {{
    color: {_TEXT};
    font-size: 12px;
    line-height: 1.6;
    padding: 0;
}}
"""


# ── Collapsible Section Widget ────────────────────────────────────

class _CollapsibleSection(QWidget):
    """A header button that expands/collapses body content."""

    def __init__(self, title: str, body_widget: QWidget, parent=None,
                 start_open: bool = False) -> None:
        super().__init__(parent)
        self._expanded = start_open

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QPushButton(f"  {'▼' if start_open else '▶'}   {title}")
        self._header.setStyleSheet(_SECTION_HEADER_QSS)
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._header.setFixedHeight(44)
        self._header.setAccessibleName(f"{title} help section")
        self._header.setAccessibleDescription(
            "Expand or collapse this help section"
        )
        self._header.clicked.connect(self._toggle)
        self._title = title
        layout.addWidget(self._header)

        # Body
        self._body = body_widget
        self._body.setVisible(start_open)
        layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        arrow = "▼" if self._expanded else "▶"
        self._header.setText(f"  {arrow}   {self._title}")
        self._body.setVisible(self._expanded)


# ── Help Content Builder ──────────────────────────────────────────

def _styled_body(html: str) -> QWidget:
    """Wrap HTML text in a styled QLabel inside a container."""
    container = QWidget()
    container.setStyleSheet("background: rgba(5, 8, 16, 0.4); border-radius: 6px;")
    lay = QVBoxLayout(container)
    lay.setContentsMargins(16, 12, 16, 14)
    lbl = QLabel(html)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(_BODY_QSS)
    lbl.setOpenExternalLinks(True)
    lay.addWidget(lbl)
    return container


def _tip_label(text: str) -> QLabel:
    """Small amber tip label."""
    lbl = QLabel(f"💡 {text}")
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {_AMBER}; font-size: 11px; padding: 6px 12px;")
    return lbl


# ── Section content ───────────────────────────────────────────────

_SECTIONS: list[tuple[str, str, bool]] = [

    ("WELCOME — WHAT IS DUPEZ?", f"""
<p style='color:{_TEXT}; font-size:13px;'>
<b style='color:{_CYAN};'>DupeZ</b> is a per-device network disruption toolkit
built for gamers. It intercepts packets between your console or PC and the game
server, giving you fine-grained control over lag, packet loss, throttling, and
more — across <b>DayZ</b>, <b>GTA</b>, <b>Fortnite</b>,
and any other game on <b>PS5</b>, <b>Xbox</b>, or <b>PC</b>.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
Under the hood DupeZ uses <b>WinDivert</b>, a kernel-level packet interception
driver. The GUI variant (DupeZ-GPU) runs the interface at normal privileges for
smooth map rendering while an elevated helper process handles the driver.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>⚠ Important:</b> DupeZ requires
<b>Administrator</b> privileges to load the WinDivert driver. If you installed
with the GPU build, admin elevation is handled automatically. If you see
"Engine: UNAVAILABLE", right-click the exe and run as admin.</p>
""", True),

    ("GETTING STARTED — FIRST-TIME SETUP", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Six steps to your first disruption:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>1.</b> Launch DupeZ. The GPU build auto-elevates
via an elevated helper; for the Compat build, right-click →
<b>Run as administrator</b>. Status bar should read
<b style='color:{_GREEN};'>Engine: READY</b>.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>2.</b> You land on the <b>Clumsy Control</b> tab
(🎯 in the sidebar). The left panel shows devices on your network — run a
<b>Scan</b> to discover them. Vendor column uses the IEEE OUI database,
so PS5 / Xbox / Switch / Apple devices auto-label.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>3.</b> Select a <b>Preset</b> from the dropdown on
the right panel. Available presets:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_GREEN};'>Red Disconnect</b> — The full-isolation diagnostic preset.
Full isolation diagnostic: 100% drop, 3s lag, zero bandwidth, throttle,
plus the stateful DISCONNECT timed-cut module. Use only in an authorized
lab or on equipment you control.</li>
<li><b>Lag</b> — Heavy sustained lag + drop. Tune with the sliders after
selecting (Light ~800ms/60% · Max ~5000ms/100%)</li>
<li><b>Custom</b> — Set your own modules and parameters manually</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>4.</b> Click a device in the table to target it, then
hit <b>DISRUPT</b>. DupeZ starts intercepting packets for that device only.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>5.</b> Hit <b>STOP</b> when done — your connection
restores instantly. Use <b>STOP ALL</b> to kill every active disruption at
once. For a fixed-length cut, set <b>Duration</b> in the Scheduler row
and click <b>TIMED DISRUPT</b> instead of DISRUPT — it auto-stops.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>6.</b> Watch the <b>LIVE STATS</b> card for the
per-device cut-state LED. Red = <b style='color:{_RED};'>severed</b>
(connection fully isolated). Amber = partial cut.
Green = cut hasn't landed yet.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_CYAN};'>Quick Start — Authorized Lab Diagnostic:</b></p>
<ol style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>Scan → select your PC or console</li>
<li>Preset → <b>Red Disconnect</b></li>
<li>Start a private/local test session that you own or administer</li>
<li>Hit <b>DISRUPT</b> to isolate the connection, or use
<b>TIMED DISRUPT</b> for a fixed diagnostic window</li>
<li>Stop the run and export a scenario report for review</li>
</ol>

""", False),

    ("🎯 CLUMSY CONTROL — THE MAIN VIEW", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The core of DupeZ. Two-panel layout: device table on the left, disruption
controls on the right.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Device Table (left)</b> — Discovered devices on
your LAN. Select a row to target that device. DupeZ filters packets by the
device's IP so only game traffic is affected.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Presets (right)</b> — Pre-built disruption
profiles. Pick one and the modules + sliders auto-configure:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_GREEN};'>Red Disconnect</b> — The full-isolation diagnostic preset.
Enables lag, drop, bandwidth, throttle, and the stateful DISCONNECT
timed-cut module in one click for authorized isolation diagnostics.</li>
<li><b>Lag</b> — Sustained lag + drop. Tune with sliders after selecting</li>
<li><b>Custom</b> — Set your own parameters manually</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Platform card</b> — A single <b>PC LOCAL</b>
toggle. Leave it <i>unchecked</i> for a PS5, Xbox, or remote PC — DupeZ
uses the NETWORK_FORWARD layer and targets the device's IP. Check it when
DayZ runs on <i>this</i> machine: DupeZ switches to the NETWORK layer and
the target becomes the game server IP instead.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Disruption Modules</b> — Each module manipulates
packets differently:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_GREEN};'>Lag</b> — Adds delay (ms) to every packet.
100–200ms is noticeable; 500ms+ is extreme.</li>
<li><b style='color:{_GREEN};'>Drop</b> — Randomly discards a % of packets.
10–30% is realistic; 50%+ causes heavy desync.</li>
<li><b style='color:{_GREEN};'>Disconnect</b> — The stateful timed cut
(arm → cut → release). Use it for bounded, repeatable lab diagnostics.</li>
<li><b style='color:{_GREEN};'>Bandwidth</b> — Caps throughput (KB/s) with
an optional queue. 0 KB/s is a full stall.</li>
<li><b style='color:{_GREEN};'>Throttle</b> — Queues packets and releases
them in bursts, creating "choppy" gameplay.</li>
<li><b style='color:{_GREEN};'>Duplicate</b> — Sends packet copies to test
how private lab traffic handles duplicate delivery.</li>
<li><b style='color:{_GREEN};'>Out of Order</b> — Shuffles packet sequence
numbers, confusing netcode.</li>
<li><b style='color:{_GREEN};'>Tamper</b> — Flips random bits in packet
data. Use sparingly — limited effect against DayZ.</li>
<li><b style='color:{_GREEN};'>TCP RST</b> — Injects TCP reset flags.
Aggressive — it will kick you too.</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Direction</b> — Choose Inbound, Outbound, or both.
Inbound affects data coming <i>from</i> the server; outbound affects data
going <i>to</i> the server.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Scheduler &amp; Macros</b> — Sits inline directly
under DISRUPT / STOP / STOP ALL (no separate card). Set <b>Duration</b>
(0.5s resolution) and an optional <b>Delay</b>, then use:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_PURPLE};'>TIMED DISRUPT</b> — Runs for the set
duration, then auto-stops. Ideal for reproducible authorized diagnostics.</li>
<li><b style='color:{_PURPLE};'>RUN MACRO</b> — Chains configured
disruption steps in sequence (recorded or scripted).</li>
<li><b style='color:{_AMBER};'>STOP MACRO</b> — Cancels an in-flight
macro without touching other active disruptions.</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>SMART MODE</b> — Lives in the <b>AI / Smart Ops</b>
tab of the Network Tools view, not in this view. It is a tri-state toggle:
<b>off</b>, <b>learn</b>, or <b>assist</b>. In learn/assist mode DupeZ
consults the learning loop (past labeled episodes + cut-effectiveness
stats) and picks the preset / direction / duration most likely to sever
the current target class. After 5 labeled episodes for a (profile, goal)
bucket it will <i>auto-switch presets</i> if the current one can't sever —
no more silently retrying a preset that doesn't fit the target.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>LIVE STATS (collapsible card below)</b> — Each
targeted device shows a coloured cut-state LED: grey (unknown), green
(connected), amber (degraded), red (severed). Hover the stats banner for
per-device tooltips driven by the A2S cut verifier.</p>
""", False),

    ("🗺 IZURVIVE MAP TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
An interactive <b>iZurvive</b> map embedded directly in DupeZ so you can
plan routes without switching windows.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Features:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>All official DayZ maps — Chernarus+, Livonia, Namalsk, Sakhal,
Deer Isle, Esseker, Takistan — with pan/zoom</li>
<li>Satellite and Topographic layer toggle</li>
<li>GPU-accelerated rendering when a capable GPU is detected</li>
<li>Automatic renderer tier detection — GPU (ANGLE/D3D11), SwiftShader, or CPU
raster based on your hardware</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Map Renderer Override:</b> Go to <b>Settings →
Interface → Map Renderer</b> to force a specific renderer (GPU, SwiftShader,
or Software). The status bar shows the active tier: <b style='color:{_GREEN};'>
GPU</b>, <b style='color:{_AMBER};'>SW-GL</b>, or <b style='color:#ff4444;'>
CPU</b>. Changing the renderer requires an app restart (DupeZ will prompt
you automatically).</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Map slow or software-rendered?</b> The GPU build
(DupeZ-GPU.exe) runs at Medium IL and can use hardware raster. The Compat
build runs elevated, which forces CPU raster. Try setting the renderer to
<b>gpu</b> in Settings if auto-detection picked a lower tier.</p>
""", False),

    ("👤 ACCOUNT TRACKER TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Manage multiple DayZ characters and alt accounts in one place.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Features:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Add / Edit / Duplicate / Delete</b> — Full CRUD with a notes field,
custom status and station values, and multi-select support</li>
<li><b>Status tracking</b> — Ready, Dead, Storage, Blood Infection, or
Offline with colour-coded rows. Type custom statuses if needed</li>
<li><b>Quick-filter chips</b> — One-click status chips above the table
to instantly show only Ready, Dead, Storage, etc.</li>
<li><b>Right-click context menu</b> — Edit, duplicate, change status, or
delete directly from the table. Works on multi-selected rows</li>
<li><b>Row numbering</b> — Each row has a # column so you can reference
accounts by number</li>
<li><b>Notes field</b> — Private per-account notes for reminders, coords,
or anything else</li>
<li><b>Import / Export</b> — Upload from XLSX or CSV, export to either
format. Auto-detects column headers from your spreadsheet</li>
<li><b>Starter template</b> — First launch populates example accounts.
Hit the Template button to reload them anytime</li>
<li><b>Search + Filter</b> — Combine the search bar with status chips to
drill down quickly</li>
<li><b>Bulk Operations</b> — Scope by all, selected, or status. Change
status, set location, clear notes, delete, or export matching</li>
<li><b>Last modified</b> — Select an account to see when it was last
changed in the status bar</li>
</ul>
""", False),

    ("🔄 TIMED DISCONNECT WORKFLOW — AUTHORIZED DIAGNOSTICS", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The timed disconnect workflow is for reproducing connection-loss scenarios
in a private or otherwise authorized lab. DupeZ does not modify the game;
it creates a bounded, visible network impairment and records enough context
to explain what happened afterward.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>The full-isolation preset is Red Disconnect.</b>
Selecting it arms the full module stack — 100% drop, 3s lag, zero bandwidth,
throttle — plus the stateful <b>DISCONNECT</b> module, which is the timed
cut used for repeatable diagnostics. One preset, one DISRUPT click.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>The DISCONNECT module — arm → cut → release.</b>
It exposes three sliders in the MODULES card:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Chance %</b> — How aggressively packets are dropped during the cut.
Leave at 100 for a clean isolation test</li>
<li><b>Arm Delay (ms)</b> — Wait time after you hit DISRUPT before the cut
lands. Use it to line the cut up with an in-game action</li>
<li><b>Duration (ms)</b> — How long the cut is held before it auto-releases.
Leave at <b>0</b> to hold the cut until you hit STOP manually</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Note:</b> Earlier builds exposed multiple
legacy timing modes. They are now consolidated into a single timed cut you
control directly with the Arm Delay / Duration sliders or the
<b>TIMED DISRUPT</b> button.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Basic lab run:</b></p>
<ol style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>Scan → select your PC or console in the device table</li>
<li>Preset → <b>Red Disconnect</b></li>
<li>Hit <b>DISRUPT</b> to hold the cut, or set a Duration and hit
<b>TIMED DISRUPT</b> for a fixed window</li>
<li>Observe severed/partial/healthy status in Live Stats</li>
<li>Stop the run and export a scenario report</li>
</ol>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Short cut:</b> Set <b>Duration</b> to
1000-3000ms and hit <b>TIMED DISRUPT</b> to verify that the connection
recovers cleanly after a bounded impairment.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Reading the cut:</b> Watch the per-device LED in
the LIVE STATS card. Red (<b style='color:{_RED};'>severed</b>) means the cut
landed and the connection is fully isolated. Amber is a partial cut — the sever has
not fully taken yet.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Tip:</b> Use <b>TIMED DISRUPT</b> for
reproducible windows — it auto-stops at the Duration you set, so every
diagnostic run uses an identical cut length.</p>
""", False),

    ("🛡 LOCAL FORWARDING & A2S CUT VERIFIER (v5.6.0)", f"""
<p style='color:{_TEXT}; font-size:12px;'>
When the target is on the <b>same WiFi network</b> as you (not behind a
hotspot), DupeZ can use a local ARP-forwarding diagnostic path instead of
the forward-path WinDivert layer. Use this only on networks you own or
administer.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>What changed in v5.6:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Forwarding-path check</b> — Confirms whether the local network permits
the diagnostic forwarding path.</li>
<li><b>Compatibility check</b> — Identifies router/client behavior that may
prevent local-path diagnostics.</li>
<li><b>Safety check</b> — Falls back to direct self-diagnostics when the
local path is not appropriate.</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>A2S cut verifier:</b> For Source-engine servers
(DayZ, every Source-derived title), DupeZ polls the query port once per
second while a cut is active. It captures a <b>baseline player count</b> on
the first reachable response, then watches for a drop. When the count goes
down, the session appears severed — the cut landed.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Cut state progression</b> (visible in session logs
as <code>cut_verified</code> events):</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_TEXT_DIM};'>unknown</b> — probe not reachable yet, or
no baseline captured</li>
<li><b style='color:{_GREEN};'>connected</b> — server reachable, player count
matches baseline (cut hasn't landed)</li>
<li><b style='color:{_AMBER};'>degraded</b> — ping failing but player count
intact (partial cut, session still alive server-side)</li>
<li><b style='color:{_RED};'>severed</b> — player count dropped below
baseline (session appears severed)</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Learning loop:</b> Every session's peak
<code>max_cut_state</code> is written to the episode recorder. SMART DISRUPT
now has two aggregations: <b>recommend()</b> (did the configured outcome occur?) and
<b>cut_effectiveness()</b> (did the cut even fire?). After 5 labeled episodes
per (profile, goal) bucket, the auto-tuner uses this to switch presets when
the current one fails to sever — instead of silently retrying a preset that
can't hit this target class.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Tip:</b> If the Device Table vendor column shows
<b>Unknown</b> for a device with a real MAC, scapy's MANUFDB isn't loading —
check logs for a scapy import error. v5.6 chains the full ~35k-entry IEEE
OUI database as a fallback to the 60-entry curated gaming table.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_GREEN};'>✓ WiFi disruption (v5.7.2):</b> Pick a device from
the network scan — an Xbox, a PS5, another PC — hit DISRUPT, and DupeZ
disrupts <b>that device</b>. Same-network targets route through a local
forwarding diagnostic path on the FORWARD layer: the target's traffic is redirected through your
machine, then the disruption modules (drop, lag, throttle, disconnect)
act on it.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>How it works:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Local forwarding + FORWARD layer</b> — DupeZ verifies that the
authorized test target's traffic can flow through your PC. WinDivert's
FORWARD layer intercepts it and the modules disrupt it. Requires Npcap installed; if
it's missing you get a Partial Failure dialog with install guidance
(no silent no-ops).</li>
<li><b>Isolation watchdog</b> — Some consumer APs (Eero, Google Nest,
many ISP gateways, guest WiFi) enable client isolation, which drops
station-to-station frames so the local path can't land. DupeZ watches the
forwarded-packet counter for 8 seconds; if the local-path setup ran but
nothing comes back, it auto-falls-back to <b>self-disrupt mode</b> and
shows a toast explaining the switch.</li>
<li><b>Self-disrupt fallback</b> — When isolation is detected, DupeZ
disrupts your own machine's traffic to/from the target instead. Useful
when the target is something you connect to (a shared game server) but
it cannot affect another device's independent traffic. This is the
honest degraded mode, not the default.</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>If a cut has no effect:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>Confirm Npcap is installed (Tools → Diagnostics will check).</li>
<li>If you see the "AP isolation detected" toast, your router is
dropping the spoof. Disable "AP Isolation" / "Client Isolation" in the
router's WiFi settings if you own it, or connect the operator PC by
Ethernet — a wired uplink is not subject to WiFi client isolation.</li>
<li>To force self-disrupt mode regardless (lag only your own traffic),
pass <code>params["_force_self_disrupt"] = True</code>.</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:4px;'>
History: v5.6.5 briefly made self-disrupt the default — that broke
disrupting peer devices like Xbox/PS5 and was reverted in v5.7.2.
local forwarding is the default again; self-disrupt is the watchdog's
automatic fallback when the AP won't cooperate.</p>
""", False),

    ("📡 NETWORK TOOLS TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
A suite of diagnostic and monitoring tools for your connection:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Traffic Monitor</b> — Real-time bandwidth usage per
network interface. Spot bandwidth hogs at a glance.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Latency Overlay</b> — Continuous ping/jitter
measurement against any target IP. Supports a floating overlay you can keep
visible while gaming.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Port Scanner</b> — TCP port scan against a target
IP. Verify game server ports are open and reachable before you play.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Connection Mapper</b> — Live view of every active
network connection on your machine — see exactly which IPs your game is
talking to and on which ports.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>AI / Smart Ops</b> — Smart Mode (the tri-state
auto-tuner), ML capture, and the Voice control panel all live in this
tab.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>GPC / Cronus Zen</b> — Appears when a CronusZEN
device is detected — see the GPC / Cronus Zen section below.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:6px;'>
A <b>LAN Cut</b> tab may also be present depending on your build.</p>
""", False),

    ("⚙ SETTINGS & THEMES", f"""
<p style='color:{_TEXT}; font-size:12px;'>
<b>Tools → Settings</b> (or <b>Ctrl+,</b>) opens the full settings panel.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Themes</b> — Four built-in looks:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_CYAN};'>Dark</b> — Cyber-HUD glassmorphism (default)</li>
<li><b>Light</b> — Clean white, blue accents</li>
<li><b style='color:{_GREEN};'>Hacker</b> — Phosphor-green terminal</li>
<li><b style='color:{_PURPLE};'>Rainbow</b> — Animated colour cycling</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
Themes apply live — switch from the combo and see the change instantly. The
sidebar buttons stay fixed at 40×40 regardless of theme.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Map Renderer</b> — Under the <b>Interface</b> tab,
choose the map rendering backend: <b>Auto</b> (recommended — detects your GPU
automatically), <b>GPU</b> (force hardware raster via ANGLE/D3D11),
<b>SwiftShader</b> (software OpenGL), or <b>Software</b> (pure CPU, no GPU
processes). Changing this restarts DupeZ so the new renderer takes effect at
Qt boot.</p>


<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Other settings:</b> scan behaviour, thread limits,
traffic thresholds, notification preferences, compact view, debug mode, and
more. Every control saves to disk and persists across sessions.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Updates</b> — <b>Help → Check for Updates</b>
checks GitHub for the latest release and walks you through the upgrade.</p>
""", False),

    ("🎙 VOICE CONTROL (OPTIONAL)", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Control DupeZ hands-free with voice commands. Useful when you're mid-game and
can't alt-tab.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Enable:</b> Open the <b>Network Tools</b> view and
go to the <b>AI / Smart Ops</b> tab — the Voice panel is there. Select your
microphone and toggle voice control on.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Example commands:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>"Start disruption" / "Stop" / "Stop all"</li>
<li>"Set lag to 200" — adjusts the Lag module to 200ms</li>
<li>"Enable drop" / "Disable throttle"</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Requires:</b> <code>pip install sounddevice
whisper</code> (not bundled in the default build).</p>
""", False),

    ("🎮 GPC / CRONUS ZEN (OPTIONAL)", f"""
<p style='color:{_TEXT}; font-size:12px;'>
DupeZ can connect to a <b>CronusZEN</b> device for accessibility helpers
and diagnostic markers alongside authorized network diagnostics.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Setup:</b> Plug in CronusZEN via USB. DupeZ
auto-detects it. The <b>GPC / Cronus Zen</b> tab appears in the Network
Tools view when the hardware is found.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Requires:</b> CronusZEN hardware + USB.
<code>pip install pyserial</code></p>
""", False),

    ("❓ TROUBLESHOOTING", f"""
<p style='color:{_TEXT}; font-size:12px;'>
<b style='color:{_RED};'>"Engine: UNAVAILABLE (no admin)"</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ The WinDivert driver needs elevation. If you're running the GPU build, the
helper process should auto-elevate — accept the UAC prompt. If you're on the
Compat build, right-click → Run as administrator.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Map is slow / software-rendered</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ You're likely running the Compat build (elevated), which forces QWebEngine
into software rasterization. Switch to the GPU build (DupeZ-GPU.exe) — it
runs the GUI at normal privileges so your GPU handles rendering.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>"WinDivert.dll missing"</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Verify <code>WinDivert.dll</code> and <code>WinDivert64.sys</code> are in
<code>app/firewall</code>. If Defender quarantined them, inspect Protection
History for the exact detection, verify the published hashes, and reinstall
from a signed build. Avoid broad antivirus exclusions.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>"Failed to extract" on launch</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Ensure at least 500 MB of free disk space, rebuild without UPX packing,
and prefer the signed installer over a raw portable exe. If Defender blocks
the artifact, inspect Protection History and verify release hashes before
running it.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>SmartScreen blocks the installer</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Do not override SmartScreen for an untrusted installer. Verify the release
signature/hash from the official release page, or use a signed build.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Disruption has no effect in game</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Make sure you selected a target device, at least one module is enabled with
a non-zero value, and the status bar shows <b>"Engine: READY"</b>. Verify
the correct direction (inbound/outbound/both) is selected.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Game disconnects immediately</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Values are too aggressive. Start with Drop at 10–15% and Lag under 300ms.
Some games have strict tolerance for packet
anomalies.</p>
""", False),

    ("⌨ KEYBOARD SHORTCUTS", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Quick reference:</p>

<table style='color:{_TEXT_MUTED}; font-size:12px; margin-top:6px;' cellpadding='4'>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+S</td>
    <td>Scan Network</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+D</td>
    <td>Stop All Disruptions</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Alt+X</td>
    <td>Kill Switch — panic-stop every disruption</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+E</td>
    <td>Export Data</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Shift+E</td>
    <td>Export active scenario report</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+,</td>
    <td>Open Settings</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Shift+P</td>
    <td>Custom Preset Editor</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>F2</td>
    <td>Diagnostics</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+F2</td>
    <td>Network Health summary</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+1</td>
    <td>Switch to Clumsy Control view</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+2</td>
    <td>Switch to iZurvive Map view</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+3</td>
    <td>Switch to Account Tracker view</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+4</td>
    <td>Switch to Network Tools view</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Alt+A</td>
    <td>Next tracked account</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Alt+Shift+A</td>
    <td>Previous tracked account</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Shift+D</td>
    <td>Toggle window (tray mode)</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>F1</td>
    <td>Show this hotkey reference</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Q</td>
    <td>Quit DupeZ</td></tr>
</table>

<p style='color:{_TEXT_MUTED}; font-size:11px; margin-top:8px;'>
The same list is available in-app at any time via <b>Help → Hotkeys</b>
(F1), generated live from the menu so it always matches.</p>
""", False),

]


# ── Main Help Panel Widget ────────────────────────────────────────

class HelpPanel(QWidget):
    """Scrollable help panel with collapsible sections for new users."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("help_panel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(_SCROLL_QSS)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(24, 20, 24, 24)
        inner_lay.setSpacing(12)

        # Title header
        title = QLabel("GETTING STARTED")
        title.setStyleSheet(
            f"color: {_CYAN}; font-size: 18px; font-weight: 800; "
            f"letter-spacing: 3px; padding-bottom: 4px;"
        )
        inner_lay.addWidget(title)

        subtitle = QLabel(
            "Everything you need to know about DupeZ — step by step, from zero."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px; padding-bottom: 12px;")
        inner_lay.addWidget(subtitle)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background: {_BORDER}; max-height: 1px; margin-bottom: 4px;")
        inner_lay.addWidget(divider)

        # Build collapsible sections
        for idx, (section_title, html, start_open) in enumerate(_SECTIONS):
            section = _CollapsibleSection(
                section_title,
                _styled_body(html),
                start_open=start_open,
            )
            inner_lay.addWidget(section)

        # Bottom spacer
        inner_lay.addStretch()

        # Footer
        footer = QLabel(
            f"<span style='color:{_TEXT_DIM}; font-size:11px;'>"
            f"DupeZ — Built for gamers. Use responsibly.</span>"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner_lay.addWidget(footer)

        scroll.setWidget(inner)
        root.addWidget(scroll)
