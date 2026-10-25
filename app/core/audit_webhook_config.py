"""Secret-backed audit webhook configuration.

Webhook URLs are bearer credentials: the path (and sometimes the query)
contains the token needed to publish messages.  Only non-secret metadata is
allowed in ``settings.json``.  The URL itself is stored through
``app.core.secret_store`` under the current Windows user's DPAPI identity.

The legacy migration is intentionally ordered as a small, retryable
transaction:

1. validate the legacy URL;
2. atomically seal it in the secret store;
3. atomically persist explicitly disabled, metadata-only settings;
4. scrub and verify rotated settings JSON files;
5. persist the prior enabled intent only after the scrub succeeds;
6. retrieve and revalidate the sealed value before enabling the sink.

If any stage fails, no sink is returned.  A failure before step 2 leaves the
legacy settings untouched; a failure after step 2 leaves a recoverable sealed
copy and a disabled, metadata-only in-memory state so a later settings save
cannot write the URL back to disk or activate the half-migrated credential.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.logs.logger import log_info

__all__ = [
    "AUDIT_WEBHOOK_SECRET_KIND",
    "AUDIT_WEBHOOK_SETTINGS_KEY",
    "AuditWebhookConfiguration",
    "AuditWebhookSecretError",
    "audit_webhook_status",
    "clear_audit_webhook",
    "configure_audit_webhook_enabled",
    "provision_audit_webhook",
    "resolve_audit_webhook",
    "sanitize_settings_document",
    "sanitize_settings_payload",
]


AUDIT_WEBHOOK_SETTINGS_KEY = "audit_webhook"
AUDIT_WEBHOOK_SECRET_KIND = "audit.webhook.url"
_SECRET_REFERENCE = AUDIT_WEBHOOK_SECRET_KIND
_SECRET_FIELDS = frozenset({"url", "webhook_url", "endpoint_url"})
_PUBLIC_METADATA_FIELDS = frozenset({
    "enabled",
    "kind",
    "rate_limit_per_min",
    "secret_ref",
})
_VALID_KINDS = frozenset({"discord", "generic"})
_MAX_URL_BYTES = 8192
_MAX_RATE_LIMIT = 600


class AuditWebhookSecretError(RuntimeError):
    """Raised when webhook configuration cannot be handled safely."""


@dataclass(frozen=True)
class AuditWebhookConfiguration:
    """Resolved runtime configuration; ``url`` is never serialized."""

    enabled: bool
    kind: str
    rate_limit_per_min: int
    url: str


def _settings_manager(manager: Any | None) -> Any:
    if manager is not None:
        return manager
    from app.core.data_persistence import settings_manager

    return settings_manager


def _read_secret() -> bytes | None:
    from app.core.secret_store import get_secret

    return get_secret(AUDIT_WEBHOOK_SECRET_KIND)


def _write_secret(value: bytes) -> None:
    from app.core.secret_store import put_secret

    put_secret(AUDIT_WEBHOOK_SECRET_KIND, value)


def _delete_secret() -> bool:
    from app.core.secret_store import delete_secret

    return delete_secret(AUDIT_WEBHOOK_SECRET_KIND)


def _probe_secret_store() -> bool:
    """Return whether the backing store is presently reachable and writable."""
    from app.core.secret_store import check_store_health

    return bool(check_store_health().healthy)


def _register_with_log_scrubber(url: str) -> None:
    """Best-effort registration with the existing in-memory log scrubber."""
    try:
        from app.core.secrets_manager import get_scrubber

        get_scrubber().register(url)
    except Exception:
        pass


def _validate_url(value: object) -> str:
    """Return a normalized, allowlisted URL without logging its value."""
    if not isinstance(value, str):
        raise AuditWebhookSecretError("webhook URL must be text")
    url = value.strip()
    try:
        encoded = url.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuditWebhookSecretError("webhook URL is not valid UTF-8") from exc
    if not encoded or len(encoded) > _MAX_URL_BYTES:
        raise AuditWebhookSecretError(
            f"webhook URL must be between 1 and {_MAX_URL_BYTES} UTF-8 bytes"
        )
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise AuditWebhookSecretError("webhook URL contains control characters")

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise AuditWebhookSecretError("webhook URL is malformed") from exc
    if parsed.username is not None or parsed.password is not None:
        raise AuditWebhookSecretError(
            "webhook URL must not contain username/password user-info"
        )
    if parsed.fragment:
        raise AuditWebhookSecretError("webhook URL must not contain a fragment")

    try:
        from app.core.audit_webhook import _validate_webhook_url

        return _validate_webhook_url(url)
    except AuditWebhookSecretError:
        raise
    except Exception as exc:
        # The public error deliberately excludes ``str(exc)`` because future
        # validators or transports may include the bearer URL in exceptions.
        raise AuditWebhookSecretError(
            "webhook URL failed the scheme or host allowlist policy"
        ) from exc


def _bounded_rate_limit(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AuditWebhookSecretError("webhook rate limit must be an integer") from exc
    if not 1 <= parsed <= _MAX_RATE_LIMIT:
        raise AuditWebhookSecretError(
            f"webhook rate limit must be in [1, {_MAX_RATE_LIMIT}]"
        )
    return parsed


def _public_metadata(raw: object, *, require_reference: bool) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AuditWebhookSecretError("webhook settings metadata must be an object")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AuditWebhookSecretError("webhook enabled flag must be true or false")
    kind = str(raw.get("kind", "discord")).strip().lower()
    if kind not in _VALID_KINDS:
        raise AuditWebhookSecretError("webhook kind must be discord or generic")
    rate_limit = _bounded_rate_limit(raw.get("rate_limit_per_min", 30))
    reference = raw.get("secret_ref")
    if require_reference and enabled and reference != _SECRET_REFERENCE:
        raise AuditWebhookSecretError("webhook secret reference is missing or invalid")
    return {
        "enabled": enabled,
        "kind": kind,
        "rate_limit_per_min": rate_limit,
        "secret_ref": _SECRET_REFERENCE,
    }


def sanitize_settings_document(
    settings: object,
    *,
    disable_if_secret_removed: bool = False,
) -> object:
    """Return a deep copy with webhook credential fields removed.

    This is also used as the persistence layer's last-line serialization
    guard.  It never mutates the caller's object.
    """
    try:
        sanitized = copy.deepcopy(settings)
    except Exception as exc:
        raise AuditWebhookSecretError(
            "settings could not be copied without risking secret persistence"
        ) from exc
    if not isinstance(sanitized, dict):
        return sanitized
    if AUDIT_WEBHOOK_SETTINGS_KEY not in sanitized:
        return sanitized

    raw = sanitized.get(AUDIT_WEBHOOK_SETTINGS_KEY)
    unsafe = not isinstance(raw, Mapping)
    if isinstance(raw, Mapping):
        unsafe = unsafe or any(
            not isinstance(key, str) or key not in _PUBLIC_METADATA_FIELDS
            for key in raw
        )

        enabled_value = raw.get("enabled", False)
        enabled = enabled_value if isinstance(enabled_value, bool) else False
        unsafe = unsafe or not isinstance(enabled_value, bool)

        kind_value = raw.get("kind", "discord")
        if isinstance(kind_value, str):
            kind = kind_value.strip().lower()
        else:
            kind = "discord"
            unsafe = True
        if kind not in _VALID_KINDS:
            kind = "discord"
            unsafe = True

        rate_value = raw.get("rate_limit_per_min", 30)
        if isinstance(rate_value, bool):
            rate_limit = 30
            unsafe = True
        else:
            try:
                rate_limit = int(rate_value)
            except (TypeError, ValueError):
                rate_limit = 30
                unsafe = True
        if not 1 <= rate_limit <= _MAX_RATE_LIMIT:
            rate_limit = 30
            unsafe = True

        reference = raw.get("secret_ref")
        if reference not in (None, _SECRET_REFERENCE):
            unsafe = True
        if enabled and reference != _SECRET_REFERENCE:
            unsafe = True
    else:
        enabled = False
        kind = "discord"
        rate_limit = 30
        reference = None

    # Unknown keys and malformed values are treated as potentially
    # credential-bearing.  Rebuild from the public schema instead of editing
    # the untrusted subtree in place, and fail closed if anything was dropped.
    # ``disable_if_secret_removed`` remains accepted for API compatibility;
    # unsafe credential removal is now always disabling at the serializer
    # boundary.
    if unsafe or disable_if_secret_removed and isinstance(raw, Mapping) and any(
        field in raw for field in _SECRET_FIELDS
    ):
        enabled = False
        reference = None

    rebuilt = {
        "enabled": enabled,
        "kind": kind,
        "rate_limit_per_min": rate_limit,
    }
    if reference == _SECRET_REFERENCE:
        rebuilt["secret_ref"] = _SECRET_REFERENCE
    sanitized[AUDIT_WEBHOOK_SETTINGS_KEY] = rebuilt
    return sanitized


def _document_contains_secret_field(settings: object) -> bool:
    if not isinstance(settings, Mapping):
        return False
    raw = settings.get(AUDIT_WEBHOOK_SETTINGS_KEY)

    def contains(value: object) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and key.lower() in _SECRET_FIELDS:
                    return True
                if contains(nested):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            return any(contains(item) for item in value)
        return False

    return contains(raw)


def sanitize_settings_payload(
    rel_path: str,
    payload: bytes,
) -> tuple[bytes | None, bool]:
    """Sanitize a settings JSON payload destined for backup or restore.

    Returns ``(payload, recognized)``.  ``None`` means the recognized settings
    file was not valid UTF-8 object JSON and must be skipped rather than copied
    into a new support/backup artifact.
    """
    norm = rel_path.replace("\\", "/")
    name = norm.rsplit("/", 1)[-1]
    recognized = (
        norm.startswith(("app/data/", "app/config/"))
        and (
            name == "settings.json"
            or (name.startswith("settings.backup.") and name.endswith(".json"))
        )
    )
    if not recognized:
        return payload, False
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, True
    if not isinstance(document, dict):
        return None, True
    if AUDIT_WEBHOOK_SETTINGS_KEY not in document:
        return payload, True
    sanitized = sanitize_settings_document(
        document,
        disable_if_secret_removed=True,
    )
    if sanitized == document:
        return payload, True
    return (
        json.dumps(sanitized, indent=2, sort_keys=True).encode("utf-8"),
        True,
    )


def _scrub_rotated_settings_files(manager: Any) -> None:
    """Rewrite rotated data-settings copies without webhook credentials."""
    data_persistence = sys.modules.get("app.core.data_persistence")
    if (
        data_persistence is None
        or manager is not getattr(data_persistence, "settings_manager", None)
    ):
        # Test/custom managers have no authoritative persistence root.  Their
        # save contract is still exercised; disk cleanup belongs to the owner.
        # Do not import the global persistence singleton merely to establish
        # that identity: importing it can open the operator's real data store.
        return
    persistence = data_persistence.persistence_manager
    root = Path(persistence.data_directory)
    for path in sorted(root.glob("settings.backup.*.json")):
        try:
            hmac_path = path.with_suffix(".hmac")
            pointer_path = data_persistence.DataPersistenceManager._pointer_path(
                path
            )
            had_authenticated_artifacts = (
                pointer_path.is_file() or hmac_path.is_file()
            )
            authoritative = data_persistence.DataPersistenceManager._try_load_json(
                path,
                require_hmac=True,
            )
            if authoritative is not None:
                if not isinstance(authoritative, dict):
                    data_persistence.DataPersistenceManager._remove_authenticated_state(
                        path
                    )
                    continue
                sanitized_document = sanitize_settings_document(
                    authoritative,
                    disable_if_secret_removed=True,
                )
                if not isinstance(sanitized_document, dict):
                    raise AuditWebhookSecretError(
                        "authenticated settings backup could not be sanitized"
                    )
                sanitized = json.dumps(
                    sanitized_document,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                data_persistence.DataPersistenceManager._replace_authenticated_pair(
                    path,
                    sanitized,
                )
                verified = data_persistence.DataPersistenceManager._try_load_json(
                    path,
                    require_hmac=True,
                )
                if (
                    verified != sanitized_document
                    or _document_contains_secret_field(verified)
                    or path.read_bytes() != sanitized
                ):
                    raise AuditWebhookSecretError(
                        "rotated settings plaintext scrub failed durable verification"
                    )
                continue

            if had_authenticated_artifacts:
                # Never fall back to a projection after an authenticated
                # journal or legacy HMAC has failed verification.  Removing
                # the logical copy is safer than allowing stale plaintext to
                # become authoritative during a later recovery.
                data_persistence.DataPersistenceManager._remove_authenticated_state(
                    path
                )
                continue

            original = path.read_bytes()
            sanitized, _recognized = sanitize_settings_payload(
                f"app/data/{path.name}", original,
            )
            if sanitized is None:
                # A corrupt legacy settings backup is unusable and cannot be
                # proven credential-free.  Remove the logical copy.
                path.unlink(missing_ok=True)
                hmac_path.unlink(missing_ok=True)
                continue
            if sanitized == original:
                continue

            # Preserve an unsigned historical backup only as a sanitized,
            # explicitly untrusted file. Recovery requires an HMAC and will
            # never promote this copy into live settings.
            tmp = path.with_name(path.name + ".sanitizing.tmp")
            try:
                data_persistence.DataPersistenceManager._write_staged(
                    tmp,
                    sanitized,
                )
                os.replace(tmp, path)
                hmac_path.unlink(missing_ok=True)
                if path.read_bytes() != sanitized or hmac_path.exists():
                    raise AuditWebhookSecretError(
                        "rotated settings plaintext scrub failed durable verification"
                    )
            finally:
                tmp.unlink(missing_ok=True)
        except OSError as exc:
            raise AuditWebhookSecretError(
                "could not scrub a rotated settings file"
            ) from exc


def _sanitized_settings_snapshot(settings: object) -> dict[str, Any]:
    """Return the rollback state for a metadata transaction.

    Existing non-secret settings are preserved exactly.  If the input still
    contains a legacy bearer URL, the snapshot removes it and disables that
    webhook so a failed migration can never put plaintext or a half-migrated
    enabled configuration back into process memory.
    """
    snapshot = sanitize_settings_document(
        settings,
        disable_if_secret_removed=True,
    )
    if not isinstance(snapshot, dict):
        raise AuditWebhookSecretError("application settings are not an object")
    return snapshot


def _verify_durable_settings(manager: Any, expected: Mapping[str, Any]) -> None:
    """Verify the global manager's exact HMAC-authenticated settings document."""
    data_persistence = sys.modules.get("app.core.data_persistence")
    if (
        data_persistence is None
        or manager is not getattr(data_persistence, "settings_manager", None)
    ):
        # Custom managers expose only the save_changes contract.  Their owner
        # is responsible for durable verification.  Avoid importing the
        # process-global manager for an identity check because its constructor
        # legitimately opens the current user's persistent settings.
        return

    path = Path(data_persistence.persistence_manager.data_directory) / "settings.json"
    durable = data_persistence.DataPersistenceManager._try_load_json(
        path,
        require_hmac=True,
    )
    if (
        not isinstance(durable, dict)
        or durable != dict(expected)
        or _document_contains_secret_field(durable)
    ):
        raise AuditWebhookSecretError(
            "metadata-only webhook settings failed durable verification"
        )


