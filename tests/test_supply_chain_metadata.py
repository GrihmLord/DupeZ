from __future__ import annotations

import hashlib
import json
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from scripts import release_preflight
from scripts.sbom import (
    PEP508_MARKER_PROPERTY,
    RELEASE_TARGET_PROPERTY,
    build_sbom,
    parse_lock,
    purl_for,
)
from scripts.vex import build_vex
from scripts.verify_requirements_lock import release_target_metadata
from scripts import vulnerability_review
from scripts.vulnerability_review import build_review


def _pypi_payload(vulnerabilities: list[dict] | None = None) -> dict:
    return {
        "info": {"name": "Requests", "version": "2.34.2"},
        "vulnerabilities": vulnerabilities or [],
    }


def test_vulnerability_review_network_is_origin_bound_and_bounded(
    monkeypatch,
) -> None:
    handler = vulnerability_review._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil") is None

    with pytest.raises(ValueError, match="outside canonical PyPI"):
        vulnerability_review._fetch_json(
            "https://example.invalid/pypi/requests/2.34.2/json",
            timeout=1.0,
            retries=1,
        )

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == vulnerability_review._MAX_PYPI_RESPONSE_BYTES + 1
            return b"x" * size

    class Opener:
        @staticmethod
        def open(_request, *, timeout: float):
            assert timeout == 1.0
            return Response()

    monkeypatch.setattr(
        vulnerability_review,
        "_build_pypi_opener",
        lambda: Opener(),
    )
    with pytest.raises(RuntimeError, match="exceeds size limit"):
        vulnerability_review._fetch_json(
            "https://pypi.org/pypi/requests/2.34.2/json",
            timeout=1.0,
            retries=1,
        )


def test_sbom_parser_projects_lock_onto_canonical_release_target(tmp_path) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        'pywin32==312 ; sys_platform == "win32" and '
        'python_full_version == "3.13.14" \\\n'
        "    --hash=sha256:" + "b" * 64 + "\n"
        'uvloop==0.21.0 ; sys_platform == "linux" \\\n'
        "    --hash=sha256:" + "c" * 64 + "\n",
        encoding="utf-8",
    )

    packages = parse_lock(lock)

    assert [
        (package.name, package.version, package.marker)
        for package in packages
    ] == [
        ("requests", "2.34.2", ""),
        (
            "pywin32",
            "312",
            'sys_platform == "win32" and '
            'python_full_version == "3.13.14"',
        ),
    ]


def test_marker_selection_and_metadata_are_bound_across_artifacts(
    tmp_path,
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    marker = (
        'sys_platform == "win32" and python_full_version == "3.13.14"'
    )
    lock.write_text(
        f"requests==2.34.2 ; {marker} \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        'uvloop==0.21.0 ; sys_platform == "linux" \\\n'
        "    --hash=sha256:" + "b" * 64 + "\n",
        encoding="utf-8",
    )
    requested_urls: list[str] = []

    def affected_lookup(url: str, *, timeout: float) -> dict:
        requested_urls.append(url)
        return _pypi_payload([{
            "id": "CVE-2026-0001",
            "aliases": [],
            "details": "fixture advisory",
            "fixed_in": [],
            "link": "https://example.invalid/CVE-2026-0001",
            "source": "fixture",
            "withdrawn": None,
        }])

    packages = parse_lock(lock)
    sbom = build_sbom(packages, product_version="5.8.0")
    review = build_review(lock, fetch_json=affected_lookup)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    vex = build_vex(
        packages,
        review,
        product_version="5.8.0",
        lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
    )

    assert len(requested_urls) == 1
    assert "/requests/2.34.2/" in requested_urls[0]
    assert [component["name"] for component in sbom["components"]] == [
        "requests"
    ]
    assert sbom["components"][0]["properties"] == [{
        "name": PEP508_MARKER_PROPERTY,
        "value": marker,
    }]
    target_property = next(
        item
        for item in sbom["metadata"]["properties"]
        if item["name"] == RELEASE_TARGET_PROPERTY
    )
    assert json.loads(target_property["value"]) == release_target_metadata()
    assert review["release_target"] == release_target_metadata()
    assert review["dependencies"][0]["marker"] == marker
    assert vex["x-dupez-vulnerability-review"][
        "release_target"
    ] == release_target_metadata()

    del review["dependencies"][0]["marker"]
    with pytest.raises(ValueError, match="marker metadata"):
        build_vex(
            packages,
            review,
            product_version="5.8.0",
            lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
            review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
        )


def test_release_target_rejects_underdetermined_marker_input(tmp_path) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        'requests==2.34.2 ; platform_version >= "10" \\\n'
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not defined by release target"):
        parse_lock(lock)


@pytest.mark.parametrize(
    ("unsupported", "message"),
    (
        (
            "unreviewed @ https://example.invalid/unreviewed.whl \\\n"
            "    --hash=sha256:" + "c" * 64 + "\n",
            "direct URL lock entries",
        ),
        (
            "--hash=sha256:" + "d" * 64 + "\n",
            "orphan lock hash",
        ),
        (
            "unreviewed[feature]==1.0 \\\n"
            "    --hash=sha256:" + "e" * 64 + "\n",
            "lock entry extras",
        ),
    ),
)
def test_supply_chain_parser_rejects_unreviewed_lock_content(
    tmp_path,
    unsupported,
    message,
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        + unsupported,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        parse_lock(lock)


def test_vulnerability_review_rejects_unreviewed_lock_content(tmp_path) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        "unreviewed @ https://example.invalid/unreviewed.whl \\\n"
        "    --hash=sha256:" + "b" * 64 + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="direct URL lock entries"):
        build_review(lock, fetch_json=lambda _url, *, timeout: {})


def test_sbom_serial_is_canonical_uuid() -> None:
    sbom = build_sbom(
        [("requests", "2.34.2", ["a" * 64])],
        product_version="5.8.0",
    )

    serial = sbom["serialNumber"]
    assert serial.startswith("urn:uuid:")
    assert str(uuid.UUID(serial.removeprefix("urn:uuid:"))) in serial
    product = sbom["metadata"]["component"]
    assert product == {
        "type": "application",
        "bom-ref": "pkg:generic/dupez@5.8.0",
        "name": "DupeZ",
        "version": "5.8.0",
        "purl": "pkg:generic/dupez@5.8.0",
    }


def test_clean_vulnerability_review_covers_lock_and_rejects_vex(tmp_path) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )

    def clean_lookup(_url: str, *, timeout: float) -> dict:
        assert timeout == 4.0
        return _pypi_payload()

    review = build_review(lock, timeout=4.0, fetch_json=clean_lookup)
    packages = parse_lock(lock)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="zero-finding review"):
        build_vex(
            packages,
            review,
            product_version="5.8.0",
            lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
            review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
        )

    assert review["dependency_count"] == 1
    assert review["active_vulnerability_count"] == 0
    assert review["dependencies"][0]["purl"] == purl_for(
        "requests", "2.34.2"
    )


