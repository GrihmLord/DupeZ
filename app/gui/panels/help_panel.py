#!/usr/bin/env python3
# app/gui/panels/help_panel.py — DupeZ Help & Getting Started Guide
"""
Comprehensive help panel for new users.

Explains every feature of DupeZ in plain language with step-by-step
instructions, organized into collapsible sections. Designed so someone
who has never used a network tool can understand exactly what to do.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QCursor, QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
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
_SCROLL_QSS = f"""
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: rgba(15, 23, 42, 0.3);
    width: 6px;
    border-radius: 3px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0, 240, 255, 0.15);
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(0, 240, 255, 0.3);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
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
    container.setStyleSheet(f"background: rgba(5, 8, 16, 0.4); border-radius: 6px;")
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
more — across <b>DayZ</b>, <b>GTA</b>, <b>Fortnite</b>, and any other game
on <b>PS5</b>, <b>Xbox</b>, or <b>PC</b>.</p>

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
Five steps to your first disruption:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>1.</b> Launch DupeZ. The GPU build auto-elevates;
for the Compat build, right-click → <b>Run as administrator</b>.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>2.</b> You land on the <b>Clumsy Control</b> tab
(🎯 in the sidebar). The left panel shows devices on your network — run a
<b>Scan</b> to discover them.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>3.</b> Select a <b>Preset</b> from the dropdown on
the right panel (e.g. "Red Disconnect" for maximum effect, or "Mild Lag" for
subtle testing). Presets auto-configure the disruption modules and values.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>4.</b> Click a device in the table to target it, then
hit <b>DISRUPT</b>. DupeZ starts intercepting packets for that device only.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>5.</b> Hit <b>STOP</b> when done — your connection
restores instantly. Use <b>STOP ALL</b> to kill every active disruption at
once.</p>
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
profiles. Pick one and the modules + sliders auto-configure. You can also save
and load your own custom profiles.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Disruption Modules</b> — Each module manipulates
packets differently:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_GREEN};'>Lag</b> — Adds delay (ms) to every packet.
100–200ms is noticeable; 500ms+ is extreme.</li>
<li><b style='color:{_GREEN};'>Drop</b> — Randomly discards a % of packets.
10–30% is realistic; 50%+ causes heavy desync.</li>
<li><b style='color:{_GREEN};'>Throttle</b> — Queues packets and releases
them in bursts, creating "choppy" gameplay.</li>
<li><b style='color:{_GREEN};'>Duplicate</b> — Sends copies of packets,
causing potential desyncs.</li>
<li><b style='color:{_GREEN};'>Out of Order</b> — Shuffles packet sequence
numbers, confusing netcode.</li>
<li><b style='color:{_GREEN};'>Tamper</b> — Flips random bits in packet
data. Use sparingly — high values cause disconnects.</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Direction</b> — Choose Inbound, Outbound, or both.
Inbound affects data coming <i>from</i> the server; outbound affects data
going <i>to</i> the server.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Scheduler</b> — Set a delay before disruption
starts and a duration for how long it runs. Useful for timed operations.</p>
""", False),

    ("🗺 IZURVIVE MAP TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
An interactive <b>iZurvive</b> map embedded directly in DupeZ so you can
plan routes without switching windows.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Features:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>Full Chernarus+ and Livonia maps with pan/zoom</li>
<li>Satellite and Topographic layer toggle</li>
<li>GPU-accelerated rendering (requires the GPU build variant)</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Map slow or software-rendered?</b> Make sure you're
running the GPU build (DupeZ-GPU.exe). The Compat build runs elevated, which
forces QWebEngine into software rasterization.</p>
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

    ("🔄 DUPE ENGINE v2 — SMART DUPLICATION", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The Dupe Engine v2 replaces the old total-hard-cut approach with <b>selective
packet filtering</b> designed for DayZ 1.29+ servers. Instead of dropping all
traffic (which triggers freeze detection and disconnects), v2 classifies every
packet and only blocks game-state replication while keeping your connection
alive.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>How it works:</b> TCP, keepalives, and small acks
always pass through. Only GAME_STATE and GAME_BULK packets (inventory/entity
replication) are blocked. This creates a desync window where the server has
applied your action but your client never receives the confirmation — the
foundation for duplication.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Dupe Methods (presets in the dropdown):</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Drop & Pick</b> — Drop an item, the outbound RPC reaches the server,
then inbound state is blocked. Safest method, low detection risk</li>
<li><b>Swap</b> — Initiate a swap between hands and container. Blocks state
both directions to freeze the partial swap on the server</li>
<li><b>Container</b> — Put item in a container. Inbound block prevents the
client from seeing the server's confirmation of the transfer</li>
<li><b>Rift</b> — Extended bidirectional state block with pulse cycling. Most
aggressive — creates deep desync over multiple cycles</li>
<li><b>Legacy</b> — Total hard cut (v1 fallback). Only for pre-1.27 servers.
<b>Will disconnect you on modern servers</b></li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Graduated Restore:</b> When the cut ends, v2 doesn't
just open the floodgates. It restores in 3 phases: keepalives first, then
outbound game state in a drip-feed, then full open. This avoids reconnection
spike detection.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Tick-Aligned Entry:</b> Optional — v2 can wait for
the next server tick boundary before entering the cut, maximizing the chance
that the RPC is processed before state replication is blocked.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Tip:</b> Start with <b>Drop & Pick</b> — it has
the highest success rate and lowest detection risk. If that doesn't work on
your server, try <b>Rift</b> with 2 cycles.</p>
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
<b style='color:{_CYAN};'>Enable:</b> Tools → Settings → Voice tab. Select
your microphone and toggle voice control on.</p>

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
DupeZ can connect to a <b>CronusZEN</b> device for console automation
alongside network disruption — coordinate controller scripts with packet
manipulation.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Setup:</b> Plug in CronusZEN via USB. DupeZ
auto-detects it. The GPC panel appears in the sidebar when hardware is
found.</p>

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
<code>app/firewall</code>. Antivirus may quarantine these — add an exception
for the DupeZ install folder.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>"Failed to extract" on launch</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Windows Defender or antivirus is blocking extraction. Exclude
<code>dupez.exe</code> and <code>%TEMP%</code>. Ensure at least 500 MB of
free disk space.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>SmartScreen blocks the installer</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Click <b>"More info"</b> → <b>"Run anyway"</b>. DupeZ is not yet
code-signed with an EV certificate.</p>

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
Some games (especially with anti-cheat) have strict tolerance for packet
anomalies.</p>
""", False),

    ("⌨ KEYBOARD SHORTCUTS", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Quick reference:</p>

<table style='color:{_TEXT_MUTED}; font-size:12px; margin-top:6px;' cellpadding='4'>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+,</td>
    <td>Open Settings</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+S</td>
    <td>Scan Network</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+D</td>
    <td>Stop All Disruptions</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+E</td>
    <td>Export Data</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>Ctrl+Q</td>
    <td>Quit DupeZ</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace; padding-right:16px;'>F1</td>
    <td>Show Hotkey Reference</td></tr>
</table>

<p style='color:{_TEXT_MUTED}; font-size:11px; margin-top:8px;'>
Custom hotkeys can be configured in <b>Tools → Settings</b>.</p>
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
