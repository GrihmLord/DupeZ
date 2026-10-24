import json
from pathlib import Path, PurePosixPath

import pytest

from scripts.license_payload import (
    LicensePayloadError,
    build_license_payload,
    validate_license_payload,
)


class _Metadata(dict):
    def get_all(self, key: str):
        value = self.get(key)
        return list(value) if isinstance(value, list) else None


class _Distribution:
    def __init__(self, root: Path, *, name: str = "demo", version: str = "1.0"):
        self.root = root
        self.version = version
        self.metadata = _Metadata({
            "Name": name,
            "License-Expression": "MIT",
            "License-File": ["LICENSE.txt"],
        })
        self.files = [PurePosixPath("demo-1.0.dist-info/licenses/LICENSE.txt")]

    def locate_file(self, relative: PurePosixPath) -> Path:
        return self.root.joinpath(*relative.parts)


def _fixture_root(tmp_path: Path) -> tuple[Path, _Distribution, Path]:
    root = tmp_path / "repo"
    (root / "packaging").mkdir(parents=True)
    (root / "docs" / "legal").mkdir(parents=True)
    (root / "LICENSE.txt").write_text("Project license\n", encoding="utf-8")
    (root / "docs" / "legal" / "SOURCE_AND_RELINK_V5.8.0.md").write_text(
        "Source route\n",
        encoding="utf-8",
    )
    (root / "requirements-locked.txt").write_text(
        "demo==1.0 --hash=sha256:" + "1" * 64 + "\n",
        encoding="utf-8",
    )
    inventory = {
        "schema": "dupez.third-party-components.v1",
        "runtime_lock": "requirements-locked.txt",
        "runtime_components": [{
            "name": "demo",
            "version": "1.0",
            "declared_license": "MIT",
            "metadata_license": "MIT",
            "homepage": "https://example.invalid/demo",
            "fallback_files": [],
            "supplemental_files": [],
        }],
        "additional_components": [{
            "id": "cpython-runtime",
            "name": "CPython",
            "version": "3.13.17",
            "declared_license": "PSF-2.0",
            "homepage": "https://example.invalid/python",
            "source": {
                "type": "python-runtime-license",
                "filename": "LICENSE.txt",
            },
            "supplemental_files": [],
        }],
    }
    (root / "packaging" / "third-party-components.json").write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )
    installed = tmp_path / "site"
    license_path = installed / "demo-1.0.dist-info" / "licenses" / "LICENSE.txt"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("Demo MIT license\n", encoding="utf-8")
    python_license = tmp_path / "python-LICENSE.txt"
    python_license.write_text("Python license\n", encoding="utf-8")
    return root, _Distribution(installed), python_license


def test_license_payload_is_deterministic_and_self_verifying(tmp_path: Path) -> None:
    root, installed, python_license = _fixture_root(tmp_path)
    dist = root / "dist"

    def resolve(name: str):
        assert name == "demo"
        return installed

    build_license_payload(
        root=root,
        dist=dist,
        product_version="5.8.0",
        distribution_resolver=resolve,
        python_license_path=python_license,
    )
    first = {
        path.name: path.read_bytes()
        for path in dist.iterdir()
    }
    build_license_payload(
        root=root,
        dist=dist,
        product_version="5.8.0",
        distribution_resolver=resolve,
        python_license_path=python_license,
    )
    second = {
        path.name: path.read_bytes()
        for path in dist.iterdir()
    }

    assert first == second
    assert validate_license_payload(
        root=root,
        dist=dist,
        expected_version="5.8.0",
    ) == []
    assert str(tmp_path) not in (dist / "THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    )


def test_license_payload_validation_rejects_tampered_notice(tmp_path: Path) -> None:
    root, installed, python_license = _fixture_root(tmp_path)
    dist = root / "dist"
    build_license_payload(
        root=root,
        dist=dist,
        product_version="5.8.0",
        distribution_resolver=lambda _name: installed,
        python_license_path=python_license,
    )
    (dist / "THIRD_PARTY_NOTICES.txt").write_text("tampered\n", encoding="utf-8")

    errors = validate_license_payload(
        root=root,
        dist=dist,
        expected_version="5.8.0",
    )

    assert any("does not match its record" in error for error in errors)
    assert any("omit a recorded source hash" in error for error in errors)


def test_license_payload_rejects_runtime_inventory_drift(tmp_path: Path) -> None:
    root, installed, python_license = _fixture_root(tmp_path)
    inventory_path = root / "packaging" / "third-party-components.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["runtime_components"][0]["version"] = "2.0"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(LicensePayloadError, match="does not exactly match"):
        build_license_payload(
            root=root,
            dist=root / "dist",
            product_version="5.8.0",
            distribution_resolver=lambda _name: installed,
            python_license_path=python_license,
        )
