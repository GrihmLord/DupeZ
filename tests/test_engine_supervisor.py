"""Process-wide packet owner and unified status tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.firewall.clumsy_network_disruptor import (
    ClumsyNetworkDisruptor,
    ENGINE_AUTO,
    ENGINE_CLUMSY,
)
from app.firewall.disruption_request import DisruptionRequest
from app.firewall.engine_supervisor import (
    EngineOwnershipError,
    PacketEngineSupervisor,
)
from app.firewall.execution_plan import resolve_execution_plan


TARGET = "192.0.2.10"


def _request() -> DisruptionRequest:
    return DisruptionRequest.from_legacy(
        target_id=TARGET,
        filter_string=f"ip.SrcAddr == {TARGET}",
        methods=["lag"],
        params={"direction": "both", "_network_local": True},
    )


def test_supervisor_rejects_second_manager_and_stale_release() -> None:
    supervisor = PacketEngineSupervisor()
    first = ClumsyNetworkDisruptor()
    second = ClumsyNetworkDisruptor()
    request = _request()
    plan = resolve_execution_plan(request)

    supervisor.reserve(first, 1, request, plan)
    with pytest.raises(EngineOwnershipError, match="already owned"):
        supervisor.reserve(second, 1, request, plan)
    assert not supervisor.release(first, 2)
    assert supervisor.snapshot(manager=first, generation=1) is not None
    assert supervisor.release(first, 1)


def test_supervisor_rejects_replacement_capability_mutation() -> None:
    supervisor = PacketEngineSupervisor()
    manager = ClumsyNetworkDisruptor()
    request = _request()
    plan = resolve_execution_plan(request)
    supervisor.reserve(manager, 1, request, plan)

    replacement = DisruptionRequest.from_legacy(
        target_id=TARGET,
        filter_string=f"ip.SrcAddr == {TARGET}",
        methods=["dupez.custom_lag"],
        params={"direction": "both", "_network_local": True},
    )
    with pytest.raises(EngineOwnershipError, match="replacement changed"):
        supervisor.transfer_generation(
            manager,
            1,
            2,
            replacement,
            resolve_execution_plan(replacement),
            pid=None,
            handle_attached=True,
        )
    assert supervisor.snapshot(manager=manager, generation=1) is not None


def test_failed_uncommitted_engine_stop_retains_owner_for_retry() -> None:
    supervisor = PacketEngineSupervisor()
    manager = ClumsyNetworkDisruptor()
    manager._packet_supervisor = supervisor
    manager._initialized = True

    engine = MagicMock()
    engine.alive = True
    engine.stop.side_effect = RuntimeError("still attached")
    manager._start_selected_engine = MagicMock(
        return_value=(engine, ENGINE_CLUMSY, ENGINE_AUTO)
    )
    supervisor.activate = MagicMock(
        side_effect=EngineOwnershipError("activation rejected")
    )

    assert not manager.disconnect_device_clumsy(
        TARGET,
        methods=["lag"],
        params={"direction": "both", "_network_local": True},
        preset="manual",
    )
    assert supervisor.snapshot(manager=manager) is not None
    assert TARGET in manager.disrupted_devices
    assert "did not confirm stop" in (
        manager.disrupted_devices[TARGET]["release_error"]
    )

    engine.stop.side_effect = None
    engine.alive = False
    assert manager.reconnect_device_clumsy(TARGET)
    assert supervisor.snapshot() is None


def test_two_managers_cannot_own_packet_engines_concurrently() -> None:
    supervisor = PacketEngineSupervisor()
    first = ClumsyNetworkDisruptor()
    second = ClumsyNetworkDisruptor()
    first._packet_supervisor = supervisor
    second._packet_supervisor = supervisor
    first._initialized = True
    second._initialized = True

    first_engine = MagicMock()
    first_engine.alive = True
    first_engine.get_stats.return_value = {
        "startup_verified": True,
        "runtime_verified": False,
        "verification_state": "waiting_for_traffic",
    }
    first._start_selected_engine = MagicMock(
        return_value=(first_engine, ENGINE_CLUMSY, ENGINE_AUTO)
    )
    second._start_selected_engine = MagicMock()

    assert first.disconnect_device_clumsy(
        TARGET,
        methods=["lag"],
        params={"direction": "both", "_network_local": True},
        preset="manual",
    )
    assert not second.disconnect_device_clumsy(
        "192.0.2.11",
        methods=["lag"],
        params={"direction": "both", "_network_local": True},
        preset="manual",
    )
    second._start_selected_engine.assert_not_called()

    status = first.get_device_status_clumsy(TARGET)
    assert status["product"] == "DupeZ"
    assert status["lifecycle_state"] == "active"
    assert status["backend"] == ENGINE_CLUMSY
    assert status["capability_ids"] == ["kali.lag"]
    assert status["capture_layer"] == "network"
    assert len(status["filter_hash"]) == 64
    assert status["packet_owner"]["generation"] == status["generation"]

    assert first.reconnect_device_clumsy(TARGET)
    assert supervisor.snapshot() is None
