"""Release controls must remain internally consistent."""

from scripts.release_preflight import check_source


def test_release_source_preflight_passes() -> None:
    assert check_source("5.7.7") == []
