"""OBS overlay HTTP endpoint (v5.7.1 feature #11).

Tiny localhost HTTP server that exposes the current disruption state
as JSON, so OBS Studio (or any browser-source-capable streaming app)
can consume it for stream graphics: "currently disrupting" indicator,
target IP badge, A2S cut-state badge, etc.

Two endpoints:

    GET /state
        Returns the live snapshot:
        {
          "version": 1,
          "now": 1715567812.341,
          "active_targets": [
            {
              "target_ip": "10.0.0.5",
              "preset": "Red Disconnect",
              "methods": ["drop", "disconnect"],
              "started_at": 1715567800.0,
              "duration_s": 12.3,
              "cut_state": "severed",
              "packets_processed": 1234,
              "packets_dropped": 1200
            }
          ],
          "risk_score": 54,
          "risk_band": "amber"
        }

    GET /overlay.html
        Self-contained HTML/JS page that polls /state every 1s and
        renders a minimal overlay. Drop the URL into OBS browser
        source, set the size, done. CSS is intentionally minimal —
        streamers theme it via OBS browser-source custom CSS.

Privacy:

* Bound to 127.0.0.1 by default — no LAN exposure unless explicitly
  reconfigured.
* IP fields are masked the same way the audit log masks them.
* No write endpoints — read-only.

Threading:

* :class:`OverlayServer.start` spawns a daemon thread running a
  :class:`http.server.ThreadingHTTPServer`. ``stop()`` shuts it down
  cleanly. Multiple browsers can poll concurrently; the thread pool
  is bounded by the OS socket backlog.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from app.logs.logger import log_error, log_info, log_warning


class _NoReuseThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with SO_REUSEADDR disabled.

    The stdlib base sets ``allow_reuse_address = True`` which maps to
    ``SO_REUSEADDR=1``. On Linux that only loosens TIME_WAIT reuse, but
    on Windows it lets a second ``bind()`` SILENTLY STEAL the port from
    a first listener — the opposite of what callers expect. We want a
    duplicate bind to raise ``OSError`` on every platform so
    :meth:`OverlayServer.start` can honestly report False. v5.7.4
    regression test ``test_start_returns_false_on_bind_failure`` locks
    this behavior.
    """

    allow_reuse_address = False


__all__ = [
    "OverlayServer",
    "build_state_snapshot",
]


