"""Release controls must remain internally consistent."""

from scripts.release_preflight import (
    _check_signtool_policy,
    _query_authenticode,
    check_source,
)


def test_release_source_preflight_passes() -> None:
    # Let the preflight derive the expected release from app/__version__.py.
    # Hard-coding the prior release caused every later patch release to fail
    # CI even when all release-controlled files were correctly synchronized.
    assert check_source() == []


def test_signtool_policy_requires_sha256_timestamp(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(
        release_preflight,
        "_read",
        lambda _rel: "signtool sign /f cert.pfx dist\\DupeZ.exe",
    )

    errors = _check_signtool_policy("packaging/build.bat")

    assert errors
    assert "/fd sha256" in errors[0]
    assert "/td sha256" in errors[0]
    assert "/tr" in errors[0]


def test_authenticode_query_non_windows_is_explicit(monkeypatch) -> None:
    from scripts import release_preflight

    monkeypatch.setattr(release_preflight.os, "name", "posix")

    statuses, error = _query_authenticode([])

    assert statuses == {}
    assert "require Windows" in error
