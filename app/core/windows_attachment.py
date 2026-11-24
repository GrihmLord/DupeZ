"""Windows Attachment Services boundary for downloaded installers.

``IAttachmentExecute.Save`` is a mutation boundary: Windows security providers
may scan, rewrite, quarantine, or delete the file.  This module only establishes
and verifies origin evidence.  The updater remains responsible for reopening
the file and repeating every cryptographic check after this function returns.
"""

from __future__ import annotations

import ctypes
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlsplit
from uuid import UUID

__all__ = [
    "AttachmentEvidence",
    "AttachmentServicesError",
    "apply_attachment_services",
    "verify_attachment_evidence",
]


_CLSID_ATTACHMENT_SERVICES = "4125DD96-E03A-4103-8F70-E0597D803B9C"
_IID_IATTACHMENT_EXECUTE = "73DB1241-1E85-4581-8E4F-A81E1D0F8C57"
_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_INPROC_SERVER = 0x1
_RPC_E_CHANGED_MODE = 0x80010106
_MAX_ZONE_IDENTIFIER_BYTES = 32 * 1024
_COM_CALL = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "_GUID":
        return cls.from_buffer_copy(UUID(value).bytes_le)


@dataclass(frozen=True)
class AttachmentEvidence:
    """Verified Windows zone evidence attached to a local file."""

    zone_id: int


