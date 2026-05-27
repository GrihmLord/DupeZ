"""Discord (and generic HTTP) webhook audit sink (v5.7.0 feature #10).

Wraps the existing ``audit_event`` event stream with an outbound POST
to a user-configured webhook URL — Discord is the primary target, but
the implementation is generic enough for any service that accepts a
JSON body (Slack incoming-webhook, Telegram bot, Mattermost, etc.).

Design:

* Subscribers register a sink via :func:`register_sink`. The audit log
  emits to JSONL first (the canonical record) and then fan-outs to
  every registered sink on its own thread — webhook failures never
  block the engine.
* Sinks declare an event whitelist (default: cut_start, cut_end,
  flow_health_miss, killswitch_fired, outcome). Anything outside the
  list is filtered before the POST so the webhook only sees signal.
* Rate limiting: per-sink token bucket prevents accidental Discord
  rate-limit hits. Default 30 events/min, configurable.
* Privacy: webhook payloads strip any field whose name starts with
  underscore (internal engine params) and run the same IP-masking
  helpers the audit log already uses, so target IPs don't leak in
  full to a public Discord channel.

Discord-specific helpers translate the structured audit dict into
a Discord embed: title = event name, color = success/warn/error,
fields = key telemetry. Plain webhooks get the raw JSON.

Config schema (persisted via secret store — the URL is sensitive
because possession of it lets anyone post into the channel):

    {
        "enabled": false,
        "url": "https://discord.com/api/webhooks/<id>/<token>",
        "kind": "discord" | "generic",
        "events": ["cut_start", "cut_end", "outcome", "killswitch_fired"],
        "rate_limit_per_min": 30,
        "username": "DupeZ",                  # optional, Discord only
        "avatar_url": null                    # optional, Discord only
    }
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.logs.logger import log_info, log_warning


__all__ = [
    "AuditSink",
    "DiscordWebhookSink",
    "GenericWebhookSink",
    "WebhookURLError",
    "register_sink",
    "unregister_sink",
    "list_sinks",
    "clear_sinks",
    "emit_to_sinks",
    "DEFAULT_EVENT_WHITELIST",
]


DEFAULT_EVENT_WHITELIST: Set[str] = {
    "cut_start",
    "cut_end",
    "outcome",
    "flow_health_miss",
    "killswitch_fired",
    "disruption_start",
    "disruption_stop",
}


# ── Rate limiter (token bucket) ──────────────────────────────────────

@dataclass
class _TokenBucket:
    """Simple token bucket. Not thread-safe; caller holds the sink lock.

    Starts full (tokens=capacity) so a newly-created sink can deliver
    the first ``capacity`` events immediately rather than waiting for
    the refill window. Pre-v5.7.1 the bucket started at 0, which
    caused sinks to silently drop every event for the first
    ``60/refill_per_min`` seconds after subscription — surfaced by
    test_emit_does_not_block.
    """
    capacity: int
    refill_per_min: int
    tokens: float = field(init=False)
    last_refill: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        # Start with a full bucket. Without this, the FIRST event after
        # any sink registration gets rate-limited because no time has
        # elapsed to refill.
        self.tokens = float(self.capacity)

    def take(self) -> bool:
        now = time.time()
        elapsed_min = (now - self.last_refill) / 60.0
        self.tokens = min(
            float(self.capacity),
            self.tokens + elapsed_min * self.refill_per_min,
        )
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# ── URL validation ───────────────────────────────────────────────────

class WebhookURLError(ValueError):
    """Raised when a webhook URL fails the security scheme check."""


def _validate_webhook_url(url: str) -> str:
    """Validate + normalize a webhook URL. Raises WebhookURLError on reject.

    v5.7.3 SECURITY: ``urllib.request.urlopen`` honors ANY scheme it has
    a handler for — including ``file://`` (reads a local file) and
    ``ftp://``. If a webhook URL ever reaches a sink from an untrusted
    source (an imported config bundle, a shared preset, a future
    marketplace), an attacker-set ``file:///C:/Users/.../secrets.enc.json``
    would exfiltrate that file's contents to... nowhere useful for them
    directly, but more importantly a ``file://`` or ``gopher://`` URL
    can be abused for SSRF-style local probing.

    Policy: only ``https://`` is accepted, with one exception —
    ``http://`` is allowed when the host is loopback (127.0.0.1 /
    localhost / ::1), so operators can point a sink at a local
    relay / test listener during development.
    """
    import urllib.parse
    if not isinstance(url, str) or not url.strip():
        raise WebhookURLError("webhook URL is empty")
    parsed = urllib.parse.urlparse(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https":
        return url.strip()
    if scheme == "http" and host in ("127.0.0.1", "localhost", "::1"):
        return url.strip()
    raise WebhookURLError(
        f"webhook URL rejected: scheme {scheme!r} not allowed "
        f"(use https://, or http:// only for localhost). "
        f"file://, ftp://, gopher:// and other schemes are blocked."
    )


# ── Sink base + concrete sinks ───────────────────────────────────────

class AuditSink:
    """Base class. Subclasses override :meth:`_post`."""

    def __init__(
        self,
        url: str,
        *,
        events: Optional[Set[str]] = None,
        rate_limit_per_min: int = 30,
        timeout_s: float = 5.0,
    ) -> None:
        # v5.7.3: validate scheme at construction — a sink can never be
        # created with a file:// or other dangerous URL.
        self.url = _validate_webhook_url(url)
        self._events: Set[str] = set(events) if events is not None else set(DEFAULT_EVENT_WHITELIST)
        self._bucket = _TokenBucket(
            capacity=max(1, rate_limit_per_min),
            refill_per_min=max(1, rate_limit_per_min),
        )
        self._timeout = float(timeout_s)
        self._lock = threading.Lock()

    def accepts(self, event_name: str) -> bool:
        return event_name in self._events

    def emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        if not self.accepts(event_name):
            return
        with self._lock:
            if not self._bucket.take():
                # Rate-limited: drop silently. The canonical audit log
                # already has the event; the webhook is a notification
                # convenience, not a record of truth.
                return
        # Fire-and-forget on its own thread so a slow webhook doesn't
        # block the engine. Daemon thread — process exit won't hang.
        threading.Thread(
            target=self._fire_safe,
            args=(event_name, payload),
            daemon=True,
            name=f"AuditSink-{event_name}",
        ).start()

    def _fire_safe(self, event_name: str, payload: Dict[str, Any]) -> None:
        try:
            scrubbed = _scrub(payload)
            self._post(event_name, scrubbed)
        except Exception as exc:
            log_warning(f"AuditSink {self.__class__.__name__} failed: {exc}")

    def _post(self, event_name: str, payload: Dict[str, Any]) -> None:  # noqa: D401
        raise NotImplementedError


class GenericWebhookSink(AuditSink):
    """POSTs a JSON body ``{event, payload, ts}`` to the webhook URL."""

    def _post(self, event_name: str, payload: Dict[str, Any]) -> None:
        body = json.dumps({
            "event": event_name,
            "payload": payload,
            "ts": time.time(),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DupeZ-AuditWebhook/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    log_warning(
                        f"GenericWebhookSink HTTP {resp.status} from {self.url}"
                    )
        except urllib.error.URLError as exc:
            log_warning(f"GenericWebhookSink urlopen failed: {exc}")


class DiscordWebhookSink(AuditSink):
    """POSTs a Discord-shaped embed payload."""

    # Discord embed color codes (RGB int). Loose mapping; users can
    # override by event in a future config knob.
    _EVENT_COLORS = {
        "cut_start":          0x3498db,  # blue
        "cut_end":            0x2ecc71,  # green
        "outcome":            0x9b59b6,  # purple
        "flow_health_miss":   0xf39c12,  # amber
        "killswitch_fired":   0xe74c3c,  # red
        "disruption_start":   0x3498db,
        "disruption_stop":    0x95a5a6,  # grey
    }

    def __init__(
        self,
        url: str,
        *,
        username: str = "DupeZ",
        avatar_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(url, **kwargs)
        self._username = username
        self._avatar_url = avatar_url

    def _post(self, event_name: str, payload: Dict[str, Any]) -> None:
        color = self._EVENT_COLORS.get(event_name, 0x607d8b)
        # Build the embed: title is the event, fields are payload keys
        # (capped at 10 to fit Discord's 25-field limit and stay readable).
        fields = []
        for k, v in list(payload.items())[:10]:
            fields.append({
                "name": str(k),
                "value": str(v)[:1024] or "—",
                "inline": True,
            })
        body = {
            "username": self._username,
            "embeds": [{
                "title": f"DupeZ · {event_name}",
                "color": color,
                "fields": fields,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
            }],
        }
        if self._avatar_url:
            body["avatar_url"] = self._avatar_url
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DupeZ-AuditWebhook/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    log_warning(
                        f"DiscordWebhookSink HTTP {resp.status}"
                    )
        except urllib.error.URLError as exc:
            log_warning(f"DiscordWebhookSink urlopen failed: {exc}")


# ── Registry + emit helper ───────────────────────────────────────────

_sinks: List[AuditSink] = []
_sinks_lock = threading.Lock()


def register_sink(sink: AuditSink) -> None:
    """Add *sink* to the broadcast list. Idempotent on identity."""
    with _sinks_lock:
        if sink not in _sinks:
            _sinks.append(sink)
            log_info(
                f"Audit sink registered: {sink.__class__.__name__}"
            )


def unregister_sink(sink: AuditSink) -> None:
    with _sinks_lock:
        if sink in _sinks:
            _sinks.remove(sink)
            log_info(
                f"Audit sink removed: {sink.__class__.__name__}"
            )


def list_sinks() -> List[AuditSink]:
    """Return a snapshot of currently-registered sinks.

    UI uses this to render the "active webhooks" list and offer
    per-sink remove buttons. Snapshot is safe to mutate; concurrent
    register/unregister calls won't see this list.
    """
    with _sinks_lock:
        return list(_sinks)


def clear_sinks() -> None:
    """Remove every registered sink. Used by config-reload paths."""
    with _sinks_lock:
        _sinks.clear()
    log_info("All audit sinks cleared")


def emit_to_sinks(event_name: str, payload: Dict[str, Any]) -> None:
    """Fan out *event_name* + *payload* to every registered sink.

    Called by the existing ``audit_event`` helper AFTER the JSONL write
    succeeds, so the canonical record is durable before any webhook fires.
    Sinks dispatch on their own daemon threads — this call returns
    immediately.
    """
    with _sinks_lock:
        targets = list(_sinks)
    for s in targets:
        try:
            s.emit(event_name, payload)
        except Exception as exc:
            log_warning(f"emit_to_sinks: sink {s} raised: {exc}")


# ── Privacy scrubbing ────────────────────────────────────────────────

def _scrub(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove underscore-prefixed keys + mask every IP before egress.

    The audit log itself already masks IPs before write; the webhook
    layer adds defense-in-depth in case a future caller forgets to
    pre-mask. Keys starting with underscore are internal engine params
    not meant for external eyes. ``mask_ips_in_text`` masks every IPv4
    address in a string value — bare ("10.0.0.9") OR embedded in prose
    ("cut on 10.0.0.9 failed") — so nothing leaks to Discord.
    """
    try:
        from app.utils.helpers import mask_ips_in_text
    except Exception:
        def mask_ips_in_text(s: str) -> str:  # type: ignore
            return s
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(k, str) and k.startswith("_"):
            continue
        if isinstance(v, str):
            out[k] = mask_ips_in_text(v)
        elif isinstance(v, dict):
            out[k] = _scrub(v)
        elif isinstance(v, list):
            out[k] = [
                _scrub(x) if isinstance(x, dict)
                else (mask_ips_in_text(x) if isinstance(x, str) else x)
                for x in v
            ]
        else:
            out[k] = v
    return out


def _looks_like_ip(s: str) -> bool:
    """Cheap IPv4 detection. False positives are masked, no harm."""
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or not 0 <= int(p) <= 255:
            return False
    return True
