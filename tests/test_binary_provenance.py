"""Bundled privileged binaries must remain byte- and source-pinned."""

from scripts.verify_bundled_binaries import verify_manifest


def test_bundled_binary_provenance_is_complete_and_current() -> None:
    assert verify_manifest() == []
