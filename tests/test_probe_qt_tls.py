import copy

import pytest

from scripts.probe_qt_tls import validate_results


def passed_results():
    return [
        {"encrypted": True, "payload_verified": True, "ssl_errors": [], "server": {"protocol": "TLSv1.3"}},
        {"encrypted": False, "payload_verified": False, "ssl_errors": ["CertificateUntrusted"]},
        {"encrypted": False, "payload_verified": False, "ssl_errors": ["HostNameMismatch"]},
    ]


def test_verified_handshake_and_both_negative_controls_pass():
    validate_results(passed_results())


@pytest.mark.parametrize("case,field,value", [
    (0, "encrypted", False), (0, "payload_verified", False),
    (0, "ssl_errors", ["CertificateUntrusted"]), (0, "server", {"protocol": "TLSv1"}),
    (1, "encrypted", True), (1, "payload_verified", True), (1, "ssl_errors", []),
    (1, "ssl_errors", ["HostNameMismatch"]),
    (2, "encrypted", True), (2, "payload_verified", True),
    (2, "ssl_errors", []), (2, "ssl_errors", ["CertificateUntrusted"]),
])
def test_rejects_incomplete_or_wrong_security_observation(case, field, value):
    results = copy.deepcopy(passed_results())
    results[case][field] = value
    with pytest.raises(RuntimeError):
        validate_results(results)


def test_requires_all_cases():
    with pytest.raises(RuntimeError):
        validate_results(passed_results()[:1])
