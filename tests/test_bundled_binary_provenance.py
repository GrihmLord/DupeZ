"""Supply-chain guard for privileged bundled binaries."""

from scripts.verify_bundled_binaries import verify_manifest


def test_bundled_binary_hashes_match_reviewed_manifest() -> None:
    assert verify_manifest() == []
