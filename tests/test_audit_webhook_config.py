"""Regression tests for secret-backed audit webhook configuration."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from app.core import audit_webhook_config as webhook_config


def _webhook_url() -> str:
    # Construct the bearer-looking suffix so source secret scanners do not
    # mistake this deterministic test value for a provisioned credential.
    return "https://discord.com/api/" + "webhooks/123/unit-test-value"


class _SettingsManager:
    def __init__(self, settings: dict, *, save_result: bool = True) -> None:
        self.settings = settings
        self.save_result = save_result
        self.saved: list[dict] = []

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def save_changes(self, data: dict, force: bool = False) -> bool:
        assert force is True
        self.saved.append(json.loads(json.dumps(data)))
        return self.save_result


def _isolate_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        webhook_config,
        "_scrub_rotated_settings_files",
        lambda _manager: None,
    )
    monkeypatch.setattr(
        webhook_config,
        "_register_with_log_scrubber",
        lambda _url: None,
    )


def test_clear_disables_metadata_before_deleting_sealed_credential(
    monkeypatch,
) -> None:
    _isolate_side_effects(monkeypatch)
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        }
    })
    secret = [_webhook_url().encode("utf-8")]
    events = []

    original_save = manager.save_changes

    def save(data, force=False):
        events.append(f"metadata:{data['audit_webhook']['enabled']}")
        return original_save(data, force=force)

    def delete_secret() -> bool:
        events.append("delete")
        secret.clear()
        return True

    manager.save_changes = save
    monkeypatch.setattr(webhook_config, "_delete_secret", delete_secret)
    monkeypatch.setattr(
        webhook_config,
        "_read_secret",
        lambda: secret[0] if secret else None,
    )

    webhook_config.clear_audit_webhook(manager=manager)

    assert events == ["metadata:False", "delete"]
    assert manager.settings["audit_webhook"] == {
        "enabled": False,
        "kind": "discord",
        "rate_limit_per_min": 12,
    }
    assert _webhook_url() not in json.dumps(manager.settings)


def test_clear_failure_retains_durably_disabled_metadata(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    secret = _webhook_url().encode("utf-8")
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "generic",
            "rate_limit_per_min": 20,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        }
    })
    monkeypatch.setattr(webhook_config, "_delete_secret", lambda: False)
    monkeypatch.setattr(webhook_config, "_read_secret", lambda: secret)

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="remains disabled",
    ):
        webhook_config.clear_audit_webhook(manager=manager)

    assert manager.settings["audit_webhook"]["enabled"] is False
    assert manager.saved[-1]["audit_webhook"]["enabled"] is False
    assert _webhook_url() not in json.dumps(manager.settings)


def test_clear_removes_an_orphan_secret_without_creating_metadata(
    monkeypatch,
) -> None:
    manager = _SettingsManager({"theme": "dark"})
    secret = [b"orphan"]

    def delete_secret() -> bool:
        secret.clear()
        return True

    monkeypatch.setattr(webhook_config, "_delete_secret", delete_secret)
    monkeypatch.setattr(
        webhook_config,
        "_read_secret",
        lambda: secret[0] if secret else None,
    )

    webhook_config.clear_audit_webhook(manager=manager)

    assert manager.settings == {"theme": "dark"}
    assert manager.saved == []


def test_custom_manager_checks_do_not_import_global_persistence(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "app.core.data_persistence", raising=False)
    manager = _SettingsManager({"theme": "dark"})

    webhook_config._scrub_rotated_settings_files(manager)
    webhook_config._verify_durable_settings(manager, manager.settings)

    assert "app.core.data_persistence" not in sys.modules


def test_legacy_url_is_sealed_before_metadata_is_persisted(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({
        "theme": "dark",
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "url": url,
        },
    })
    stored: list[bytes] = []
    monkeypatch.setattr(webhook_config, "_write_secret", stored.append)
    monkeypatch.setattr(
        webhook_config,
        "_read_secret",
        lambda: stored[-1] if stored else None,
    )

    resolved = webhook_config.resolve_audit_webhook(manager=manager)

    assert resolved is not None
    assert resolved.url == url
    assert stored == [url.encode("utf-8")]
    assert len(manager.saved) == 2
    assert manager.saved[0]["audit_webhook"]["enabled"] is False
    assert manager.saved[1]["audit_webhook"]["enabled"] is True
    persisted = manager.saved[-1]["audit_webhook"]
    assert "url" not in persisted
    assert persisted["secret_ref"] == webhook_config.AUDIT_WEBHOOK_SECRET_KIND
    assert url not in json.dumps(manager.settings)


def test_inaccessible_store_leaves_legacy_settings_and_disables_sink(
    monkeypatch,
) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({
        "audit_webhook": {"enabled": True, "url": url},
    })

    def unavailable(_value: bytes) -> None:
        raise PermissionError("secret store unavailable")

    monkeypatch.setattr(webhook_config, "_write_secret", unavailable)

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="not migrated",
    ):
        webhook_config.resolve_audit_webhook(manager=manager)

    assert manager.saved == []
    assert manager.settings["audit_webhook"]["url"] == url


def test_secret_retrieval_uses_metadata_reference_only(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "generic",
            "rate_limit_per_min": 7,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    })
    monkeypatch.setattr(webhook_config, "_read_secret", lambda: url.encode())

    resolved = webhook_config.resolve_audit_webhook(manager=manager)

    assert resolved == webhook_config.AuditWebhookConfiguration(
        enabled=True,
        kind="generic",
        rate_limit_per_min=7,
        url=url,
    )


def test_inaccessible_store_never_returns_runtime_configuration(
    monkeypatch,
) -> None:
    _isolate_side_effects(monkeypatch)
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 30,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    })

    def unavailable() -> bytes | None:
        raise PermissionError("secret store unavailable")

    monkeypatch.setattr(webhook_config, "_read_secret", unavailable)

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="unavailable",
    ):
        webhook_config.resolve_audit_webhook(manager=manager)


def test_failed_metadata_write_never_restores_url_to_memory(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({}, save_result=False)
    stored: list[bytes] = []
    deleted: list[bool] = []
    monkeypatch.setattr(webhook_config, "_read_secret", lambda: None)
    monkeypatch.setattr(webhook_config, "_write_secret", stored.append)
    monkeypatch.setattr(
        webhook_config,
        "_delete_secret",
        lambda: deleted.append(True) or True,
    )

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="metadata-only",
    ):
        webhook_config.provision_audit_webhook(url, manager=manager)

    # The durable disabled commit is required before the fixed secret slot is
    # touched.  A rejected pre-disable save therefore performs no secret I/O.
    assert stored == []
    assert deleted == []
    assert manager.settings == {}
    assert url not in json.dumps(manager.settings)


def test_failed_reprovision_restores_prior_safe_settings_exactly(
    monkeypatch,
) -> None:
    _isolate_side_effects(monkeypatch)
    old_secret = (
        "https://discord.com/api/" + "webhooks/123/previous-secret"
    ).encode()
    new_url = _webhook_url()
    prior = {
        "theme": "dark",
        "audit_webhook": {
            "enabled": False,
            "kind": "generic",
            "rate_limit_per_min": 7,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    }
    manager = _SettingsManager(json.loads(json.dumps(prior)), save_result=False)
    writes: list[bytes] = []
    monkeypatch.setattr(webhook_config, "_read_secret", lambda: old_secret)
    monkeypatch.setattr(webhook_config, "_write_secret", writes.append)

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="metadata-only",
    ):
        webhook_config.provision_audit_webhook(new_url, manager=manager)

    assert writes == []
    assert manager.settings == prior
    assert new_url not in json.dumps(manager.settings)

    # A later unrelated save and resolve both observe the exact old, disabled
    # configuration rather than the failed candidate.
    manager.save_result = True
    assert manager.save_changes(manager.settings, force=True)
    assert manager.saved[-1] == prior
    assert webhook_config.resolve_audit_webhook(manager=manager) is None


def test_failed_reprovision_sanitizes_legacy_rollback_state(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    legacy_url = (
        "https://discord.com/api/" + "webhooks/123/legacy-secret"
    )
    new_url = _webhook_url()
    original = {
        "theme": "light",
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "url": legacy_url,
        },
    }
    manager = _SettingsManager(
        json.loads(json.dumps(original)),
        save_result=False,
    )
    old_secret = b"previously-sealed-value"
    writes: list[bytes] = []
    monkeypatch.setattr(webhook_config, "_read_secret", lambda: old_secret)
    monkeypatch.setattr(webhook_config, "_write_secret", writes.append)

    with pytest.raises(webhook_config.AuditWebhookSecretError):
        webhook_config.provision_audit_webhook(new_url, manager=manager)

    expected = webhook_config.sanitize_settings_document(
        original,
        disable_if_secret_removed=True,
    )
    assert manager.settings == expected
    assert manager.settings["audit_webhook"]["enabled"] is False
    assert "secret_ref" not in manager.settings["audit_webhook"]
    assert legacy_url not in json.dumps(manager.settings)
    assert new_url not in json.dumps(manager.settings)
    assert writes == []

    manager.save_result = True
    assert manager.save_changes(manager.settings, force=True)
    assert webhook_config.resolve_audit_webhook(manager=manager) is None


def test_legacy_scrub_failure_keeps_sealed_secret_disabled(monkeypatch) -> None:
    url = _webhook_url()
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "url": url,
        },
    })
    sealed: list[bytes] = []
    reads: list[bool] = []
    monkeypatch.setattr(webhook_config, "_write_secret", sealed.append)

    def read_secret() -> bytes | None:
        reads.append(True)
        return sealed[-1] if sealed else None

    def fail_scrub(_manager) -> None:
        raise webhook_config.AuditWebhookSecretError(
            "rotated settings plaintext scrub failed durable verification"
        )

    monkeypatch.setattr(webhook_config, "_read_secret", read_secret)
    monkeypatch.setattr(webhook_config, "_scrub_rotated_settings_files", fail_scrub)
    monkeypatch.setattr(webhook_config, "_register_with_log_scrubber", lambda _url: None)

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="durable verification",
    ):
        webhook_config.resolve_audit_webhook(manager=manager)

    assert sealed == [url.encode()]
    assert reads == []
    assert manager.saved[0]["audit_webhook"]["enabled"] is False
    assert manager.settings["audit_webhook"]["enabled"] is False
    assert "url" not in manager.settings["audit_webhook"]
    assert "secret_ref" not in manager.settings["audit_webhook"]

    # Once the failed operation returns, later resolution cannot consume the
    # sealed value because the restored safe state remains disabled.
    monkeypatch.setattr(
        webhook_config,
        "_scrub_rotated_settings_files",
        lambda _manager: None,
    )
    assert webhook_config.resolve_audit_webhook(manager=manager) is None
    assert reads == []


def test_legacy_enable_commit_failure_restores_disabled_commit(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "url": url,
        },
    })
    sealed: list[bytes] = []
    reads: list[bool] = []
    monkeypatch.setattr(webhook_config, "_write_secret", sealed.append)

    def read_secret() -> bytes | None:
        reads.append(True)
        return sealed[-1] if sealed else None

    monkeypatch.setattr(webhook_config, "_read_secret", read_secret)

    def sequenced_save(data: dict, force: bool = False) -> bool:
        assert force is True
        manager.saved.append(json.loads(json.dumps(data)))
        return len(manager.saved) in {1, 3}

    manager.save_changes = sequenced_save

    with pytest.raises(webhook_config.AuditWebhookSecretError):
        webhook_config.resolve_audit_webhook(manager=manager)

    assert [
        saved["audit_webhook"]["enabled"] for saved in manager.saved
    ] == [False, True, False]
    assert manager.settings["audit_webhook"]["enabled"] is False
    assert manager.settings["audit_webhook"]["secret_ref"] == (
        webhook_config.AUDIT_WEBHOOK_SECRET_KIND
    )
    assert reads == []
    assert webhook_config.resolve_audit_webhook(manager=manager) is None
    assert reads == []


def test_disabling_legacy_webhook_never_commits_enabled_state(monkeypatch) -> None:
    _isolate_side_effects(monkeypatch)
    url = _webhook_url()
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 12,
            "url": url,
        },
    })
    sealed: list[bytes] = []
    reads: list[bool] = []
    monkeypatch.setattr(webhook_config, "_write_secret", sealed.append)
    monkeypatch.setattr(
        webhook_config,
        "_read_secret",
        lambda: reads.append(True) or sealed[-1],
    )

    webhook_config.configure_audit_webhook_enabled(False, manager=manager)

    assert sealed == [url.encode()]
    assert reads == []
    assert manager.saved
    assert all(
        saved["audit_webhook"]["enabled"] is False
        for saved in manager.saved
    )
    assert manager.settings["audit_webhook"]["enabled"] is False
    assert "url" not in manager.settings["audit_webhook"]


def test_settings_serialization_guard_never_writes_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    monkeypatch.setattr(data_persistence, "_compute_hmac", lambda _raw: "a" * 96)
    monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_args: True)
    persistence = data_persistence.DataPersistenceManager(
        data_persistence.PersistenceConfig(
            data_directory=str(tmp_path),
            backup_enabled=False,
        )
    )
    url = _webhook_url()

    assert persistence.save_data(
        "settings",
        {"audit_webhook": {"enabled": True, "url": url}},
        force=True,
    )

    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert url not in raw
    assert "\"url\"" not in raw


def test_settings_rotation_never_copies_legacy_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    monkeypatch.setattr(data_persistence, "_compute_hmac", lambda _raw: "a" * 96)
    monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_args: True)
    url = _webhook_url()
    current = tmp_path / "settings.json"
    current.write_text(
        json.dumps({"audit_webhook": {"enabled": True, "url": url}}),
        encoding="utf-8",
    )
    current.with_suffix(".hmac").write_text(
        data_persistence._compute_hmac(current.read_bytes()),
        encoding="ascii",
    )
    persistence = data_persistence.DataPersistenceManager(
        data_persistence.PersistenceConfig(
            data_directory=str(tmp_path),
            backup_enabled=True,
        )
    )

    assert persistence.save_data("settings", {"theme": "dark"}, force=True)

    rotated = list(tmp_path.glob("settings.backup.*.json"))
    assert len(rotated) == 1
    assert url not in rotated[0].read_text(encoding="utf-8")
    assert rotated[0].with_suffix(".hmac").is_file()


def test_rotated_settings_are_scrubbed_after_migration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    url = _webhook_url()
    backup = tmp_path / "settings.backup.1.json"
    backup.write_text(
        json.dumps({"audit_webhook": {"enabled": True, "url": url}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        tmp_path,
    )

    webhook_config._scrub_rotated_settings_files(
        data_persistence.settings_manager,
    )

    scrubbed = backup.read_text(encoding="utf-8")
    assert url not in scrubbed
    assert json.loads(scrubbed)["audit_webhook"]["enabled"] is False


def test_rotated_scrub_uses_authenticated_journal_not_stale_safe_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    monkeypatch.setattr(data_persistence, "_compute_hmac", lambda _raw: "a" * 96)
    monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_args: True)
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        tmp_path,
    )
    backup = tmp_path / "settings.backup.1.json"
    url = _webhook_url()
    committed = {
        "theme": "authoritative",
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 13,
            "url": url,
        },
    }
    data_persistence.DataPersistenceManager._replace_authenticated_pair(
        backup,
        json.dumps(committed).encode("utf-8"),
    )

    # Simulate a crash that left an older, apparently safe compatibility
    # projection next to a journal generation that still contains plaintext.
    stale_projection = {
        "theme": "stale-projection",
        "audit_webhook": {
            "enabled": False,
            "kind": "generic",
            "rate_limit_per_min": 2,
        },
    }
    stale_raw = json.dumps(stale_projection).encode("utf-8")
    backup.write_bytes(stale_raw)
    backup.with_suffix(".hmac").write_text("a" * 96, encoding="ascii")

    webhook_config._scrub_rotated_settings_files(
        data_persistence.settings_manager,
    )

    durable = data_persistence.DataPersistenceManager._try_load_json(
        backup,
        require_hmac=True,
    )
    assert durable["theme"] == "authoritative"
    assert durable["audit_webhook"]["enabled"] is False
    assert url not in json.dumps(durable)
    assert url not in backup.read_text(encoding="utf-8")


def test_rotated_scrub_never_promotes_stale_secret_projection_over_journal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    monkeypatch.setattr(data_persistence, "_compute_hmac", lambda _raw: "a" * 96)
    monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_args: True)
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        tmp_path,
    )
    backup = tmp_path / "settings.backup.2.json"
    committed = {
        "theme": "authoritative",
        "audit_webhook": {
            "enabled": False,
            "kind": "generic",
            "rate_limit_per_min": 9,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    }
    data_persistence.DataPersistenceManager._replace_authenticated_pair(
        backup,
        json.dumps(committed).encode("utf-8"),
    )

    url = _webhook_url()
    stale_projection = {
        "theme": "stale-projection",
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 30,
            "transport": {"credentials": {"endpoint_url": url}},
        },
    }
    stale_raw = json.dumps(stale_projection).encode("utf-8")
    backup.write_bytes(stale_raw)
    backup.with_suffix(".hmac").write_text("a" * 96, encoding="ascii")

    webhook_config._scrub_rotated_settings_files(
        data_persistence.settings_manager,
    )

    durable = data_persistence.DataPersistenceManager._try_load_json(
        backup,
        require_hmac=True,
    )
    assert durable == committed
    assert json.loads(backup.read_text(encoding="utf-8")) == committed
    assert url not in backup.read_text(encoding="utf-8")


def test_reprovision_secret_rollback_failure_leaves_metadata_disabled(
    monkeypatch,
) -> None:
    _isolate_side_effects(monkeypatch)
    old_secret = b"previously-sealed-value"
    new_url = _webhook_url()
    new_secret = new_url.encode("utf-8")
    manager = _SettingsManager({
        "audit_webhook": {
            "enabled": True,
            "kind": "discord",
            "rate_limit_per_min": 30,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    })
    slot = {"value": old_secret}
    events: list[str] = []
    save_results = iter((True, False, True))

    def sequenced_save(data: dict, force: bool = False) -> bool:
        assert force is True
        manager.saved.append(json.loads(json.dumps(data)))
        events.append(f"metadata:{data['audit_webhook']['enabled']}")
        return next(save_results)

    def read_secret() -> bytes:
        events.append("secret:read")
        return slot["value"]

    def write_secret(value: bytes) -> None:
        if value == old_secret and slot["value"] == new_secret:
            events.append("secret:rollback-failed")
            raise PermissionError("fixed secret slot rollback failed")
        slot["value"] = value
        events.append("secret:new")

    manager.save_changes = sequenced_save
    monkeypatch.setattr(webhook_config, "_read_secret", read_secret)
    monkeypatch.setattr(webhook_config, "_write_secret", write_secret)

    with pytest.raises(webhook_config.AuditWebhookSecretError):
        webhook_config.provision_audit_webhook(new_url, manager=manager)

    assert events == [
        "secret:read",
        "metadata:False",
        "secret:new",
        "metadata:True",
        "metadata:False",
        "secret:rollback-failed",
    ]
    assert slot["value"] == new_secret
    assert manager.settings["audit_webhook"]["enabled"] is False
    event_count = len(events)
    assert webhook_config.resolve_audit_webhook(manager=manager) is None
    assert len(events) == event_count


def test_post_save_verification_failure_durably_rolls_metadata_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.core import data_persistence

    monkeypatch.setattr(data_persistence, "_compute_hmac", lambda _raw: "a" * 96)
    monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_args: True)
    persistence = data_persistence.persistence_manager
    manager = data_persistence.settings_manager
    monkeypatch.setattr(persistence, "data_directory", tmp_path)
    monkeypatch.setattr(persistence.config, "backup_enabled", False)
    prior = {
        "theme": "dark",
        "audit_webhook": {
            "enabled": False,
            "kind": "generic",
            "rate_limit_per_min": 7,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
        },
    }
    monkeypatch.setattr(manager, "settings", json.loads(json.dumps(prior)))
    assert manager.save_changes(manager.settings, force=True)
    monkeypatch.setattr(
        webhook_config,
        "_scrub_rotated_settings_files",
        lambda _manager: None,
    )
    real_verify = webhook_config._verify_durable_settings
    verify_calls = 0

    def fail_candidate_then_verify_rollback(
        target,
        expected,
    ) -> None:
        nonlocal verify_calls
        verify_calls += 1
        if verify_calls == 1:
            raise webhook_config.AuditWebhookSecretError(
                "forced post-save verification failure"
            )
        real_verify(target, expected)

    monkeypatch.setattr(
        webhook_config,
        "_verify_durable_settings",
        fail_candidate_then_verify_rollback,
    )
    candidate = {
        "enabled": True,
        "kind": "discord",
        "rate_limit_per_min": 30,
        "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
    }

    with pytest.raises(
        webhook_config.AuditWebhookSecretError,
        match="forced post-save verification failure",
    ):
        webhook_config._persist_metadata(manager, candidate)

    durable = data_persistence.DataPersistenceManager._try_load_json(
        tmp_path / "settings.json",
        require_hmac=True,
    )
    assert verify_calls == 2
    assert manager.settings == prior
    assert durable == prior


def test_serializer_rebuilds_malformed_nested_webhook_settings() -> None:
    url = _webhook_url()
    document = {
        "theme": "dark",
        "audit_webhook": {
            "enabled": True,
            "kind": "generic",
            "rate_limit_per_min": 17,
            "secret_ref": webhook_config.AUDIT_WEBHOOK_SECRET_KIND,
            "transport": {"credentials": {"endpoint_url": url}},
            "opaque_authorization": {"bearer": url},
        },
    }

    payload, recognized = webhook_config.sanitize_settings_payload(
        "app/data/settings.json",
        json.dumps(document).encode("utf-8"),
    )

    assert recognized is True
    assert payload is not None
    rebuilt = json.loads(payload)
    assert rebuilt["theme"] == "dark"
    assert rebuilt["audit_webhook"] == {
        "enabled": False,
        "kind": "generic",
        "rate_limit_per_min": 17,
    }
    assert url not in payload.decode("utf-8")

    malformed = webhook_config.sanitize_settings_document({
        "audit_webhook": [{"webhook_url": url}],
    })
    assert malformed == {
        "audit_webhook": {
            "enabled": False,
            "kind": "discord",
            "rate_limit_per_min": 30,
        },
    }
    assert url not in json.dumps(malformed)


def test_no_config_status_probes_unavailable_secret_store(monkeypatch) -> None:
    manager = _SettingsManager({})
    probes: list[bool] = []
    monkeypatch.setattr(
        webhook_config,
        "_probe_secret_store",
        lambda: probes.append(True) or False,
    )
    monkeypatch.setattr(
        webhook_config,
        "_read_secret",
        lambda: pytest.fail("no-config status must not retrieve a secret"),
    )

    status = webhook_config.audit_webhook_status(manager=manager)

    assert probes == [True]
    assert status == {
        "configured": False,
        "enabled": False,
        "kind": None,
        "rate_limit_per_min": None,
        "secret_store_accessible": False,
    }
