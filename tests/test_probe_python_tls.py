from __future__ import annotations

from copy import deepcopy
import ssl

import pytest

from scripts import probe_python_tls as probe


def successful_results():
    return [
        {"case": "trusted", "certificate_verified": True, "payload_verified": True, "http_status": 200,
         "server": {"http_request_received": True, "protocol": "TLSv1.3"}},
        {"case": "untrusted", "certificate_verified": False, "payload_verified": False,
         "error_type": "SSLCertVerificationError", "verification_code": 20,
         "server": {"http_request_received": False}},
        {"case": "wrong-host", "certificate_verified": False, "payload_verified": False,
         "error_type": "SSLCertVerificationError", "verification_code": 64,
         "server": {"http_request_received": False}},
    ]


def test_requires_verified_payload_and_both_certificate_rejections():
    probe.validate_results(successful_results())


@pytest.mark.parametrize("index,field,value", [
    (0, "certificate_verified", False), (0, "certificate_verified", 1),
    (0, "payload_verified", False), (0, "http_status", 500),
    (0, "server", {"protocol": "TLSv1.1", "http_request_received": True}),
    (1, "certificate_verified", True), (1, "payload_verified", True),
    (1, "verification_code", 64), (1, "error_type", "TimeoutError"),
    (1, "server", {"http_request_received": True}),
    (2, "verification_code", 20), (2, "payload_verified", True),
])
def test_rejects_false_positive_or_wrong_negative_control(index, field, value):
    results = deepcopy(successful_results())
    results[index][field] = value
    with pytest.raises(RuntimeError):
        probe.validate_results(results)


def test_rejects_missing_or_reordered_controls():
    with pytest.raises(RuntimeError):
        probe.validate_results(successful_results()[:2])
    with pytest.raises(RuntimeError):
        probe.validate_results(list(reversed(successful_results())))


def test_certificate_error_requires_actual_exception_not_error_text():
    certificate = ssl.SSLCertVerificationError("controlled error")
    inner = RuntimeError(certificate)
    outer = RuntimeError("wrapper")
    outer.reason = inner
    inner.__cause__ = outer  # A wrapper cycle must not hang inspection.
    assert probe.certificate_error(outer) is certificate
    assert probe.certificate_error(RuntimeError("SSLCertVerificationError verify_code=20")) is None
