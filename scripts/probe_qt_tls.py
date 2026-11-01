#!/usr/bin/env python3
"""Exercise Qt Schannel with local TLS peers; never change the system trust store.

Run with an isolated candidate interpreter and a sanitized environment. This
probe checks real TLS handshakes, certificate rejection and hostname rejection.
It is local runtime evidence, not a release or public-service compatibility gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading


def make_certificates(directory: Path) -> tuple[Path, Path, bytes]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DupeZ local probe CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca_name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert, private = directory / "peer.pem", directory / "peer-key.pem"
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    return cert, private, ca.public_bytes(serialization.Encoding.PEM)


def handshake(cert: Path, key: Path, ca: bytes, *, trust: bool, hostname: str) -> dict:
    from PyQt6.QtNetwork import QSsl, QSslCertificate, QSslConfiguration, QSslSocket

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(8)
    port = server.getsockname()[1]
    server_result = {}

    def serve() -> None:
        try:
            with server:
                connection, _ = server.accept()
                connection.settimeout(8)
                with context.wrap_socket(connection, server_side=True) as encrypted:
                    server_result["protocol"] = encrypted.version()
                    encrypted.sendall(b"dupez-local-tls-probe\n")
                    encrypted.recv(1)
        except (OSError, ssl.SSLError) as exc:
            server_result["error_type"] = type(exc).__name__

    thread = threading.Thread(target=serve, name="dupez-loopback-tls", daemon=True)
    thread.start()
    client = QSslSocket()
    errors = []
    client.sslErrors.connect(lambda values: errors.extend(error.error().name for error in values))
    config = QSslConfiguration.defaultConfiguration()
    config.setProtocol(QSsl.SslProtocol.TlsV1_2OrLater)
    # Socket-local trust only. Never use setDefaultConfiguration or ignoreSslErrors.
    config.setCaCertificates([QSslCertificate(ca)] if trust else [])
    config.setPeerVerifyMode(QSslSocket.PeerVerifyMode.VerifyPeer)
    client.setSslConfiguration(config)
    client.setPeerVerifyName(hostname)
    received = b""
    try:
        client.connectToHostEncrypted("127.0.0.1", port)
        encrypted = client.waitForEncrypted(5000)
        if encrypted:
            if client.bytesAvailable() or client.waitForReadyRead(3000):
                received = bytes(client.readAll())
        result = {"trusted_probe_ca": trust, "peer_name": hostname,
                  "encrypted": encrypted, "ssl_errors": sorted(set(errors)),
                  "socket_error": client.error().name,
                  "payload_verified": received == b"dupez-local-tls-probe\n"}
    finally:
        client.abort()
        thread.join(10)
        server.close()
    if thread.is_alive():
        raise RuntimeError("Local TLS server did not terminate")
    result["server"] = server_result
    return result


def validate_results(results: list[dict]) -> None:
    if len(results) != 3:
        raise RuntimeError("Expected all three TLS cases")
    trusted, untrusted, wrong_host = results
    if (not trusted["encrypted"] or not trusted["payload_verified"] or trusted["ssl_errors"]
            or trusted["server"].get("protocol") not in {"TLSv1.2", "TLSv1.3"}):
        raise RuntimeError("Trusted local peer failed verified TLS")
    if (untrusted["encrypted"] or untrusted["payload_verified"]
            or not set(untrusted["ssl_errors"]) & {"CertificateUntrusted", "UnableToGetLocalIssuerCertificate",
                                                  "SelfSignedCertificateInChain", "UnableToVerifyFirstCertificate"}):
        raise RuntimeError("Untrusted local peer was not rejected for a certificate error")
    if (wrong_host["encrypted"] or wrong_host["payload_verified"]
            or "HostNameMismatch" not in wrong_host["ssl_errors"]):
        raise RuntimeError("Wrong hostname was not rejected")


def probe(expected_qt: str) -> dict:
    import ctypes
    from PyQt6 import QtCore, QtNetwork

    if sys.platform != "win32" or ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Use a standard-user Windows candidate interpreter")
    if QtCore.qVersion() != expected_qt:
        raise RuntimeError("Unexpected Qt runtime version")
    prefix = Path(sys.prefix).resolve()
    for module in (QtCore, QtNetwork):
        if not Path(module.__file__).resolve().is_relative_to(prefix):
            raise RuntimeError("Qt binding escaped the selected environment")
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    if (QtNetwork.QSslSocket.availableBackends() != ["schannel"]
            or not QtNetwork.QSslSocket.setActiveBackend("schannel")
            or not QtNetwork.QSslSocket.supportsSsl()):
        raise RuntimeError("Expected Schannel-only TLS")
    with tempfile.TemporaryDirectory(prefix="dupez-local-tls-") as temporary:
        cert, key, ca = make_certificates(Path(temporary))
        results = [handshake(cert, key, ca, trust=True, hostname="localhost"),
                   handshake(cert, key, ca, trust=False, hostname="localhost"),
                   handshake(cert, key, ca, trust=True, hostname="wrong.invalid")]
    validate_results(results)
    app.processEvents()
    return {"schema": "dupez.qt-loopback-tls-probe.v1", "status": "passed",
            "observed_at": datetime.now(timezone.utc).isoformat(), "qt_version": expected_qt,
            "python_version": sys.version.split()[0], "backend": QtNetwork.QSslSocket.activeBackend(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cases": results, "trust_store_modified": False,
            "scope": "Loopback TLS only; no public service, HTTP/2, full app or frozen runtime proof"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-qt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Exclusive creation prevents overwriting previous receipts or following an
    # existing symlink. The operator supplies an isolated output directory.
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(probe(args.expected_qt), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
