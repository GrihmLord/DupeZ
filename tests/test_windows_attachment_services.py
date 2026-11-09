"""Windows Attachment Services and updater provenance-boundary tests."""

from __future__ import annotations

import ctypes
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.core import windows_attachment


class _RecordingService:
    def __init__(self, events: list[tuple[str, str | None]]) -> None:
        self._events = events

    def set_local_path(self, value: str) -> None:
        self._events.append(("SetLocalPath", value))

    def set_source(self, value: str) -> None:
        self._events.append(("SetSource", value))

    def save(self) -> None:
        self._events.append(("Save", None))


def test_apply_calls_required_methods_in_order_and_proves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "DupeZ_Setup.exe"
    target.write_bytes(b"fixture")
    source = "https://example.com/DupeZ_Setup.exe"
    events: list[tuple[str, str | None]] = []

    @contextmanager
    def fake_factory():
        events.append(("Create", None))
        try:
            yield _RecordingService(events)
        finally:
            events.append(("Release", None))

    monkeypatch.setattr(
        windows_attachment,
        "_create_attachment_services",
        fake_factory,
    )
    monkeypatch.setattr(
        windows_attachment,
        "_read_zone_identifier",
        lambda path: (
            events.append(("ReadEvidence", path))
            or b"[ZoneTransfer]\r\nZoneId=3\r\n"
        ),
    )

    evidence = windows_attachment.apply_attachment_services(str(target), source)

    assert evidence == windows_attachment.AttachmentEvidence(zone_id=3)
    assert events == [
        ("Create", None),
        ("SetLocalPath", str(target)),
        ("SetSource", source),
        ("Save", None),
        ("Release", None),
        ("ReadEvidence", str(target)),
    ]


@pytest.mark.parametrize("failed_method", ["SetLocalPath", "SetSource", "Save"])
def test_apply_fails_closed_on_each_attachment_method_failure(
    failed_method: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "DupeZ_Setup.exe"
    target.write_bytes(b"fixture")
    events: list[str] = []

    class FailingService:
        def _call(self, method: str) -> None:
            events.append(method)
            if method == failed_method:
                raise windows_attachment.AttachmentServicesError(
                    "com_call_failed",
                    f"{method} failed",
                )

        def set_local_path(self, _value: str) -> None:
            self._call("SetLocalPath")

        def set_source(self, _value: str) -> None:
            self._call("SetSource")

        def save(self) -> None:
            self._call("Save")

    @contextmanager
    def fake_factory():
        try:
            yield FailingService()
        finally:
            events.append("Release")

    monkeypatch.setattr(
        windows_attachment,
        "_create_attachment_services",
        fake_factory,
    )
    monkeypatch.setattr(
        windows_attachment,
        "_read_zone_identifier",
        lambda _path: events.append("ReadEvidence") or b"",
    )

    with pytest.raises(
        windows_attachment.AttachmentServicesError,
        match=f"{failed_method} failed",
    ):
        windows_attachment.apply_attachment_services(
            str(target),
            "https://example.com/DupeZ_Setup.exe",
        )

    assert events[-1] == "Release"
    assert "ReadEvidence" not in events
    method_order = ["SetLocalPath", "SetSource", "Save"]
    assert events[:-1] == method_order[: method_order.index(failed_method) + 1]


@pytest.mark.parametrize(
    ("payload", "expected_zone"),
    [
        (b"[ZoneTransfer]\r\nZoneId=3\r\n", 3),
        (b"[ZoneTransfer]\nHostUrl=https://example.com\nZoneId = 4\n", 4),
        (b"\xef\xbb\xbf[ZoneTransfer]\r\nZoneId=3\r\n", 3),
    ],
)
def test_parse_zone_identifier_accepts_only_internet_evidence(
    payload: bytes,
    expected_zone: int,
) -> None:
    assert windows_attachment._parse_zone_identifier(payload).zone_id == expected_zone


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"ZoneId=3\r\n",
        b"[ZoneTransfer]\r\nZoneId=0\r\n",
        b"[ZoneTransfer]\r\nZoneId=1\r\n",
        b"[ZoneTransfer]\r\nZoneId=2\r\n",
        b"[ZoneTransfer]\r\nZoneId=3\r\nZoneId=4\r\n",
        b"[ZoneTransfer]\r\n[Other]\r\nZoneId=3\r\n",
        b"[ZoneTransfer]\r\n[ZoneTransfer]\r\nZoneId=3\r\n",
        b"[ZoneTransfer]\r\nZoneId=999999999999999999999999\r\n",
    ],
)
def test_parse_zone_identifier_rejects_missing_weak_or_ambiguous_evidence(
    payload: bytes,
) -> None:
    with pytest.raises(windows_attachment.AttachmentServicesError) as captured:
        windows_attachment._parse_zone_identifier(payload)
    assert captured.value.reason == "evidence_invalid"