def _persist_metadata(manager: Any, metadata: Mapping[str, Any]) -> None:
    previous_settings = _sanitized_settings_snapshot(manager.settings)
    candidate_settings = copy.deepcopy(previous_settings)
    candidate_settings[AUDIT_WEBHOOK_SETTINGS_KEY] = dict(metadata)

    try:
        # Install only a credential-free candidate before calling arbitrary
        # manager I/O.  On every failure path memory is restored to the exact
        # prior sanitized snapshot below.
        manager.settings = candidate_settings
        try:
            saved = manager.save_changes(candidate_settings, force=True)
        except Exception as exc:
            raise AuditWebhookSecretError(
                "could not persist metadata-only webhook settings"
            ) from exc
        if saved is False:
            raise AuditWebhookSecretError(
                "could not persist metadata-only webhook settings"
            )

        _scrub_rotated_settings_files(manager)
        _verify_durable_settings(manager, candidate_settings)
    except Exception as exc:
        # A successful save followed by scrub/verification failure may have
        # already committed the candidate to the authenticated journal.  A
        # memory-only restore would resurrect that candidate on restart, so
        # write and verify the prior sanitized document before returning.
        manager.settings = previous_settings
        try:
            rollback_saved = manager.save_changes(previous_settings, force=True)
            if rollback_saved is False:
                raise AuditWebhookSecretError(
                    "prior webhook metadata rollback save was rejected"
                )
            _verify_durable_settings(manager, previous_settings)
        except Exception as rollback_exc:
            manager.settings = previous_settings
            raise AuditWebhookSecretError(
                "metadata-only webhook settings failed and prior metadata "
                "rollback could not be durably verified"
            ) from rollback_exc

        manager.settings = previous_settings
        if isinstance(exc, AuditWebhookSecretError):
            raise exc
        raise AuditWebhookSecretError(
            "could not persist metadata-only webhook settings"
        ) from exc


