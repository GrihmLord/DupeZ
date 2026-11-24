#!/usr/bin/env python3
"""Check requests TLS against loopback peers in the QtNetwork-free environment.

This never contacts a public service or changes the system trust store. It
proves only local certificate and hostname verification in the selected venv,
not frozen execution, binary provenance, or approval to distribute a release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading


SCRIPT_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PAYLOAD = b"dupez-python-loopback-tls\n"


def make_certificates(directory: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Create short-lived, private probe CAs and peers; never install their trust."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)

    def make_ca(label: str):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        return key, cert

    ca_key, ca = make_ca("DupeZ Python TLS local probe CA")
    _unrelated_key, unrelated_ca = make_ca("DupeZ Python TLS unrelated probe CA")
    trusted, unrelated = directory / "trusted-ca.pem", directory / "unrelated-ca.pem"
    trusted.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    unrelated.write_bytes(unrelated_ca.public_bytes(serialization.Encoding.PEM))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = directory / "peer-key.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    peers = []
    for label, san in (
        ("matching", x509.IPAddress(ipaddress.ip_address("127.0.0.1"))),
        ("wrong-host", x509.DNSName("wrong.invalid")),
    ):
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)]))
                .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        path = directory / f"{label}.pem"
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        peers.append(path)
    return trusted, unrelated, private, peers[0], peers[1]


def certificate_error(error: BaseException) -> ssl.SSLCertVerificationError | None:
    """Unwrap requests/urllib3 without using error strings as proof of rejection."""
    pending: list[object] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return current
        if isinstance(current, BaseException):
            pending.extend(current.args)
            pending.extend((current.__cause__, current.__context__, getattr(current, "reason", None)))
    return None


def request_case(cert: Path, key: Path, trust: Path, *, name: str) -> dict:
    import requests

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(8)
    port = server.getsockname()[1]
    server_result: dict[str, object] = {"http_request_received": False}

    def serve() -> None:
        try:
            with server:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(8)
                    with context.wrap_socket(connection, server_side=True) as encrypted:
                        server_result["protocol"] = encrypted.version()
                        received = b""
                        while b"\r\n\r\n" not in received and len(received) < 4096:
                            block = encrypted.recv(4096 - len(received))
                            if not block:
                                break
                            received += block
                        if not received.startswith(b"GET /probe HTTP/1.1\r\n") or b"\r\n\r\n" not in received:
                            raise RuntimeError("Unexpected or oversized local probe request")
                        server_result["http_request_received"] = True
                        header = f"HTTP/1.1 200 OK\r\nContent-Length: {len(PAYLOAD)}\r\nConnection: close\r\n\r\n"
                        encrypted.sendall(header.encode("ascii") + PAYLOAD)
        except (OSError, RuntimeError) as error:
            server_result["error_type"] = type(error).__name__

    thread = threading.Thread(target=serve, name="dupez-python-loopback-tls", daemon=True)
    thread.start()
    result: dict[str, object] = {"case": name, "payload_verified": False, "certificate_verified": False}
    try:
        with requests.Session() as client:
            # Ambient proxy or CA variables must not alter either negative control.
            client.trust_env = False
            try:
                with client.get(f"https://127.0.0.1:{port}/probe", verify=str(trust),
                                timeout=(5, 5), allow_redirects=False, stream=True) as response:
                    payload = response.raw.read(len(PAYLOAD) + 1)
                    result.update(certificate_verified=True, http_status=response.status_code,
                                  payload_verified=response.status_code == 200 and payload == PAYLOAD)
            except requests.exceptions.SSLError as error:
                verified_error = certificate_error(error)
                if verified_error is None:
                    raise RuntimeError("TLS failure did not contain certificate verification evidence") from error
                result.update(error_type=type(verified_error).__name__, verification_code=verified_error.verify_code)
    finally:
        thread.join(10)
        server.close()
    if thread.is_alive():
        raise RuntimeError("Local TLS server did not terminate")
    result["server"] = server_result
    return result


def validate_results(results: list[dict]) -> None:
    if len(results) != 3 or [row.get("case") for row in results] != ["trusted", "untrusted", "wrong-host"]:
        raise RuntimeError("Expected the three distinct loopback TLS controls")
    trusted, untrusted, wrong_host = results
    if (trusted.get("certificate_verified") is not True or trusted.get("payload_verified") is not True
            or trusted.get("http_status") != 200 or "error_type" in trusted
            or trusted.get("server", {}).get("http_request_received") is not True
            or trusted.get("server", {}).get("protocol") not in {"TLSv1.2", "TLSv1.3"}):
        raise RuntimeError("Trusted loopback peer did not complete verified HTTPS")
    for row, codes in ((untrusted, {18, 19, 20, 21}), (wrong_host, {62, 64})):
        if (row.get("certificate_verified") is not False or row.get("payload_verified") is not False
                or row.get("error_type") != "SSLCertVerificationError"
                or row.get("verification_code") not in codes
                or row.get("server", {}).get("http_request_received") is not False):
            raise RuntimeError("Negative TLS control did not reject the expected certificate failure")


def probe() -> dict:
    import ctypes
    import requests
    import urllib3

    if sys.platform != "win32" or ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Use a standard-user Windows candidate interpreter")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Use an isolated candidate environment")
    prefix = Path(sys.prefix).resolve()
    for module in (requests, urllib3):
        if not Path(module.__file__).resolve().is_relative_to(prefix):
            raise RuntimeError("TLS dependency escaped the selected environment")
    if importlib.util.find_spec("PyQt6.QtNetwork") is not None:
        raise RuntimeError("Expected the QtNetwork-free candidate environment")
    defaults = ssl.create_default_context()
    if defaults.check_hostname is not True or defaults.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("Python TLS defaults are not verifying certificates and hostname")
    with tempfile.TemporaryDirectory(prefix="dupez-python-tls-") as temporary:
        trusted, unrelated, key, matching, wrong = make_certificates(Path(temporary))
        results = [request_case(matching, key, trusted, name="trusted"),
                   request_case(matching, key, unrelated, name="untrusted"),
                   request_case(wrong, key, trusted, name="wrong-host")]
    validate_results(results)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != SCRIPT_DIGEST:
        raise RuntimeError("Probe source changed during execution")
    return {
        "schema": "dupez.python-loopback-tls-probe.v1", "status": "passed",
        "observed_at": datetime.now(timezone.utc).isoformat(), "script_sha256": SCRIPT_DIGEST,
        "python_version": sys.version.split()[0], "openssl_version": ssl.OPENSSL_VERSION,
        "requests_version": importlib.metadata.version("requests"),
        "urllib3_version": importlib.metadata.version("urllib3"),
        "qt_network": "absent", "check_hostname": True, "verify_mode": "CERT_REQUIRED",
        "cases": results, "trust_store_modified": False, "release_approval": False,
        "scope": "requests HTTPS loopback only; no public service, loaded DLL provenance, full app or frozen runtime proof",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(probe(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
