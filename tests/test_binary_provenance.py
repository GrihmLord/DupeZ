"""Bundled privileged binaries must remain byte- and source-pinned."""

import json

from scripts.verify_bundled_binaries import verify_manifest


def test_bundled_binary_provenance_is_complete_and_current() -> None:
    assert verify_manifest() == []


def test_new_release_binary_without_provenance_fails(tmp_path) -> None:
    release_data = tmp_path / "release-data.json"
    release_data.write_text(
        json.dumps({
            "schema": "dupez.release-data.v1",
            "binaries": [
                "app/firewall/WinDivert.dll",
                "app/firewall/WinDivert64.sys",
                "app/firewall/clumsy.exe",
                "app/firewall/iup.dll",
                "app/firewall/unreviewed.dll",
            ],
        }),
        encoding="utf-8",
    )

    errors = verify_manifest(release_data_path=release_data)

    assert any("unreviewed.dll" in error for error in errors)