# ── HTML payload for /overlay.html ───────────────────────────────────
_OVERLAY_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>DupeZ Overlay</title>
<style>
  html, body { margin:0; padding:0; background:transparent;
    font-family:'Cascadia Code','Consolas',monospace; color:#e2e8f0; }
  .root { padding:12px 18px; }
  .badge { display:inline-block; padding:4px 10px; margin-right:6px;
    border-radius:6px; font-size:12px; font-weight:600;
    background:rgba(8,12,22,0.85); border:1px solid rgba(0,240,255,0.35); }
  .badge.active { border-color:#ff6b6b; color:#ff6b6b; }
  .badge.amber  { border-color:#fbbf24; color:#fbbf24; }
  .badge.red    { border-color:#ff6b6b; color:#ff6b6b; }
  .badge.green  { border-color:#00ff88; color:#00ff88; }
  .target { font-size:11px; color:#94a3b8; margin-top:4px; }
</style></head>
<body><div class="root" id="root">connecting…</div>
<script>
async function tick() {
  try {
    const r = await fetch('/state', {cache:'no-store'});
    const s = await r.json();
    const root = document.getElementById('root');
    const parts = [];
    if (s.active_targets && s.active_targets.length) {
      parts.push('<span class="badge active">DISRUPTING</span>');
      for (const t of s.active_targets) {
        parts.push(
          '<div class="target">' +
          (t.preset || '?') + ' · ' + (t.target_ip || '?') +
          ' · ' + (t.cut_state || 'unknown') +
          ' · ' + Math.round(t.duration_s || 0) + 's</div>'
        );
      }
    } else {
      parts.push('<span class="badge">IDLE</span>');
    }
    if (typeof s.risk_score === 'number') {
      parts.push('<span class="badge ' + (s.risk_band || 'green') +
        '">RISK ' + s.risk_score + '</span>');
    }
    root.innerHTML = parts.join('');
  } catch (e) {
    document.getElementById('root').innerHTML =
      '<span class="badge">offline</span>';
  }
}
tick(); setInterval(tick, 1000);
</script></body></html>"""


# ── State snapshot ───────────────────────────────────────────────────

def build_state_snapshot(controller: Any) -> Dict[str, Any]:
    """Render the current disruption state as a JSON-ready dict.

    Pulls from ``controller.disrupted_devices`` (the live dict
    maintained by the disruption manager) and adds the risk score
    on top. Never raises — failures degrade fields to safe defaults.
    """
    try:
        from app.utils.helpers import mask_ip
    except Exception:
        def mask_ip(s: str) -> str:  # type: ignore
            return s

    snapshot: Dict[str, Any] = {
        "version": 1,
        "now": time.time(),
        "active_targets": [],
        "risk_score": None,
        "risk_band": None,
    }

    # Active disruptions.
    try:
        devices = getattr(controller, "disrupted_devices", {}) or {}
    except Exception:
        devices = {}
    now = snapshot["now"]
    for ip, info in devices.items():
        try:
            engine = info.get("engine")
            params = info.get("params", {}) or {}
            start_time = info.get("start_time", now)
            snapshot["active_targets"].append({
                "target_ip": mask_ip(str(ip)),
                "preset": params.get("_preset", "?"),
                "methods": list(info.get("methods", []) or []),
                "started_at": start_time,
                "duration_s": round(now - start_time, 1),
                "cut_state": getattr(engine, "_max_cut_state", "unknown"),
                "packets_processed": int(
                    getattr(engine, "_packets_processed", 0) or 0
                ),
                "packets_dropped": int(
                    getattr(engine, "_packets_dropped", 0) or 0
                ),
            })
        except Exception as exc:
            log_warning(f"overlay: target {ip} render failed: {exc}")

    # Risk score (best-effort).
    try:
        from app.core.risk_score import compute_risk_score
        score = compute_risk_score()
        snapshot["risk_score"] = score.score
        snapshot["risk_band"] = score.band
    except Exception:
        pass

    return snapshot


# ── HTTP server ──────────────────────────────────────────────────────

def _make_handler_class(controller: Any) -> type:
    """Build a per-server handler class with the controller closure-bound.

    Avoids the multi-instance hazard of attaching the controller as a
    class attribute (last writer wins, breaks tests that spin up two
    OverlayServer instances on different ports).
    """

    class _OverlayHandler(BaseHTTPRequestHandler):
        """Read-only HTTP handler."""

        _controller = controller

        def do_GET(self) -> None:  # noqa: N802 — http.server API
            if self.path.startswith("/state"):
                body = json.dumps(
                    build_state_snapshot(self._controller)
                ).encode("utf-8")
                self._send(200, "application/json", body)
            elif self.path.startswith("/overlay.html") or self.path == "/":
                self._send(200, "text/html; charset=utf-8",
                           _OVERLAY_HTML.encode("utf-8"))
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # v5.7.3 SECURITY: NO wildcard CORS header.
            #
            # The OBS browser source navigates directly TO /overlay.html,
            # so its fetch() calls to /state are same-origin and need no
            # CORS grant. A wildcard `Access-Control-Allow-Origin: *`
            # would let ANY web page the operator visits in a normal
            # browser poll http://127.0.0.1:4778/state and learn that
            # DupeZ is running, what it is targeting, and the live risk
            # score — a cross-origin information leak. Omitting the
            # header entirely keeps /state readable only same-origin
            # (i.e. only by the overlay page we serve).
            #
            # X-Content-Type-Options stops a browser from MIME-sniffing
            # the JSON/HTML into something executable.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
            """Route access logs to DupeZ's logger instead of stderr."""
            # Discard the default per-request access log to keep logs
            # readable. Real errors still surface via DupeZ's logger.
            return

        def log_error(self, fmt: str, *args: Any) -> None:  # noqa: D401
            """Route handler errors to DupeZ's logger."""
            try:
                log_warning(f"OverlayServer handler error: {fmt % args}")
            except Exception:
                # Defensive: malformed format args shouldn't bring down
                # the request thread.
                log_warning("OverlayServer handler error (unformattable)")

    return _OverlayHandler


class OverlayServer:
    """Lifecycle wrapper around the ThreadingHTTPServer.

    Each instance owns its own handler class so multiple servers can
    coexist on different ports without clobbering each other's
    controller reference.
    """

    def __init__(
        self,
        controller: Any,
        host: str = "127.0.0.1",
        port: int = 4778,
    ) -> None:
        self._controller = controller
        self._host = host
        self._port = int(port)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def running(self) -> bool:
        """True when the HTTP server is bound and serving."""
        return self._server is not None

    def start(self) -> bool:
        """Start the overlay HTTP server.

        Returns:
            True if the server is bound and serving (or was already
            running), False if the bind failed — e.g. the port is in
            use. v5.7.4 callers (main.py autostart, dashboard toggle)
            check this so they never report "overlay started" on a
            failed bind. Pre-v5.7.5 start() always returned None and
            both callers reported success unconditionally.
        """
        if self._server is not None:
            return True
        handler_cls = _make_handler_class(self._controller)
        try:
            self._server = _NoReuseThreadingHTTPServer(
                (self._host, self._port), handler_cls
            )
        except OSError as exc:
            log_error(
                f"OverlayServer bind failed on {self._host}:{self._port}: "
                f"{exc}"
            )
            self._server = None
            return False
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True, name="OverlayServer"
        )
        self._thread.start()
        log_info(
            f"OverlayServer listening on {self.base_url}/overlay.html"
        )
        return True

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception as exc:
            log_warning(f"OverlayServer shutdown: {exc}")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
        log_info("OverlayServer stopped")