def _migrate_legacy(
    manager: Any,
    raw: Mapping[str, Any],
    *,
    enable_after_scrub: bool | None = None,
) -> dict[str, Any]:
    present_fields = [field for field in _SECRET_FIELDS if field in raw]
    legacy_values = [raw.get(field) for field in present_fields if raw.get(field)]
    if legacy_values and any(
        value != legacy_values[0] for value in legacy_values[1:]
    ):
        raise AuditWebhookSecretError(
            "conflicting legacy webhook credential fields were found"
        )
    legacy_url = legacy_values[0] if legacy_values else None
    if legacy_url is None and not present_fields:
        return _public_metadata(raw, require_reference=True)

    if legacy_url is None:
        metadata = _public_metadata(raw, require_reference=False)
        metadata["enabled"] = False
        _persist_metadata(manager, metadata)
        return metadata

    url = _validate_url(legacy_url)
    metadata = _public_metadata(raw, require_reference=False)
    intended_enabled = (
        metadata["enabled"]
        if enable_after_scrub is None
        else enable_after_scrub
    )
    encoded = url.encode("utf-8")
    try:
        _write_secret(encoded)
    except Exception as exc:
        raise AuditWebhookSecretError(
            "webhook secret store is unavailable; legacy URL was not migrated"
        ) from exc

    # Do not restore the URL to memory after this point.  Keep the migrated
    # configuration disabled until the live and rotated settings documents
    # have been durably scrubbed and verified.  If the later enable commit
    # fails, _persist_metadata restores this disabled state.
    _register_with_log_scrubber(url)
    metadata["enabled"] = False
    _persist_metadata(manager, metadata)
    if intended_enabled:
        enabled_metadata = dict(metadata)
        enabled_metadata["enabled"] = True
        _persist_metadata(manager, enabled_metadata)
        metadata = enabled_metadata
    log_info("Legacy audit webhook URL migrated to the secret store")
    return metadata


