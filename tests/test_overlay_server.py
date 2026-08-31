"""Tests for app.core.overlay_server (v5.7.1 feature #11)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from app.core.overlay_server import (
    OverlayServer,
    OverlayServerOwner,
    _make_handler_class,
    build_state_snapshot,
)


class FakeEngine:
    _max_cut_state = "severed"
    _packets_processed = 1234
    _packets_dropped = 1200


class FakeController:
    """Mimics controller.disrupted_devices the snapshot reads."""

    def __init__(self, *, with_target: bool = True) -> None:
        if with_target:
            self.disrupted_devices = {
                "10.0.0.5": {
                    "engine": FakeEngine(),
                    "methods": ["drop", "lag"],
                    "params": {"_preset": "Red Disconnect", "direction": "both"},
                    "start_time": 1000.0,
                },
            }
        else:
            self.disrupted_devices = {}


class TestBuildStateSnapshot:
    """Snapshot shape + handling of edge cases."""

    def test_snapshot_has_required_top_level_keys(self) -> None:
        snap = build_state_snapshot(FakeController())
        for key in ("version", "now", "active_targets", "risk_score", "risk_band"):
            assert key in snap

    def test_active_targets_populated(self) -> None:
        snap = build_state_snapshot(FakeController())
        assert len(snap["active_targets"]) == 1
        t = snap["active_targets"][0]
        assert "target_ip" in t
        assert t["cut_state"] == "severed"
        assert t["packets_processed"] == 1234

    def test_empty_controller_yields_empty_targets(self) -> None:
        snap = build_state_snapshot(FakeController(with_target=False))
        assert snap["active_targets"] == []

    def test_controller_without_attr_safe(self) -> None:
        # Defensive: a non-controller object passed in should not crash.
        class NoDict:
            pass
        snap = build_state_snapshot(NoDict())
        assert snap["active_targets"] == []

    def test_snapshot_is_json_serializable(self) -> None:
        # The handler json.dumps it — must round-trip cleanly.
        snap = build_state_snapshot(FakeController())
        s = json.dumps(snap)
        again = json.loads(s)
        assert again["version"] == 1

    def test_slow_risk_refresh_never_blocks_snapshot(self, monkeypatch) -> None:
        from app.core import overlay_server
        from app.core import risk_score

        entered = threading.Event()
        release = threading.Event()

        def slow_score():
            entered.set()
            assert release.wait(2.0)
            return type("Score", (), {"score": 17, "band": "green"})()

        monkeypatch.setattr(risk_score, "compute_risk_score", slow_score)
        monkeypatch.setattr(overlay_server, "_risk_cache_score", None)
        monkeypatch.setattr(overlay_server, "_risk_cache_band", None)
        monkeypatch.setattr(overlay_server, "_risk_cache_at", 0.0)
        monkeypatch.setattr(overlay_server, "_risk_refresh_in_progress", False)

        snapshot = build_state_snapshot(FakeController(with_target=False))

        assert entered.wait(1.0)
        assert snapshot["risk_score"] is None
        assert snapshot["risk_band"] is None
        release.set()
        deadline = time.monotonic() + 2.0
        while overlay_server._risk_refresh_in_progress:
            assert time.monotonic() < deadline
            time.sleep(0.01)


class TestHandlerIsolation:
    """v5.7.0 audit fix: per-instance handler factory."""

    def test_two_handler_classes_have_distinct_controllers(self) -> None:
        ctrl_a = object()
        ctrl_b = object()
        H1 = _make_handler_class(ctrl_a)
        H2 = _make_handler_class(ctrl_b)
        assert H1._controller is ctrl_a
        assert H2._controller is ctrl_b
        assert H1._controller is not H2._controller

    def test_handler_classes_are_distinct_types(self) -> None:
        # If they were the same class, setting _controller on one
        # would affect the other.
        H1 = _make_handler_class(object())
        H2 = _make_handler_class(object())
        assert H1 is not H2


class TestServerLifecycle:
    """Real socket bind — uses an ephemeral port + live HTTP fetch."""

    def test_server_serves_state_endpoint(self) -> None:
        # Pick port 0 → kernel assigns ephemeral. Then read the bound
        # port off the socket so the URL is correct.
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        srv.start()
        # ThreadingHTTPServer stores the actual port in server_address.
        actual_port = srv._server.server_address[1]  # type: ignore
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{actual_port}/state", timeout=2.0
            )
            assert resp.status == 200
            body = json.loads(resp.read())
            assert "active_targets" in body
        finally:
            srv.stop()

    def test_server_serves_overlay_html(self) -> None:
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        srv.start()
        actual_port = srv._server.server_address[1]  # type: ignore
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{actual_port}/overlay.html", timeout=2.0
            )
            assert resp.status == 200
            assert b"DupeZ Overlay" in resp.read()
        finally:
            srv.stop()

    def test_unknown_path_returns_404(self) -> None:
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        srv.start()
        actual_port = srv._server.server_address[1]  # type: ignore
        try:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{actual_port}/nope", timeout=2.0
                )
                assert False, "expected 404"
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            srv.stop()

    def test_double_start_is_idempotent(self) -> None:
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        srv.start()
        srv.start()  # must not raise / rebind
        srv.stop()

    def test_start_returns_true_on_success(self) -> None:
        # v5.7.4: start() must signal success so callers don't report
        # "overlay started" on a failed bind.
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        try:
            assert srv.start() is True
            assert srv.running is True
            assert not srv.base_url.endswith(":0")
            # Second start on an already-running server also returns True.
            assert srv.start() is True
        finally:
            srv.stop()
        assert srv.running is False

    def test_start_returns_false_on_bind_failure(self) -> None:
        # Bind the same port twice — the second start must return False,
        # not silently report success.
        ctrl = FakeController()
        srv1 = OverlayServer(ctrl, host="127.0.0.1", port=0)
        assert srv1.start() is True
        bound_port = srv1._server.server_address[1]  # type: ignore
        srv2 = OverlayServer(ctrl, host="127.0.0.1", port=bound_port)
        try:
            assert srv2.start() is False, (
                "start() must return False when the port is already "
                "in use — callers rely on this to avoid claiming success"
            )
            assert srv2.running is False
        finally:
            srv1.stop()
            srv2.stop()

    def test_double_stop_is_idempotent(self) -> None:
        ctrl = FakeController()
        srv = OverlayServer(ctrl, host="127.0.0.1", port=0)
        srv.start()
        assert srv.stop() is True
        assert srv.stop() is True

    def test_failed_stop_retains_resources_for_retry(self) -> None:
        class Worker:
            ident = 42
            alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                return None

        class BoundServer:
            def __init__(self, worker):
                self.worker = worker
                self.fail_shutdown = True

            def shutdown(self):
                if self.fail_shutdown:
                    raise RuntimeError("simulated shutdown failure")
                self.worker.alive = False

            def server_close(self):
                return None

        worker = Worker()
        bound = BoundServer(worker)
        srv = OverlayServer(FakeController(), port=0)
        ready = threading.Event()
        ready.set()
        srv._server = bound  # type: ignore[assignment]
        srv._thread = worker  # type: ignore[assignment]
        srv._ready = ready
        srv._serve_failed = threading.Event()

        assert srv.stop() is False
        assert srv.owns_resources is True
        assert srv._server is bound
        assert srv._thread is worker

        bound.fail_shutdown = False
        assert srv.stop() is True
        assert srv.owns_resources is False

    def test_dead_worker_remains_owned_until_cleanup(self) -> None:
        srv = OverlayServer(FakeController(), host="127.0.0.1", port=0)
        assert srv.start() is True
        server = srv._server
        thread = srv._thread
        assert server is not None and thread is not None

        server.shutdown()
        thread.join(timeout=2.0)

        assert srv.running is False
        assert srv.owns_resources is True
        assert srv.start() is False
        assert srv.stop() is True


class TestServerOwner:
    class StubServer:
        def __init__(self, *_args, **_kwargs):
            self.running = False
            self.owns_resources = True
            self.stop_result = False
            self.start_calls = 0
            self.stop_calls = 0
            self.base_url = "http://127.0.0.1:4778"

        def start(self):
            self.start_calls += 1
            return False

        def stop(self):
            self.stop_calls += 1
            return self.stop_result

    def test_failed_start_and_stop_retain_one_authoritative_owner(self) -> None:
        created = []

        def factory(*args, **kwargs):
            server = self.StubServer(*args, **kwargs)
            created.append(server)
            return server

        owner = OverlayServerOwner(FakeController(), server_factory=factory)

        assert owner.start() is False
        assert owner.owned is True
        assert owner.server is created[0]
        assert owner.start() is False
        assert len(created) == 1

        assert owner.stop() is False
        assert owner.server is created[0]
        created[0].stop_result = True
        assert owner.stop() is True
        assert owner.owned is False
        assert owner.server is None

    def test_owner_accepts_start_only_when_worker_is_live(self) -> None:
        class MisreportingServer(self.StubServer):
            def start(self):
                self.start_calls += 1
                return True

        owner = OverlayServerOwner(
            FakeController(),
            server_factory=MisreportingServer,
        )

        assert owner.start() is False
        assert owner.owned is True