class AttachmentServicesError(RuntimeError):
    """A generic, non-sensitive Attachment Services failure."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _is_windows() -> bool:
    return os.name == "nt"


def _unsigned_hresult(value: int) -> int:
    return ctypes.c_uint32(value).value


def _hresult_error(operation: str, value: int) -> AttachmentServicesError:
    return AttachmentServicesError(
        "com_call_failed",
        f"Windows Attachment Services {operation} failed "
        f"(HRESULT 0x{_unsigned_hresult(value):08X})",
    )


class _AttachmentExecute:
    """Minimal raw ``IAttachmentExecute`` wrapper.

    The vtable slots come from the published interface order: IUnknown's three
    methods are followed by SetClientTitle, SetClientGuid, SetLocalPath,
    SetFileName, SetSource, SetReferrer, CheckPolicy, Prompt, Save, Execute,
    SaveWithUI, and ClearClientState.
    """

    _RELEASE_INDEX = 2
    _SET_LOCAL_PATH_INDEX = 5
    _SET_SOURCE_INDEX = 7
    _SAVE_INDEX = 11

    def __init__(self, pointer: ctypes.c_void_p) -> None:
        if not pointer.value:
            raise AttachmentServicesError(
                "com_activation_failed",
                "Windows Attachment Services returned an empty interface",
            )
        self._pointer = pointer

    def _method(self, index: int, result_type, *argument_types):
        vtable = ctypes.cast(
            self._pointer,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        address = vtable[index]
        if not address:
            raise AttachmentServicesError(
                "com_activation_failed",
                "Windows Attachment Services exposed an incomplete interface",
            )
        return _COM_CALL(
            result_type,
            ctypes.c_void_p,
            *argument_types,
        )(address)

    def _call_string(self, index: int, operation: str, value: str) -> None:
        method = self._method(index, ctypes.c_long, ctypes.c_wchar_p)
        result = int(method(self._pointer, value))
        if result != 0:
            raise _hresult_error(operation, result)

    def set_local_path(self, value: str) -> None:
        self._call_string(self._SET_LOCAL_PATH_INDEX, "SetLocalPath", value)

    def set_source(self, value: str) -> None:
        self._call_string(self._SET_SOURCE_INDEX, "SetSource", value)

    def save(self) -> None:
        method = self._method(self._SAVE_INDEX, ctypes.c_long)
        result = int(method(self._pointer))
        if result != 0:
            raise _hresult_error("Save", result)

    def release(self) -> None:
        if not self._pointer.value:
            return
        method = self._method(self._RELEASE_INDEX, ctypes.c_ulong)
        method(self._pointer)
        self._pointer = ctypes.c_void_p()


@contextmanager
def _create_attachment_services() -> Iterator[_AttachmentExecute]:
    """Initialize COM and yield a fresh Attachment Services interface."""
    if not _is_windows():
        raise AttachmentServicesError(
            "unsupported_platform",
            "Windows Attachment Services are unavailable on this platform",
        )

    try:
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise AttachmentServicesError(
            "com_unavailable",
            "Windows Attachment Services could not be loaded",
        ) from exc

    co_initialize = ole32.CoInitializeEx
    co_initialize.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    co_initialize.restype = ctypes.c_long
    co_uninitialize = ole32.CoUninitialize
    co_uninitialize.argtypes = []
    co_uninitialize.restype = None
    co_create = ole32.CoCreateInstance
    co_create.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    co_create.restype = ctypes.c_long

    initialize_result = int(co_initialize(None, _COINIT_APARTMENTTHREADED))
    initialize_code = _unsigned_hresult(initialize_result)
    initialized_here = initialize_code in {0, 1}
    if not initialized_here and initialize_code != _RPC_E_CHANGED_MODE:
        raise AttachmentServicesError(
            "com_initialization_failed",
            "Windows Attachment Services COM initialization failed "
            f"(HRESULT 0x{initialize_code:08X})",
        )

    interface_pointer = ctypes.c_void_p()
    service: _AttachmentExecute | None = None
    try:
        class_id = _GUID.from_string(_CLSID_ATTACHMENT_SERVICES)
        interface_id = _GUID.from_string(_IID_IATTACHMENT_EXECUTE)
        create_result = int(
            co_create(
                ctypes.byref(class_id),
                None,
                _CLSCTX_INPROC_SERVER,
                ctypes.byref(interface_id),
                ctypes.byref(interface_pointer),
            )
        )
        if create_result != 0 or not interface_pointer.value:
            raise AttachmentServicesError(
                "com_activation_failed",
                "Windows Attachment Services activation failed "
                f"(HRESULT 0x{_unsigned_hresult(create_result):08X})",
            )
        service = _AttachmentExecute(interface_pointer)
        yield service
    finally:
        if service is not None:
            service.release()
        if initialized_here:
            co_uninitialize()


def _validate_local_path(local_path: str) -> str:
    if not isinstance(local_path, str) or not local_path or "\x00" in local_path:
        raise AttachmentServicesError(
            "invalid_path",
            "Attachment Services requires a valid local installer path",
        )
    absolute_path = os.path.abspath(local_path)
    if not os.path.isabs(local_path) or absolute_path != local_path:
        raise AttachmentServicesError(
            "invalid_path",
            "Attachment Services requires an absolute local installer path",
        )
    try:
        path_stat = os.lstat(absolute_path)
    except OSError as exc:
        raise AttachmentServicesError(
            "invalid_path",
            "Attachment Services requires an existing local installer",
        ) from exc
    attributes = int(getattr(path_stat, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or attributes & reparse_flag
    ):
        raise AttachmentServicesError(
            "invalid_path",
            "Attachment Services requires a non-reparse regular file",
        )
    return absolute_path


def _validate_source(source_url: str) -> str:
    if (
        not isinstance(source_url, str)
        or not source_url
        or len(source_url) > 4096
        or any(ord(character) < 0x20 for character in source_url)
    ):
        raise AttachmentServicesError(
            "invalid_source",
            "Attachment Services requires a valid HTTPS source",
        )
    try:
        parsed = urlsplit(source_url)
        port = parsed.port
    except ValueError as exc:
        raise AttachmentServicesError(
            "invalid_source",
            "Attachment Services requires a valid HTTPS source",
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise AttachmentServicesError(
            "invalid_source",
            "Attachment Services requires a credential-free HTTPS source",
        )
    return source_url


def _read_zone_identifier(local_path: str) -> bytes:
    stream_path = f"{local_path}:Zone.Identifier"
    try:
        with open(stream_path, "rb") as stream:
            evidence = stream.read(_MAX_ZONE_IDENTIFIER_BYTES + 1)
    except FileNotFoundError as exc:
        if not os.path.isfile(local_path):
            raise AttachmentServicesError(
                "file_unavailable_after_scan",
                "The installer is unavailable after Windows attachment scanning",
            ) from exc
        raise AttachmentServicesError(
            "evidence_not_preserved",
            "Windows did not preserve attachment zone evidence",
        ) from exc
    except OSError as exc:
        if not os.path.isfile(local_path):
            raise AttachmentServicesError(
                "file_unavailable_after_scan",
                "The installer is unavailable after Windows attachment scanning",
            ) from exc
        raise AttachmentServicesError(
            "evidence_not_preserved",
            "Windows attachment zone evidence could not be read",
        ) from exc
    if len(evidence) > _MAX_ZONE_IDENTIFIER_BYTES:
        raise AttachmentServicesError(
            "evidence_invalid",
            "Windows attachment zone evidence exceeded its safety limit",
        )
    return evidence


def _parse_zone_identifier(evidence: bytes) -> AttachmentEvidence:
    zone_sections = 0
    current_section = b""
    zone_values: list[bytes] = []
    for line_number, raw_line in enumerate(evidence.splitlines()):
        line = raw_line.strip(b" \t")
        if line_number == 0:
            line = line.removeprefix(b"\xef\xbb\xbf")
        if line.startswith(b"[") and line.endswith(b"]"):
            current_section = line[1:-1].strip().lower()
            if current_section == b"zonetransfer":
                zone_sections += 1
            continue
        if current_section != b"zonetransfer" or b"=" not in line:
            continue
        key, value = line.split(b"=", 1)
        if key.strip().lower() == b"zoneid":
            zone_values.append(value.strip())

    if zone_sections != 1:
        raise AttachmentServicesError(
            "evidence_invalid",
            "Windows attachment zone evidence is malformed",
        )
    if len(zone_values) != 1:
        raise AttachmentServicesError(
            "evidence_invalid",
            "Windows attachment zone evidence is ambiguous",
        )
    zone_value = zone_values[0]
    if not zone_value.isdigit() or len(zone_value) > 2:
        raise AttachmentServicesError(
            "evidence_invalid",
            "Windows attachment zone evidence is malformed",
        )
    zone_id = int(zone_value)
    if zone_id not in {3, 4}:
        raise AttachmentServicesError(
            "evidence_invalid",
            "Windows did not classify the attachment as an Internet download",
        )
    return AttachmentEvidence(zone_id=zone_id)


def apply_attachment_services(
    local_path: str,
    source_url: str,
) -> AttachmentEvidence:
    """Apply Attachment Services and prove Internet-zone evidence exists.

    The caller must repeat its content, manifest, and publisher verification
    after this function returns because ``Save`` may invoke security providers
    that modify or delete the local file.
    """
    safe_path = _validate_local_path(local_path)
    safe_source = _validate_source(source_url)
    with _create_attachment_services() as service:
        service.set_local_path(safe_path)
        service.set_source(safe_source)
        service.save()
    return verify_attachment_evidence(safe_path)


def verify_attachment_evidence(local_path: str) -> AttachmentEvidence:
    """Reopen and validate Internet-zone evidence on an existing local file."""
    if (
        isinstance(local_path, str)
        and local_path
        and "\x00" not in local_path
        and os.path.isabs(local_path)
        and not os.path.isfile(local_path)
    ):
        raise AttachmentServicesError(
            "file_unavailable_after_scan",
            "The installer is unavailable after Windows attachment scanning",
        )
    safe_path = _validate_local_path(local_path)
    return _parse_zone_identifier(_read_zone_identifier(safe_path))