@pytest.mark.parametrize(
    "source",
    [
        "http://example.com/DupeZ_Setup.exe",
        "ftp://example.com/DupeZ_Setup.exe",
        "https://user@example.com/DupeZ_Setup.exe",
        "https://user:secret@example.com/DupeZ_Setup.exe",
        "https://example.com:444/DupeZ_Setup.exe",
        "https://example.com/DupeZ_Setup.exe?token=value",
        "https://example.com/DupeZ_Setup.exe#fragment",
        "https://example.com:invalid/DupeZ_Setup.exe",
    ],
)
def test_source_validation_rejects_ambiguous_or_credential_bearing_urls(
    source: str,
) -> None:
    with pytest.raises(windows_attachment.AttachmentServicesError) as captured:
        windows_attachment._validate_source(source)
    assert captured.value.reason == "invalid_source"


@pytest.mark.parametrize(
    ("delete_target", "expected_reason"),
    [
        (False, "evidence_not_preserved"),
        (True, "file_unavailable_after_scan"),
    ],
)
def test_save_success_without_durable_evidence_fails_closed(
    delete_target: bool,
    expected_reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "DupeZ_Setup.exe"
    target.write_bytes(b"fixture")

    class SaveWithoutEvidence(_RecordingService):
        def save(self) -> None:
            super().save()
            if delete_target:
                target.unlink()

    @contextmanager
    def fake_factory():
        yield SaveWithoutEvidence([])

    monkeypatch.setattr(
        windows_attachment,
        "_create_attachment_services",
        fake_factory,
    )

    with pytest.raises(windows_attachment.AttachmentServicesError) as captured:
        windows_attachment.apply_attachment_services(
            str(target),
            "https://example.com/DupeZ_Setup.exe",
        )
    assert captured.value.reason == expected_reason


def test_non_windows_factory_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows_attachment, "_is_windows", lambda: False)
    with pytest.raises(windows_attachment.AttachmentServicesError) as captured:
        with windows_attachment._create_attachment_services():
            pytest.fail("Attachment Services must not be created off Windows")
    assert captured.value.reason == "unsupported_platform"