def test_active_review_generates_nonempty_vulnerability_specific_vex(
    tmp_path,
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )

    def affected_lookup(_url: str, *, timeout: float) -> dict:
        assert timeout == 4.0
        return _pypi_payload([{
                "id": "CVE-2026-0001",
                "aliases": ["GHSA-test-test-test"],
                "details": "fixture advisory",
                "fixed_in": ["2.34.3"],
                "link": "https://example.invalid/CVE-2026-0001",
                "source": "fixture",
                "withdrawn": None,
        }])

    review = build_review(lock, timeout=4.0, fetch_json=affected_lookup)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    vex = build_vex(
        parse_lock(lock),
        review,
        product_version="5.8.0",
        lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
    )

    assert review["active_vulnerability_count"] == 1
    assert len(vex["statements"]) == 1
    statement = vex["statements"][0]
    assert statement["vulnerability"]["name"] == "CVE-2026-0001"
    assert statement["status"] == "affected"
    assert statement["action_statement"]
    assert statement["products"] == [{
        "@id": "pkg:generic/dupez@5.8.0",
        "subcomponents": [{"@id": purl_for("requests", "2.34.2")}],
    }]
    assert vex["x-dupez-vulnerability-review"][
        "active_vulnerability_count"
    ] == 1


def test_vex_rejects_review_for_different_lock(tmp_path) -> None:
    packages = [("requests", "2.34.2", ["a" * 64])]
    review = {
        "schema": "dupez.python-vulnerability-review.v1",
        "generated_at_utc": "2026-08-12T00:00:00Z",
        "source": "fixture",
        "lock_sha256": "b" * 64,
        "dependency_count": 1,
        "active_vulnerability_count": 0,
        "dependencies": [{
            "name": "requests",
            "version": "2.34.2",
            "purl": purl_for("requests", "2.34.2"),
            "advisories": [],
        }],
        "active_vulnerabilities": [],
    }

    with pytest.raises(ValueError, match="does not match"):
        build_vex(
            packages,
            review,
            product_version="5.8.0",
            lock_sha256="a" * 64,
            review_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({}, "package identity"),
        (
            {
                "info": {"name": "urllib3", "version": "2.34.2"},
                "vulnerabilities": [],
            },
            "package name",
        ),
        (
            {
                "info": {"name": "requests", "version": "2.34.1"},
                "vulnerabilities": [],
            },
            "package version",
        ),
        (
            {
                "info": {"name": "requests", "version": "2.34.2"},
                "vulnerabilities": {},
            },
            "must be a list",
        ),
        (
            {
                "info": {"name": "requests", "version": "2.34.2"},
                "vulnerabilities": [None],
            },
            "must be a JSON object",
        ),
    ),
)
def test_vulnerability_review_rejects_unbound_or_malformed_pypi_response(
    tmp_path,
    payload,
    message,
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        build_review(
            lock,
            fetch_json=lambda _url, *, timeout: payload,
        )


def test_dist_metadata_validation_accepts_clean_review_without_vex(
    tmp_path, monkeypatch
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)
    sbom = build_sbom(
        [("requests", "2.34.2", ["a" * 64])],
        product_version="5.8.0",
    )
    (tmp_path / "DupeZ.sbom.json").write_text(json.dumps(sbom), encoding="utf-8")
    review = build_review(
        lock,
        fetch_json=lambda _url, *, timeout: _pypi_payload(),
    )
    (tmp_path / "DupeZ.vulnerability-review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )

    assert release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    ) == []

    review["generated_at_utc"] = (
        datetime.now(timezone.utc) - timedelta(hours=25)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "DupeZ.vulnerability-review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )
    assert any("older than the 24-hour" in error for error in errors)

    review["generated_at_utc"] = (
        datetime.now(timezone.utc) + timedelta(minutes=6)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "DupeZ.vulnerability-review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )
    assert any("unacceptably in the future" in error for error in errors)


def test_dist_metadata_validation_binds_target_and_true_marker(
    tmp_path,
    monkeypatch,
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    marker = 'sys_platform == "win32" and python_version == "3.13"'
    lock.write_text(
        f"requests==2.34.2 ; {marker} \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n"
        'uvloop==0.21.0 ; sys_platform == "linux" \\\n'
        "    --hash=sha256:" + "b" * 64 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)
    sbom = build_sbom(parse_lock(lock), product_version="5.8.0")
    sbom_path = tmp_path / "DupeZ.sbom.json"
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    review = build_review(
        lock,
        fetch_json=lambda _url, *, timeout: _pypi_payload(),
    )
    review_path = tmp_path / "DupeZ.vulnerability-review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    assert release_preflight._validate_supply_chain_metadata(
        tmp_path,
        "5.8.0",
    ) == []

    del sbom["components"][0]["properties"]
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path,
        "5.8.0",
    )
    assert any("dependency marker metadata" in error for error in errors)

    sbom["components"][0]["properties"] = [{
        "name": PEP508_MARKER_PROPERTY,
        "value": marker,
    }]
    sbom["metadata"]["properties"][0]["value"] = "{}"
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path,
        "5.8.0",
    )
    assert any("wrong release-target metadata" in error for error in errors)

    sbom["metadata"]["properties"][0]["value"] = json.dumps(
        release_target_metadata(),
        sort_keys=True,
        separators=(",", ":"),
    )
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    del review["dependencies"][0]["marker"]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path,
        "5.8.0",
    )
    assert any("dependency marker metadata" in error for error in errors)


