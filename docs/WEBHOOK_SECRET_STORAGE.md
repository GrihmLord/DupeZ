# Audit webhook credential storage

Audit webhook URLs are bearer credentials. The path, query string, or both can
authorize message delivery, so DupeZ does not store the URL in `settings.json`.

DupeZ stores the URL as `audit.webhook.url` through
`app.core.secret_store`. On Windows this is a CurrentUser DPAPI-sealed value in
the per-user DupeZ secret store. Settings contain only `enabled`, `kind`,
`rate_limit_per_min`, and the non-secret `secret_ref` identifier.

Provision from a terminal with hidden input:

```powershell
python -m app.cli webhook provision --apply
python -m app.cli webhook status
```

For controlled automation, `--url-stdin` reads exactly one line from standard
input. There is deliberately no `--url` argument: command-line arguments are
visible in shell history and process inspection.

Add `--json` for a single machine-readable stdout document. Exit status `0`
means success, `1` means the requested secure operation failed, and `2` means
the command was incomplete or invalid. Internal diagnostic logging is kept out
of JSON stdout, and failures never echo the submitted URL.

At startup, a legacy `audit_webhook.url` value is validated and sealed first.
DupeZ then persists an explicitly disabled, metadata-only configuration and
verifies that the active settings file and rotated settings JSON files are
durably plaintext-free. Only after that verification may it persist the prior
enabled intent and register the sink. A failure restores the prior sanitized
in-memory state; it never restores the legacy URL or activates the sealed copy.
Backup creation and restore also sanitize legacy settings payloads, and
support-bundle sanitization removes URL paths and query strings.

New rotated settings backups are authenticated. An older unsigned rotated file
that needs credential removal is rewritten without the URL but deliberately
remains unsigned, so recovery will not promote otherwise-untrusted settings.

The secret store is intentionally excluded from DupeZ backups. After restoring
settings on a new Windows user or machine, provision the webhook again.

## Historical backups and token rotation

DupeZ cannot prove that backup ZIPs, copied settings files, support attachments,
or snapshots created by an older release have been found and erased. A legacy
archive may still contain the full webhook URL even after the live settings are
migrated. Treat that token as exposed: revoke or rotate it at the webhook
provider, delete old copies according to your retention policy, and provision
the replacement URL through the command above. Sanitizing current files cannot
make deleted sectors, remote copies, or third-party attachments recoverably
secret again.