@pytest.mark.parametrize(
    ("initialize_result", "expects_uninitialize"),
    [
        (0, True),
        (1, True),
        (0x80010106, False),
    ],
)
def test_com_lifetime_balances_initialization_and_release(
    initialize_result: int,
    expects_uninitialize: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeFunction:
        def __init__(self, callback) -> None:
            self._callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self._callback(*args)

    def initialize(_reserved, mode):
        assert mode == windows_attachment._COINIT_APARTMENTTHREADED
        events.append("CoInitializeEx")
        return initialize_result

    def create(_class_id, _outer, context, _interface_id, output):
        assert context == windows_attachment._CLSCTX_INPROC_SERVER
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 123
        events.append("CoCreateInstance")
        return 0

    class FakeOle32:
        CoInitializeEx = FakeFunction(initialize)
        CoCreateInstance = FakeFunction(create)
        CoUninitialize = FakeFunction(lambda: events.append("CoUninitialize"))

    class FakeAttachmentExecute:
        def __init__(self, pointer) -> None:
            assert pointer.value == 123
            events.append("Interface")

        def release(self) -> None:
            events.append("Release")

    monkeypatch.setattr(windows_attachment, "_is_windows", lambda: True)
    monkeypatch.setattr(
        windows_attachment.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: FakeOle32(),
        raising=False,
    )
    monkeypatch.setattr(
        windows_attachment,
        "_AttachmentExecute",
        FakeAttachmentExecute,
    )

    with windows_attachment._create_attachment_services():
        events.append("Use")

    expected = [
        "CoInitializeEx",
        "CoCreateInstance",
        "Interface",
        "Use",
        "Release",
    ]
    if expects_uninitialize:
        expected.append("CoUninitialize")
    assert events == expected


@pytest.mark.parametrize(
    ("method_name", "arguments", "expected_index"),
    [
        ("set_local_path", (r"C:\staged\DupeZ_Setup.exe",), 5),
        ("set_source", ("https://example.com/DupeZ_Setup.exe",), 7),
        ("save", (), 11),
    ],
)
def test_raw_interface_rejects_nonzero_hresult(
    method_name: str,
    arguments: tuple[str, ...],
    expected_index: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = windows_attachment._AttachmentExecute(ctypes.c_void_p(1))
    calls: list[int] = []

    def fake_method(index, _result_type, *_argument_types):
        calls.append(index)
        return lambda *_args: 0x80004005

    monkeypatch.setattr(service, "_method", fake_method)
    with pytest.raises(windows_attachment.AttachmentServicesError) as captured:
        getattr(service, method_name)(*arguments)
    assert captured.value.reason == "com_call_failed"
    assert "0x80004005" in str(captured.value)
    assert calls == [expected_index]


def test_source_policy_pins_com_contract_and_post_save_verification() -> None:
    helper_source = Path(windows_attachment.__file__).read_text(encoding="utf-8")
    assert "4125DD96-E03A-4103-8F70-E0597D803B9C" in helper_source
    assert "73DB1241-1E85-4581-8E4F-A81E1D0F8C57" in helper_source
    local_call = helper_source.index("service.set_local_path(safe_path)")
    source_call = helper_source.index("service.set_source(safe_source)")
    save_call = helper_source.index("service.save()")
    evidence_read = helper_source.index("_read_zone_identifier(safe_path)")
    assert local_call < source_call < save_call < evidence_read

    from app.core import updater

    updater_source = Path(updater.__file__).read_text(encoding="utf-8")
    attachment_call = updater_source.index(
        "                    _apply_windows_attachment_evidence(dest, url)"
    )
    post_save_source = updater_source[attachment_call:]
    manifest_check = post_save_source.index(
        "rescanned_manifest = verify_manifest_and_enforce_monotonic("
    )
    content_check = post_save_source.index(
        "_verify_safe_installer(dest, private_dir, manifest)"
    )
    publisher_check = post_save_source.index(
        "verify_installer_authenticode(dest, manifest)"
    )
    process_cleanup = post_save_source.index("_kill_dupez_processes(")
    assert 0 < manifest_check < content_check < publisher_check < process_cleanup
    launch_lock = post_save_source.index("with _locked_verified_installer(")
    evidence_recheck = post_save_source.index(
        "_verify_windows_attachment_evidence(dest)",
        launch_lock,
    )
    spawn = post_save_source.index("safe_subprocess.spawn_detached(", launch_lock)
    assert launch_lock < evidence_recheck < spawn


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows Attachment Services integration requires Windows",
)
def test_windows_attachment_services_records_zone_evidence(tmp_path: Path) -> None:
    probe = tmp_path / "ads-volume-probe.txt"
    probe.write_bytes(b"probe")
    probe_stream = f"{probe}:dupez-ads-probe"
    try:
        with open(probe_stream, "wb") as stream:
            stream.write(b"supported")
        with open(probe_stream, "rb") as stream:
            assert stream.read() == b"supported"
    except OSError as exc:
        error_code = getattr(exc, "winerror", None) or exc.errno or "unknown"
        pytest.skip(
            "Windows Attachment Services integration requires NTFS alternate "
            f"data streams (error {error_code})"
        )

    target = tmp_path / "attachment-services-integration.txt"
    target.write_bytes(b"harmless Attachment Services integration fixture")
    try:
        evidence = windows_attachment.apply_attachment_services(
            str(target),
            "https://example.com/DupeZ_Setup.exe",
        )
    except windows_attachment.AttachmentServicesError as exc:
        pytest.skip(
            "Windows Attachment Services is unavailable or attachment-zone "
            f"persistence is disabled on this host ({exc.reason})"
        )

    assert evidence.zone_id in {3, 4}
    recorded = windows_attachment._read_zone_identifier(str(target))
    assert b"[ZoneTransfer]" in recorded
    assert f"ZoneId={evidence.zone_id}".encode("ascii") in recorded