def provision_audit_webhook(
    url: str,
    *,
    kind: str = "discord",
    rate_limit_per_min: int = 30,
    enabled: bool = True,
    manager: Any | None = None,
) -> None:
    """Validate and atomically provision a webhook bearer URL."""
    target = _settings_manager(manager)
    normalized_url = _validate_url(url)
    metadata = _public_metadata(
        {
            "enabled": enabled,
            "kind": kind,
            "rate_limit_per_min": rate_limit_per_min,
            "secret_ref": _SECRET_REFERENCE,
        },
        require_reference=True,
    )

    try:
        previous = _read_secret()
    except Exception as exc:
        raise AuditWebhookSecretError(
            "webhook secret store is unavailable; configuration was not changed"
        ) from exc

    # The secret store has one fixed slot for this credential.  Commit and
    # verify a disabled metadata state before overwriting it so a later
    # metadata failure plus secret-rollback failure cannot activate the newly
    # written URL under the prior enabled configuration.
    disabled_metadata = dict(metadata)
    disabled_metadata["enabled"] = False
    _persist_metadata(target, disabled_metadata)

    try:
        _write_secret(normalized_url.encode("utf-8"))
    except Exception as exc:
        # The write may have failed after replacing the fixed slot.  Restore
        # best-effort, but deliberately keep the durably disabled metadata in
        # either case.
        try:
            if previous is None:
                _delete_secret()
            else:
                _write_secret(previous)
        except Exception:
            pass
        raise AuditWebhookSecretError(
            "webhook secret store is unavailable; configuration remains disabled"
        ) from exc

    _register_with_log_scrubber(normalized_url)
    try:
        _persist_metadata(target, metadata)
    except Exception:
        # The failed enabled commit durably rolls back to ``disabled_metadata``
        # before returning.  Secret restoration is best-effort; failure leaves
        # a new value in the fixed slot, but no enabled metadata can consume it.
        try:
            if previous is None:
                _delete_secret()
            else:
                _write_secret(previous)
        except Exception:
            pass
        raise
    log_info("Audit webhook credential provisioned in the secret store")


