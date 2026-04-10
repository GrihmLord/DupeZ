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
<b style='color:{_CYAN};'>DupeZ</b> is a network disruption toolkit for gamers.
It lets you control your network connection to games like
<b>DayZ</b>, <b>GTA</b>, <b>Fortnite</b>, and more — on <b>PS5</b>,
<b>Xbox</b>, and <b>PC</b>.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
In simple terms: DupeZ sits between your device and the game server, and lets
you temporarily slow down, drop, or delay packets. This can be used for testing
network conditions, simulating lag, or other purposes.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>⚠ Important:</b> DupeZ requires
<b>Administrator</b> privileges to work because it uses a low-level
network driver called <b>WinDivert</b>. Always run DupeZ as Admin.</p>
""", True),

    ("GETTING STARTED — FIRST-TIME SETUP", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Follow these steps the very first time you open DupeZ:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Step 1:</b> Right-click <code>dupez.exe</code> and
select <b>"Run as administrator"</b>. DupeZ needs admin to intercept packets.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Step 2:</b> When the splash screen finishes loading,
you'll see the main window with a sidebar on the left. The first tab
(🎯) is the <b>Clumsy Control</b> — this is where all the action happens.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Step 3:</b> Select a <b>Game Profile</b> from the
dropdown at the top of Clumsy Control. This automatically sets up the correct
filter for your game (the right ports and IP ranges).</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Step 4:</b> Toggle on the disruption modules you want
(Lag, Drop, Throttle, etc.) and hit the big <b>Start</b> button.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Step 5:</b> When you're done, hit <b>Stop</b>. Your
connection returns to normal instantly.</p>
""", False),

    ("🎯 CLUMSY CONTROL — THE MAIN VIEW", f"""
<p style='color:{_TEXT}; font-size:12px;'>
This is the first tab and the core of DupeZ. Here's what each part does:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:8px;'>
<b style='color:{_CYAN};'>Game Profile Selector</b> — The dropdown at the top.
Pick your game and DupeZ auto-fills the network filter so you don't have to
know anything about IP addresses or ports.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Disruption Modules</b> — The checkboxes on the left.
Each one does something different to your packets:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_GREEN};'>Lag</b> — Adds a delay (in milliseconds) to
every packet. Higher = more delay. Start with 100-200ms.</li>
<li><b style='color:{_GREEN};'>Drop</b> — Randomly discards a percentage of
packets. 10-30% is noticeable, 50%+ is extreme.</li>
<li><b style='color:{_GREEN};'>Throttle</b> — Holds packets and releases them
in bursts. Makes the connection "choppy".</li>
<li><b style='color:{_GREEN};'>Duplicate</b> — Sends copies of packets. Can
cause desyncs.</li>
<li><b style='color:{_GREEN};'>Out of Order</b> — Shuffles packet sequence.
Confuses game netcode.</li>
<li><b style='color:{_GREEN};'>Tamper</b> — Corrupts packet data bits.
Use sparingly — can cause disconnects.</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Sliders</b> — Each module has a slider to control
intensity (percentage or milliseconds). Drag to adjust.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Start / Stop Button</b> — The big button at the
bottom. Green = start disruption. Red = stop and restore normal connection.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Device Table</b> — Shows detected devices on your
network. Select a target device to focus disruption on just that device.</p>
""", False),

    ("🗺 IZURVIVE MAP TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The second tab (🗺️) opens an interactive <b>iZurvive</b> map for DayZ. This
is the same map you'd see on the iZurvive website, embedded right inside
DupeZ.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>What you can do:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>Pan and zoom the Chernarus+ map</li>
<li>Switch between Satellite and Topographic views</li>
<li>Use it as a reference while playing DayZ</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Note:</b> This tab requires
<b>PyQt6-WebEngine</b> to be installed. If you see a "Map unavailable"
message, the WebEngine component isn't present in your build. The rest of
DupeZ works fine without it.</p>
""", False),

    ("👤 ACCOUNT TRACKER TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The third tab (👤) is the <b>DayZ Account Tracker</b>. It helps you manage
multiple DayZ characters and track their stats across servers.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Features:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b>Add accounts</b> — Track different characters or alt accounts</li>
<li><b>Server history</b> — See which servers each account has visited</li>
<li><b>Notes</b> — Add personal notes to each account (gear, base location, etc.)</li>
<li><b>Status tracking</b> — Mark accounts as active, banned, or inactive</li>
</ul>
""", False),

    ("📡 NETWORK TOOLS TAB", f"""
<p style='color:{_TEXT}; font-size:12px;'>
The fourth tab (📡) is a suite of <b>Network Intelligence Tools</b> for
diagnosing and monitoring your connection:</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Traffic Monitor</b> — Shows real-time bandwidth
usage per network interface. Useful for seeing if something is eating your
bandwidth.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Latency Overlay</b> — Continuously pings a target
(like a game server) and shows your ping and jitter. Has a floating overlay
mode you can keep on screen while gaming.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Port Scanner</b> — Scans open TCP ports on a target
IP. Useful for checking if game server ports are open and reachable.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Connection Mapper</b> — Shows all active network
connections on your machine in real time. You can see exactly which IPs your
game is talking to.</p>
""", False),

    ("⚙ SETTINGS & THEMES", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Open settings from the menu bar: <b>Tools → Settings</b> (or press
<b>Ctrl+,</b>).</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Themes</b> — DupeZ comes with 4 built-in themes:</p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li><b style='color:{_CYAN};'>Dark</b> — Navy/cyan glassmorphism (default)</li>
<li><b>Light</b> — Clean white with blue accents</li>
<li><b style='color:{_GREEN};'>Hacker</b> — Green phosphor terminal aesthetic</li>
<li><b style='color:{_PURPLE};'>Rainbow</b> — Animated color cycling</li>
</ul>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Hotkeys</b> — You can configure keyboard shortcuts
for quick actions. Press <b>F1</b> to see the full hotkey list.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Auto-Update</b> — DupeZ can check for updates
automatically. Go to <b>Help → Check for Updates</b> in the menu bar.</p>
""", False),

    ("🎙 VOICE CONTROL (OPTIONAL)", f"""
<p style='color:{_TEXT}; font-size:12px;'>
If you have a microphone and the optional voice libraries installed, DupeZ can
be controlled entirely by voice commands.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>How to enable:</b> Go to <b>Tools → Settings →
Voice</b> tab. Toggle voice control on and select your microphone.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Example commands:</b></p>
<ul style='color:{_TEXT_MUTED}; font-size:12px; margin-left:16px;'>
<li>"Start disruption" — Starts the active modules</li>
<li>"Stop" — Stops all disruption</li>
<li>"Set lag to 200" — Adjusts lag module to 200ms</li>
<li>"Enable drop" — Turns on the drop module</li>
</ul>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Requires:</b> <code>pip install sounddevice whisper</code></p>
""", False),

    ("🎮 GPC / CRONUS ZEN (OPTIONAL)", f"""
<p style='color:{_TEXT}; font-size:12px;'>
DupeZ can connect to a <b>CronusZEN</b> device for advanced console
automation alongside network disruption.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:6px;'>
<b style='color:{_CYAN};'>Setup:</b> Plug in your CronusZEN via USB. DupeZ
will auto-detect it. Go to the GPC panel (available as a plugin panel in the
sidebar) to load and manage scripts.</p>

<p style='color:{_TEXT_MUTED}; font-size:12px; margin-top:8px;'>
<b style='color:{_AMBER};'>Requires:</b> CronusZEN hardware + USB connection.
<code>pip install pyserial</code></p>
""", False),

    ("❓ TROUBLESHOOTING", f"""
<p style='color:{_TEXT}; font-size:12px;'>
<b style='color:{_RED};'>DupeZ won't start / "Access Denied"</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Right-click the exe and choose <b>"Run as administrator"</b>. DupeZ needs
admin privileges for WinDivert.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>"WinDivert engine unavailable"</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Make sure <code>WinDivert.dll</code> and <code>WinDivert64.sys</code> are
in the <code>app/firewall</code> folder. Some antivirus software quarantines
WinDivert — add an exception for the DupeZ folder.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>"Failed to extract" errors on launch</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Your antivirus or Windows Defender may be blocking extraction. Add an
exception for <code>dupez.exe</code> and the <code>%TEMP%</code> folder.
Also make sure you have enough free disk space (at least 500 MB).</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Windows SmartScreen blocks the installer</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Click <b>"More info"</b> then <b>"Run anyway"</b>. This happens because
DupeZ is not yet code-signed with an EV certificate. It's safe to run.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Disruption isn't working / no effect in game</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Check that you selected the correct <b>Game Profile</b>. Make sure at least
one module is enabled with a non-zero value. Verify the status bar says
<b>"CONNECTED"</b>.</p>

<p style='color:{_TEXT}; font-size:12px; margin-top:10px;'>
<b style='color:{_RED};'>Game disconnects immediately</b></p>
<p style='color:{_TEXT_MUTED}; font-size:12px;'>
→ Your disruption values are too aggressive. Lower the Drop percentage (try
10-15%) and reduce Lag to under 300ms. Some games have strict anti-cheat that
detects extreme packet manipulation.</p>
""", False),

    ("⌨ KEYBOARD SHORTCUTS", f"""
<p style='color:{_TEXT}; font-size:12px;'>
Quick reference for keyboard shortcuts:</p>

<table style='color:{_TEXT_MUTED}; font-size:12px; margin-top:6px;' cellpadding='4'>
<tr><td style='color:{_CYAN}; font-family:monospace;'>F1</td>
    <td>Show hotkey reference</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace;'>Ctrl+,</td>
    <td>Open Settings</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace;'>Ctrl+Q</td>
    <td>Quit DupeZ</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace;'>Ctrl+S</td>
    <td>Start / Stop disruption</td></tr>
<tr><td style='color:{_CYAN}; font-family:monospace;'>Ctrl+1-4</td>
    <td>Switch between sidebar tabs</td></tr>
</table>

<p style='color:{_TEXT_MUTED}; font-size:11px; margin-top:8px;'>
Custom hotkeys can be configured in <b>Tools → Settings → Hotkeys</b>.</p>
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
