"""Defense-in-depth scope checks in the elevated helper."""

from app.firewall_helper.protocol import (
    ERR_BAD_REQUEST,
    OP_BLOCK_DEVICE,
    OP_DISRUPT_DEVICE,
    Request,
)
from app.firewall_helper.server import HelperDispatcher


class _Manager:
    def __init__(self) -> None:
        self.calls = []

    def disrupt_device(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return True


class _Blocker:
    def __init__(self) -> None:
        self.calls = []

    def block_device(self, ip, block=True):
        self.calls.append((ip, block))
        return True


def test_helper_rejects_public_disruption_target() -> None:
    manager = _Manager()
    dispatcher = HelperDispatcher(manager)

    response = dispatcher.dispatch(Request(
        op=OP_DISRUPT_DEVICE,
        args={"ip": "8.8.8.8", "methods": ["drop"]},
    ))

    assert response.ok is False
    assert response.error_code == ERR_BAD_REQUEST
    assert manager.calls == []


def test_helper_rejects_public_firewall_target() -> None:
    blocker = _Blocker()
    dispatcher = HelperDispatcher(_Manager(), blocker_module=blocker)

    response = dispatcher.dispatch(Request(
        op=OP_BLOCK_DEVICE,
        args={"ip": "8.8.8.8"},
    ))

    assert response.ok is False
    assert response.error_code == ERR_BAD_REQUEST
    assert blocker.calls == []
