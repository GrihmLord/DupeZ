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
from typing import Any, Callable, Dict, Optional

from app.logs.logger import log_error, log_info, log_warning


_RISK_CACHE_TTL_SECONDS = 2.0
_SERVER_START_TIMEOUT_SECONDS = 2.0
_risk_cache_lock = threading.Lock()
_risk_cache_score: Optional[int] = None
_risk_cache_band: Optional[str] = None
_risk_cache_at = 0.0
_risk_refresh_in_progress = False


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
    "OverlayServerOwner",
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

def _refresh_risk_cache() -> None:
    """Refresh overlay risk data off the request thread.

    Risk scoring can inspect the episode store and a bounded audit-log tail.
    Neither should make the localhost HTTP handler miss its one-second polling
    cadence, so the endpoint serves the last complete value while one daemon
    refresh is in flight.
    """
    global _risk_cache_at, _risk_cache_band, _risk_cache_score
    global _risk_refresh_in_progress

    score_value: Optional[int] = None
    band_value: Optional[str] = None
    try:
        from app.core.risk_score import compute_risk_score

        score = compute_risk_score()
        score_value = int(score.score)
        band_value = str(score.band)
        if not 0 <= score_value <= 100 or band_value not in {
            "green",
            "amber",
            "red",
        }:
            raise ValueError("invalid risk score result")
    except Exception:
        log_warning("overlay: risk score refresh unavailable")
    finally:
        with _risk_cache_lock:
            if score_value is not None and band_value is not None:
                _risk_cache_score = score_value
                _risk_cache_band = band_value
                _risk_cache_at = time.monotonic()
            _risk_refresh_in_progress = False


def _cached_risk_score() -> tuple[Optional[int], Optional[str]]:
    """Return the last complete risk value and start one refresh if stale."""
    global _risk_refresh_in_progress

    now = time.monotonic()
    with _risk_cache_lock:
        stale = now - _risk_cache_at >= _RISK_CACHE_TTL_SECONDS
        if stale and not _risk_refresh_in_progress:
            _risk_refresh_in_progress = True
            try:
                threading.Thread(
                    target=_refresh_risk_cache,
                    daemon=True,
                    name="OverlayRiskRefresh",
                ).start()
            except RuntimeError:
                _risk_refresh_in_progress = False
                log_warning("overlay: risk score refresh could not start")
        return _risk_cache_score, _risk_cache_band


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

    # Risk score (best-effort and latency-bounded). The first request can
    # legitimately report null while the daemon refresh warms the cache.
    snapshot["risk_score"], snapshot["risk_band"] = _cached_risk_score()

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
        self._ready: Optional[threading.Event] = None
        self._serve_failed: Optional[threading.Event] = None
        self._lifecycle_lock = threading.RLock()

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def running(self) -> bool:
        """True when the HTTP server is bound and serving."""
        with self._lifecycle_lock:
            return self._running_locked()

    @property
    def owns_resources(self) -> bool:
        """True while this instance owns any server lifecycle resource."""
        with self._lifecycle_lock:
            return any(
                item is not None
                for item in (self._server, self._thread, self._ready)
            )

    def _running_locked(self) -> bool:
        thread = self._thread
        ready = self._ready
        failed = self._serve_failed
        return bool(
            self._server is not None
            and thread is not None
            and thread.is_alive()
            and ready is not None
            and ready.is_set()
            and (failed is None or not failed.is_set())
        )

    def _clear_resources_locked(self) -> None:
        self._server = None
        self._thread = None
        self._ready = None
        self._serve_failed = None

    def _cleanup_failed_start_locked(
        self,
        server: ThreadingHTTPServer,
        thread: threading.Thread,
    ) -> bool:
        """Close a bound-but-unstarted server without losing ownership."""
        cleanup_ok = True
        try:
            server.server_close()
        except Exception as exc:
            cleanup_ok = False
            log_error(f"OverlayServer failed-start socket cleanup failed: {exc}")
        if thread.ident is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if thread.is_alive():
            cleanup_ok = False
            log_error("OverlayServer failed-start worker did not exit")
        if cleanup_ok:
            self._clear_resources_locked()
        return cleanup_ok

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
        with self._lifecycle_lock:
            if self.owns_resources:
                if self._running_locked():
                    return True
                log_error(
                    "OverlayServer start refused while prior resources remain "
                    "owned after incomplete cleanup"
                )
                return False

            handler_cls = _make_handler_class(self._controller)
            try:
                server = _NoReuseThreadingHTTPServer(
                    (self._host, self._port), handler_cls
                )
            except OSError as exc:
                log_error(
                    f"OverlayServer bind failed on {self._host}:{self._port}: "
                    f"{exc}"
                )
                return False

            # Port zero asks the kernel for an ephemeral port. Publish the
            # actual bound port before callers receive a successful result.
            self._port = int(server.server_address[1])
            ready = threading.Event()
            cancel_before_serve = threading.Event()
            serve_failed = threading.Event()

            def _serve() -> None:
                ready.set()
                if cancel_before_serve.is_set():
                    return
                try:
                    server.serve_forever()
                except Exception as exc:
                    serve_failed.set()
                    log_error(f"OverlayServer worker failed: {exc}")

            thread = threading.Thread(
                target=_serve,
                daemon=True,
                name="OverlayServer",
            )
            # Publish the complete ownership record before starting the
            # worker. If startup or cleanup fails, later stop() calls retain a
            # truthful handle to every resource that may still be live.
            self._server = server
            self._thread = thread
            self._ready = ready
            self._serve_failed = serve_failed
            try:
                thread.start()
            except RuntimeError as exc:
                log_error(f"OverlayServer thread could not be started: {exc}")
                self._cleanup_failed_start_locked(server, thread)
                return False

            if not ready.wait(_SERVER_START_TIMEOUT_SECONDS):
                log_error(
                    "OverlayServer thread did not become ready before timeout"
                )
                cancel_before_serve.set()
                self._cleanup_failed_start_locked(server, thread)
                return False
            if not self._running_locked():
                log_error("OverlayServer worker exited during startup")
                self._cleanup_failed_start_locked(server, thread)
                return False

            log_info(
                f"OverlayServer listening on {self.base_url}/overlay.html"
            )
            return True

    def stop(self) -> bool:
        """Release all owned resources and confirm the worker has exited."""
        with self._lifecycle_lock:
            if not self.owns_resources:
                return True
            server = self._server
            thread = self._thread
            cleanup_ok = True

            if server is not None:
                if thread is not None and thread.is_alive():
                    try:
                        server.shutdown()
                    except Exception as exc:
                        cleanup_ok = False
                        log_error(f"OverlayServer shutdown failed: {exc}")
                try:
                    server.server_close()
                except Exception as exc:
                    cleanup_ok = False
                    log_error(f"OverlayServer socket close failed: {exc}")

            if thread is not None:
                if thread is threading.current_thread():
                    cleanup_ok = False
                    log_error("OverlayServer cannot join its own worker")
                elif thread.ident is not None:
                    thread.join(timeout=2.0)
                if thread.is_alive():
                    cleanup_ok = False
                    log_error("OverlayServer worker did not stop within 2s")

            if not cleanup_ok:
                log_warning(
                    "OverlayServer cleanup was not confirmed; ownership retained"
                )
                return False

            self._clear_resources_locked()
            log_info("OverlayServer stopped")
            return True