def configure_audit_webhook_enabled(
    enabled: bool,
    *,
    manager: Any | None = None,
) -> None:
    """Enable or disable an already-provisioned webhook without exposing it."""
    if not isinstance(enabled, bool):
        raise AuditWebhookSecretError("webhook enabled flag must be true or false")
    target = _settings_manager(manager)
    raw = target.get_setting(AUDIT_WEBHOOK_SETTINGS_KEY, {})
    if not isinstance(raw, Mapping):
        raise AuditWebhookSecretError("webhook settings metadata must be an object")
    metadata = _migrate_legacy(
        target,
        raw,
        enable_after_scrub=enabled,
    )
    if enabled:
        try:
            if _read_secret() is None:
                raise AuditWebhookSecretError(
                    "webhook credential is not provisioned"
                )
        except AuditWebhookSecretError:
            raise
        except Exception as exc:
            raise AuditWebhookSecretError(
                "webhook secret store is unavailable"
            ) from exc
    metadata["enabled"] = enabled
    _persist_metadata(target, metadata)


def clear_audit_webhook(*, manager: Any | None = None) -> None:
    """Disable the webhook and remove its sealed credential.

    Disabled metadata is committed before secret deletion. If deletion cannot
    be verified, no enabled configuration can consume the retained credential.
    """
    target = _settings_manager(manager)
    try:
        raw = target.get_setting(AUDIT_WEBHOOK_SETTINGS_KEY, None)
    except Exception as exc:
        raise AuditWebhookSecretError(
            "webhook configuration could not be read safely"
        ) from exc

    if raw is not None:
        kind = "discord"
        rate_limit = 30
        if isinstance(raw, Mapping):
            try:
                existing = _public_metadata(raw, require_reference=False)
                kind = existing["kind"]
                rate_limit = existing["rate_limit_per_min"]
            except AuditWebhookSecretError:
                pass
        _persist_metadata(
            target,
            {
                "enabled": False,
                "kind": kind,
                "rate_limit_per_min": rate_limit,
            },
        )

    try:
        _delete_secret()
        remaining = _read_secret()
    except Exception as exc:
        raise AuditWebhookSecretError(
            "webhook credential removal could not be verified; configuration "
            "remains disabled"
        ) from exc
    if remaining is not None:
        raise AuditWebhookSecretError(
            "webhook credential removal could not be verified; configuration "
            "remains disabled"
        )
    log_info("Audit webhook credential removed from the secret store")


