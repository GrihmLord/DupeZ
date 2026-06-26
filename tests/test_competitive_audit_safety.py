"""Keep the current competitive strategy aligned with defensive product use."""

from pathlib import Path


def test_competitive_audit_rejects_offensive_product_priorities() -> None:
    text = Path("docs/competitive_audit.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "explicit non-goals" in text
    assert "server-integrity bypass" in text
    assert "highest priority" not in text
    assert "dupe-reliability instrument" not in text
    assert "maximum cut" not in text