class OverlayServerOwner:
    """Single authoritative owner shared by startup, UI, and shutdown."""

    def __init__(
        self,
        controller: Any,
        host: str = "127.0.0.1",
        port: int = 4778,
        *,
        server_factory: Callable[..., OverlayServer] = OverlayServer,
    ) -> None:
        self._controller = controller
        self._host = host
        self._port = int(port)
        self._server_factory = server_factory
        self._server: Optional[OverlayServer] = None
        self._lock = threading.RLock()

    @property
    def owned(self) -> bool:
        with self._lock:
            return self._server is not None

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._server is not None and self._server.running)

    @property
    def base_url(self) -> str:
        with self._lock:
            if self._server is not None:
                return self._server.base_url
            return f"http://{self._host}:{self._port}"

    @property
    def server(self) -> Optional[OverlayServer]:
        """Expose the owned instance for diagnostics, never for mutation."""
        with self._lock:
            return self._server

    def start(self) -> bool:
        with self._lock:
            if self._server is not None:
                if self._server.running:
                    return True
                log_error(
                    "OBS overlay start refused until retained resources are "
                    "successfully cleaned up"
                )
                return False

            candidate = self._server_factory(
                self._controller,
                host=self._host,
                port=self._port,
            )
            try:
                started = bool(candidate.start())
            except Exception:
                if candidate.owns_resources:
                    self._server = candidate
                raise
            if started and candidate.running:
                self._server = candidate
                return True
            if candidate.owns_resources:
                self._server = candidate
            if started:
                log_error(
                    "OBS overlay start returned success without a live worker"
                )
            return False

    def stop(self) -> bool:
        with self._lock:
            server = self._server
            if server is None:
                return True
            try:
                stopped = bool(server.stop())
            except Exception as exc:
                log_error(f"OBS overlay owner cleanup raised: {exc}")
                return False
            if not stopped:
                return False
            self._server = None
            return True
