"""Tests for app.core.diagnostics (v5.7.0 feature #8)."""

from __future__ import annotations

from app.core.diagnostics import (
    ALL_CHECKS,
    CheckResult,
    CheckStatus,
    run_all_checks,
    run_check,
)


class TestRegistry:
    """ALL_CHECKS structure + lookup contract."""

    def test_registry_non_empty(self) -> None:
        # At least the 8 documented checks should be registered.
        assert len(ALL_CHECKS) >= 8

    def test_every_check_has_unique_name(self) -> None:
        names = [c.name for c in ALL_CHECKS]
        assert len(names) == len(set(names)), "duplicate check names"

    def test_documented_checks_present(self) -> None:
        names = {c.name for c in ALL_CHECKS}
        for required in (
            "admin", "windivert", "npcap", "clumsy",
            "wifi_adapter", "update_pubkey", "data_directory", "secret_store",
            "persistence_key", "audit_chain", "firewall", "episode_store",
        ):
            assert required in names, f"missing check: {required}"


class TestRunAllChecks:
    """run_all_checks — returns list, every entry is CheckResult."""

    def test_returns_one_result_per_check(self) -> None:
        results = run_all_checks()
        assert len(results) == len(ALL_CHECKS)

    def test_every_result_is_valid(self) -> None:
        for r in run_all_checks():
            assert isinstance(r, CheckResult)
            assert r.name
            assert r.status in (
                CheckStatus.PASS, CheckStatus.WARN, CheckStatus.FAIL
            )
            assert isinstance(r.message, str)
            assert isinstance(r.fix_hint, str)
            assert isinstance(r.fix_command, str)

    def test_does_not_raise_on_any_check(self) -> None:
        # The whole reason we wrap individual checks in try/except —
        # one failing check must not bring down the whole report.
        run_all_checks()  # must not raise


class TestRunCheck:
    """run_check by name — returns result or None for unknown."""

    def test_known_check_returns_result(self) -> None:
        r = run_check("admin")
        assert r is not None
        assert r.name

    def test_unknown_check_returns_none(self) -> None:
        assert run_check("nonexistent_check_name") is None

    def test_fail_check_includes_fix_hint(self) -> None:
        # If a FAIL check is present in the report, it should also
        # carry a fix_hint — otherwise the wizard can't suggest a fix.
        for r in run_all_checks():
            if r.status == CheckStatus.FAIL:
                assert r.fix_hint, (
                    f"check {r.name!r} is FAIL with no fix_hint — "
                    f"add one or downgrade to WARN"
                )


class TestWifiAdapterDiagnostic:
    """WiFi path troubleshooting output stays specific and private."""

    def test_masks_local_ip_in_message(self, monkeypatch) -> None:
        from app.core import diagnostics
        from app.network import wifi_probe

        monkeypatch.setattr(
            wifi_probe,
            "get_wifi_route_info",
            lambda: wifi_probe.WifiRouteInfo(
                is_wifi=False,
                adapter_name="Ethernet",
                local_ip="192.168.50.123",
                reason="adapter name did not match WiFi indicators",
                psutil_available=True,
            ),
        )

        result = diagnostics._check_wifi_adapter()

        assert result.status == CheckStatus.WARN
        assert "192.168.50.x" in result.message
        assert "192.168.50.123" not in result.message
        assert "passive diagnostic" in result.fix_hint