def resolve_audit_webhook(
    *,
    manager: Any | None = None,
) -> AuditWebhookConfiguration | None:
    """Resolve runtime webhook configuration, migrating legacy settings.

    ``None`` means the webhook is intentionally disabled or unconfigured.
    Store, migration, validation, and integrity failures raise a redacted
    :class:`AuditWebhookSecretError`; callers must not register a sink.
    """
    target = _settings_manager(manager)
    raw = target.get_setting(AUDIT_WEBHOOK_SETTINGS_KEY, None)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise AuditWebhookSecretError("webhook settings metadata must be an object")

    metadata = _migrate_legacy(target, raw)
    _scrub_rotated_settings_files(target)
    if not metadata["enabled"]:
        return None
    try:
        secret = _read_secret()
    except Exception as exc:
        raise AuditWebhookSecretError("webhook secret store is unavailable") from exc
    if secret is None:
        raise AuditWebhookSecretError("webhook credential is not provisioned")
    try:
        url = secret.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditWebhookSecretError("stored webhook credential is invalid") from exc
    url = _validate_url(url)
    _register_with_log_scrubber(url)
    return AuditWebhookConfiguration(
        enabled=True,
        kind=metadata["kind"],
        rate_limit_per_min=metadata["rate_limit_per_min"],
        url=url,
    )


def audit_webhook_status(*, manager: Any | None = None) -> dict[str, Any]:
    """Return a URL-free operator status payload."""
    target = _settings_manager(manager)
    raw = target.get_setting(AUDIT_WEBHOOK_SETTINGS_KEY, None)
    if raw is None:
        try:
            accessible = _probe_secret_store()
        except Exception:
            accessible = False
        return {
            "configured": False,
            "enabled": False,
            "kind": None,
            "rate_limit_per_min": None,
            "secret_store_accessible": accessible,
        }
    try:
        if not _probe_secret_store():
            raise AuditWebhookSecretError("webhook secret store is unavailable")
        metadata = _migrate_legacy(target, raw)
        present = _read_secret() is not None
    except Exception:
        return {
            "configured": False,
            "enabled": False,
            "kind": None,
            "rate_limit_per_min": None,
            "secret_store_accessible": False,
        }
    return {
        "configured": present,
        "enabled": bool(metadata["enabled"] and present),
        "kind": metadata["kind"],
        "rate_limit_per_min": metadata["rate_limit_per_min"],
        "secret_store_accessible": True,
    }
