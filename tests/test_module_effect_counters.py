"""Effect counters used by NativeWinDivertEngine activity telemetry."""

from app.firewall.modules.corrupt import CorruptModule
from app.firewall.modules.disconnect import DisconnectModule
from app.firewall.modules.rst import RSTModule
from app.firewall.native_divert_engine import TCP_FLAG_RST, WINDIVERT_ADDRESS


def test_corrupt_counts_modified_payloads() -> None:
    module = CorruptModule({"tamper_chance": 100})
    packet = bytearray(range(64))
    before = bytes(packet)

    assert module.process(packet, WINDIVERT_ADDRESS(), lambda *_: None) is False
    assert bytes(packet) != before
    assert module.get_stats()["affected"] == 1


def test_rst_counts_modified_tcp_packets() -> None:
    module = RSTModule({"rst_chance": 100})
    packet = bytearray(40)
    packet[0] = 0x45  # IPv4, five-word header
    packet[9] = 6     # TCP
    flags_offset = 20 + 13

    assert module.process(packet, WINDIVERT_ADDRESS(), lambda *_: None) is False
    assert packet[flags_offset] & TCP_FLAG_RST
    assert module.get_stats()["affected"] == 1


def test_disconnect_exposes_common_get_stats_contract() -> None:
    module = DisconnectModule({"disconnect_chance": 100})
    module.process(bytearray(40), WINDIVERT_ADDRESS(), lambda *_: None)
    assert module.get_stats()["dropped"] == 1
