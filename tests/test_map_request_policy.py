from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl

from app.gui.map_host.request_policy import (
    AdBlockInterceptor,
    is_reviewed_map_url,
)


class _RequestInfo:
    def __init__(self, url: str) -> None:
        self._url = QUrl(url)
        self.blocked = False

    def requestUrl(self) -> QUrl:  # noqa: N802
        return self._url

    def block(self, blocked: bool) -> None:
        self.blocked = bool(blocked)


def test_reviewed_map_navigation_rejects_non_https_and_foreign_hosts() -> None:
    assert is_reviewed_map_url("https://izurvive.com/chernarusplussatmap")
    assert is_reviewed_map_url("https://www.izurvive.com/livonia")
    assert not is_reviewed_map_url("http://izurvive.com/livonia")
    assert not is_reviewed_map_url("https://izurvive.com.evil.example/livonia")
    assert not is_reviewed_map_url("https://user@izurvive.com/livonia")
    assert not is_reviewed_map_url("javascript:alert(1)")


def test_shared_interceptor_blocks_tracker_but_allows_map_origin() -> None:
    interceptor = AdBlockInterceptor()
    tracker = _RequestInfo("https://pagead2.googlesyndication.com/pagead/x")
    map_tile = _RequestInfo("https://tiles.izurvive.com/chernarus/1/2/3.png")

    interceptor.interceptRequest(tracker)
    interceptor.interceptRequest(map_tile)

    assert tracker.blocked is True
    assert map_tile.blocked is False
    assert interceptor.blocked_count == 1


def test_child_sets_shared_context_attribute_before_qapplication() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "gui"
        / "map_host"
        / "host.py"
    ).read_text(encoding="utf-8")

    attribute = source.index("AA_ShareOpenGLContexts")
    application = source.index("app = QApplication(qt_argv)")
    assert attribute < application