def test_dist_metadata_validation_rejects_vex_for_clean_review(
    tmp_path, monkeypatch
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)
    sbom = build_sbom(
        [("requests", "2.34.2", ["a" * 64])],
        product_version="5.8.0",
    )
    (tmp_path / "DupeZ.sbom.json").write_text(json.dumps(sbom), encoding="utf-8")
    review = build_review(
        lock,
        fetch_json=lambda _url, *, timeout: _pypi_payload(),
    )
    (tmp_path / "DupeZ.vulnerability-review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )
    (tmp_path / "DupeZ.vex.json").write_text(
        json.dumps({
            "@context": "https://openvex.dev/ns/v0.2.0",
            "statements": [],
            "x-dupez-vulnerability-review": {},
        }),
        encoding="utf-8",
    )

    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )

    assert any("zero-finding release must omit" in error for error in errors)


def test_dist_metadata_validation_requires_and_binds_vex_for_findings(
    tmp_path, monkeypatch
) -> None:
    lock = tmp_path / "requirements-locked.txt"
    lock.write_text(
        "requests==2.34.2 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_preflight, "ROOT", tmp_path)
    sbom = build_sbom(
        [("requests", "2.34.2", ["a" * 64])],
        product_version="5.8.0",
    )
    (tmp_path / "DupeZ.sbom.json").write_text(json.dumps(sbom), encoding="utf-8")

    def affected_lookup(_url: str, *, timeout: float) -> dict:
        return _pypi_payload([{
                "id": "CVE-2026-0001",
                "aliases": [],
                "details": "fixture advisory",
                "fixed_in": [],
                "link": "https://example.invalid/CVE-2026-0001",
                "source": "fixture",
                "withdrawn": None,
        }])

    review = build_review(lock, fetch_json=affected_lookup)
    review_path = tmp_path / "DupeZ.vulnerability-review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )
    assert any("active findings" in error for error in errors)
    assert any("requires vulnerability-specific" in error for error in errors)

    vex = build_vex(
        parse_lock(lock),
        review,
        product_version="5.8.0",
        lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
    )
    (tmp_path / "DupeZ.vex.json").write_text(json.dumps(vex), encoding="utf-8")
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )

    assert any("active findings" in error for error in errors)
    assert not any("release VEX" in error for error in errors)
    assert not any("DupeZ.vex.json" in error for error in errors)

    vex["statements"][0]["status"] = "under_investigation"
    (tmp_path / "DupeZ.vex.json").write_text(json.dumps(vex), encoding="utf-8")
    errors = release_preflight._validate_supply_chain_metadata(
        tmp_path, "5.8.0"
    )
    assert any("must have affected status" in error for error in errors)
