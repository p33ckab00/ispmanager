# Backup and Restore Runbook

Operational runbook for backing up and restoring `ISP Manager` in production.

## Purpose

This document defines the backup and restore strategy for `ISP Manager` once deployed in a production environment with PostgreSQL on Ubuntu.

It covers:

- database backups
- application file backups
- restore workflow
- validation after restore
- operational recommendations

## Goal

Ensure the system can recover safely from:

- database corruption
- accidental deletion
- failed deployment
- server loss
- operator error
- storage failure

## Scope of Backup

The following components must be considered part of the recoverable system state.

### 1. Database

Primary business-critical component:

- PostgreSQL database

Contains:

- subscribers
- billing records
- payments
- payment allocations
- accounting records
- settings
- router inventory
- notifications
- topology assignments

### 2. Media Files

If used in production, these may include:

- ISP logo
- generated exports
- uploaded assets
- any persistent runtime-created files

### 3. Environment and Deployment Configuration

Examples:

- environment file
- systemd service files
- Nginx site configuration
- deployment scripts

These are not part of the business dataset, but they are important for full recovery.

## What Is Business-Critical

Highest-value data:

- subscribers
- plans
- rate history
- invoices
- payments
- payment allocations
- billing snapshots
- income records
- expense records
- settings

Lower-priority but useful:

- routers
- interfaces
- network node assignments

Usually lower-value and reconstructable:

- temporary OTP records
- volatile telemetry cache
- scheduler execution history
- temporary diagnostics noise

## 1. Backup Strategy

## Recommended Backup Model

Use layered backups:

- logical PostgreSQL backup
- filesystem backup for media/config
- optional VM or volume snapshot

This gives both portability and disaster recovery coverage.

## 2. PostgreSQL Backup Types

### Logical Backup

Use:

- `pg_dump`

Purpose:

- portable backup of the application database
- easiest to restore into a clean PostgreSQL instance

Recommended for:

- daily app backups
- pre-deployment backups
- pre-migration backups

### Physical/Volume-Level Backup

Use:

- VM snapshot
- disk snapshot
- storage-level snapshot

Purpose:

- fast full-system recovery
- complementary protection beyond logical dump

Recommended for:

- infrastructure-level disaster recovery

## 3. Backup Frequency

### Minimum Recommended Cadence

- daily PostgreSQL logical backup
- daily media/config backup
- pre-deployment backup before any risky production change

### Stronger Cadence for Higher Risk

If the business depends heavily on recent financial data:

- more frequent logical dumps
- WAL archiving or PITR strategy later

## 4. Retention Policy

Example retention model:

- daily backups for `7` to `14` days
- weekly backups for `4` to `8` weeks
- monthly backups for several months

Exact retention depends on:

- storage cost
- compliance needs
- acceptable recovery horizon

## 5. Backup Storage Rules

Backups should be:

- stored off the production server
- versioned
- access-controlled
- encrypted if stored externally

Do not rely on:

- only one local copy on the same machine

## 6. Pre-Backup Checklist

Before taking a meaningful backup:

- ensure PostgreSQL is healthy
- verify app is connected normally
- verify storage destination is available
- confirm enough disk space exists

Before a risky deployment or migration:

- take a fresh backup immediately before the change
- confirm backup completion before proceeding

## 7. PostgreSQL Backup Workflow

### Standard Production Backup

Recommended workflow:

1. Generate PostgreSQL logical dump
2. Store dump with timestamped filename
3. Verify backup file exists and is non-empty
4. Copy to secure backup location
5. Log backup result

### Recommended Naming Convention

Use timestamped, environment-aware naming such as:

- `ispmanager-prod-YYYYMMDD-HHMM.sql`

or compressed variants if used operationally.

## 8. Media and Config Backup Workflow

Back up:

- media directory
- environment file
- Nginx config
- systemd service files
- deployment scripts if maintained on server

Reason:

DB restore alone may not be enough to fully recover the production service.

## 9. Pre-Restore Planning

Before restoring, decide:

- is this a test restore or real incident restore
- full restore or partial restore
- same server or alternate server
- replace current DB or restore alongside it for inspection

### Golden Rule

Do not perform a destructive restore on production until you know:

- which backup is correct
- what data you are replacing
- how rollback will work if the restore itself fails

## 10. Restore Scenarios

## Scenario A: Test Restore

Purpose:

- validate backup quality
- prove recovery workflow

Recommended:

- restore into staging or separate PostgreSQL database
- do not overwrite production

## Scenario B: Production Recovery

Purpose:

- recover from outage, corruption, or failed deployment

Requires:

- controlled downtime or maintenance window
- preserved current state if possible
- clear restore target

## Scenario C: Pre-Cutover Validation Restore

Purpose:

- confirm a backup is usable before a high-risk change

Example:

- before PostgreSQL migration
- before schema-risk deployment

## 11. Database Restore Workflow

Recommended restore sequence:

1. Identify target backup
2. Preserve current broken state if forensic value exists
3. Stop app writes
4. Stop scheduler
5. Restore DB into target PostgreSQL instance
6. Reconnect app to restored DB
7. Run validation checks
8. Re-enable services

## 12. Application Restore Workflow

If full service recovery is needed:

1. Restore PostgreSQL
2. Restore media files
3. Restore environment/config files
4. Restore Nginx and service definitions if needed
5. Start PostgreSQL
6. Start Gunicorn
7. Start scheduler
8. Start Nginx
9. Run smoke tests

## 13. Validation After Restore

After restore, confirm:

- app starts successfully
- login works
- dashboard loads
- subscribers page loads
- router list loads
- billing pages load
- settings pages load

### Critical Data Validation

Check:

- subscriber count
- invoice count
- payment count
- total open balances
- payment allocation integrity
- billing snapshot visibility

### Functional Validation

Test at least:

- open subscriber detail
- open invoice detail
- record test payment if safe in non-production validation
- open router detail
- test public billing page if applicable

## 14. Recovery Point and Recovery Time Guidance

## Recovery Point Objective

This is the acceptable amount of recent data loss.

For early production:

- daily backup may be acceptable

For more serious operations:

- tighter DB backup strategy may be needed

## Recovery Time Objective

This is the acceptable duration of outage during recovery.

Factors:

- server size
- DB size
- media size
- team readiness

## 15. Restore Testing Policy

Backups are not trustworthy until restore is tested.

### Minimum Policy

At regular intervals:

- restore one recent backup into non-production environment
- confirm DB opens successfully
- confirm app connects successfully
- confirm critical records exist

### Best Practice

Run scheduled recovery drills.

## 16. Recommended Backup Automation

Automate:

- PostgreSQL logical dumps
- backup rotation
- backup copy to remote storage
- failure alerting

### Automation Should Include

- timestamped filenames
- cleanup according to retention policy
- success/failure logging
- alert on failed backup

## 17. Recommended Restore Documentation

Maintain a restore checklist that includes:

- who authorized restore
- what backup was used
- when restore started
- when restore completed
- what validation was performed
- whether rollback was needed

This helps incident tracking and operational accountability.

## 18. High-Risk Data Areas in ISP Manager

### Billing and Payments

Highest restore sensitivity:

- invoices
- payments
- allocations
- open balances

Any restore must validate these carefully.

### Settings

Important because:

- wrong billing settings can affect future invoices
- wrong router settings can affect polling
- wrong Telegram/SMS settings can affect notifications

### Router and Interface State

Operationally important, but partly reconstructable through re-sync.

### Usage and Telemetry

Useful but less critical than financial and subscriber data.

## 19. Backup Runbook Checklist

Before backup:

- DB healthy
- destination available
- enough disk space

After backup:

- file exists
- file size non-zero
- copied off-host
- log recorded

## 20. Restore Runbook Checklist

Before restore:

- identify target backup
- stop writes
- stop scheduler
- decide overwrite vs alternate restore target

After restore:

- app starts
- login works
- subscriber count validated
- billing count validated
- payment count validated
- settings confirmed

## 21. Recommended Operational Policy

For `ISP Manager` production:

- daily PostgreSQL logical backup minimum
- off-host backup storage required
- pre-deployment backup required
- routine restore testing required

## 22. Final Recommendation

Treat backup and restore as part of the application design, not as an optional ops task.

For this project:

- PostgreSQL must be backed up regularly
- business-critical financial data must be restorable
- restore drills must be tested before real incidents happen

This is especially important because `ISP Manager` handles:

- subscriber records
- invoices
- payments
- collections state
- operational settings

## 23. Application-Managed Backup and Restore Feature Plan

`ISP Manager` should expose database backup operations carefully because the app is
currently maintained directly on a live production server.

The product naming should stay precise:

- `Data Exchange` means CSV import/export for operational records.
- `DB Export / Backup` means PostgreSQL-native backup output.
- `DB Import` means validating or restoring a PostgreSQL backup file.

For operator safety, database export should not be implemented as another CSV
export. A full database backup must use PostgreSQL-native tooling such as
`pg_dump`.

### Backup & Restore Settings

Add a settings page under:

- `Settings > Backup & Restore`

The settings page should control:

- local backup root, such as `/opt/backups/ispmanager/db`
- `pg_dump` path
- filename prefix
- minimum free-space guard
- manual backup enablement
- partial backup enablement
- download and delete enablement
- retention count
- scheduled backup time and profile
- stale-backup alert threshold
- V2 remote copy, encryption, and restore-test guardrails

Remote storage credentials and encryption secrets should come from environment
variables or OS-level secret handling, not from normal database fields.

### V1 Scope

V1 should include:

- manual full DB export / backup
- manual partial DB export / backup using curated presets
- backup job history
- checksum and file-size recording
- controlled backup download
- controlled backup delete
- audit logging for all backup operations
- uploaded backup validation only

V1 should not include one-click production restore.

### V2 Scope

V2 should include:

- scheduled full backup
- retention cleanup
- diagnostics backup-health checks
- failure and stale-backup alerts
- remote copy
- encrypted backups
- media/config backup packages
- restore test into a separate database

Production restore should remain a guided maintenance workflow unless a future
wizard can enforce scheduler stop, write lock, pre-restore backup, authorization,
and rollback checks.

### Partial Backup Presets

Partial backups must use dependency-aware presets instead of arbitrary table
selection.

Recommended presets:

- `Full Database`
- `Business Critical`
- `Subscribers`
- `Billing and Payments`
- `Accounting`
- `Network and NMS`
- `Settings and Content`

Random table selection is not recommended because it can produce backups that
cannot restore cleanly due to foreign-key dependencies.

### DB Import Boundary

The safe first implementation for DB import is upload validation:

- confirm file type and size
- compute checksum
- confirm compressed files can be read
- record validation result

The next safe step is test restore:

- restore into a separate temporary or staging database
- run count and integrity checks
- produce a validation report

Direct import into the live production database must not be exposed as a normal
operator action.

## 24. Production-Safe Implementation Slices

Because this system is being changed directly on a live server, backup work
should be delivered in small slices.

### Slice 0: Documentation

- Document backup/export/import boundaries.
- Document V1 and V2 scope.
- Document partial backup presets.
- No runtime behavior changes.

### Slice 1: Settings

- Add `Settings > Backup & Restore`.
- Add backup settings persistence.
- Keep backup execution disabled.

### Slice 2: Backup Job History

- Add backup job history records.
- Add a history dashboard.
- Do not run `pg_dump` yet.

### Slice 3: Manual Full Backup

- Add manual full database backup.
- Write to a temporary file first.
- Rename only after success.
- Record checksum and size.
- Log the action in `AuditLog`.

Implementation notes:

- The manual full backup must be disabled by default.
- The operator must enable manual backups in `Settings > Backup & Restore`.
- The action must require the `run_database_backup` permission or superuser access.
- The backup service should call `pg_dump` with structured subprocess arguments,
  not a shell string.
- The database password should be supplied through `PGPASSWORD` in the subprocess
  environment and must not be written to job logs.
- The first supported output format is PostgreSQL custom format
  (`pg_dump --format=custom`) with `.dump` filenames.
- If the app reports `No such file or directory: pg_dump`, set `pg_dump path`
  in `Settings > Backup & Restore` to an absolute path such as
  `/usr/bin/pg_dump`. On Ubuntu, install the client tools with
  `sudo apt install postgresql-client` if no `pg_dump` binary exists.
- The final backup file should be written with restrictive permissions, such as
  `0600`, after successful completion.
- Failed backups should create or update a failed backup job record so diagnostics
  and operators can see the problem.

### Slice 4: Download, Delete, and Verify

- Add controlled download.
- Add controlled delete.
- Add checksum verification.
- Require explicit permissions.

Implementation notes:

- Download must require `download_database_backup` permission or superuser access.
- Download must also require `allow_backup_download` in Backup & Restore settings.
- Delete must require `delete_database_backup` permission or superuser access.
- Delete must also require `allow_backup_delete` in Backup & Restore settings.
- Checksum verification may be available to operators who can view backup jobs.
- Download, delete, and verify must resolve the target file path and confirm it is
  inside the configured backup root before touching the file.
- Delete should remove the file from disk but preserve the job history record for
  auditability.
- Every download, delete, and verification action should write an `AuditLog`
  entry.

### Slice 5: Partial Backup Presets

- Add curated partial backup profiles.
- Preserve required table dependencies.
- Do not allow arbitrary table picking.

Implementation notes:

- Partial backups must require `partial_backups_enabled` in Backup & Restore
  settings.
- Partial backups must also require manual backups to be enabled and the same
  `run_database_backup` permission used by full backups.
- Profiles should resolve to Django model table names from approved app-label
  groups.
- The first implementation should use PostgreSQL custom dump format with
  repeated `--table` arguments.
- The backup job summary should record the selected profile and included table
  list.
- The UI must present named presets only. Do not expose arbitrary table
  selection to operators.
- Partial backups are for controlled export, inspection, and future restore-test
  workflows. They are not a substitute for full production backups.

### Slice 6: Import Validation

- Allow upload validation only.
- Do not restore into production.

Implementation notes:

- Import validation must require `validate_database_backup` permission or
  superuser access.
- Uploaded files should be streamed to a temporary file for inspection and
  removed after validation.
- Validation should record file name, size, checksum, compression, detected dump
  format, status, and validation errors in backup job history.
- Validation may confirm gzip readability and basic PostgreSQL dump signatures,
  such as PostgreSQL custom dump headers or plain SQL dump markers.
- Validation must not call `pg_restore` against the live production database.
- Validation must not replace, truncate, or mutate production tables.
- A successful validation means the uploaded file is readable enough for the
  current validation checks. It does not prove the file can fully restore until
  a later restore-test slice restores it into a separate database.

### Slice 7: Retention Cleanup

- Add manual retention cleanup first.
- Keep scheduled cleanup disabled until manual cleanup is validated.

Implementation notes:

- Retention cleanup should use `retention_keep_last` from Backup & Restore
  settings.
- The first implementation should be manual only.
- Cleanup should require `delete_database_backup` permission or superuser access.
- Cleanup should also respect the same delete setting used for manual backup
  delete actions.
- Cleanup must only consider completed DB export backup jobs.
- Cleanup must preserve the newest configured number of backup files.
- Cleanup must confirm every target file is inside the configured backup root
  before deleting it.
- Cleanup should remove files from disk but preserve backup job records and mark
  the job summary with `deleted_at`, `deleted_by`, and `deleted_reason`.
- Cleanup must write an `AuditLog` entry with deleted/skipped counts.

### Slice 8: Diagnostics

- Show last successful backup.
- Show last failed backup.
- Warn when backups are stale.
- Warn when backup storage is low.

Implementation notes:

- Diagnostics should read Backup & Restore settings and backup job history.
- Diagnostics should not create backup directories or mutate backup files.
- Alerts should be generated when backup storage is unavailable, backup storage
  is below the configured free-space guard, no successful backup is recent enough,
  or recent backup export jobs failed.
- The diagnostics dashboard should show last success, recent failures, validation
  failures, `pg_dump` availability, backup root status, and free-space details.
- Backup alerts should link operators to `/backups/` or `/settings/backup/`.

### Slice 9: Scheduled Backups

- Add scheduler integration.
- Keep disabled by default.
- Enable only after manual backup is proven reliable.

Implementation notes:

- Scheduled backups must use `scheduled_backups_enabled` from Backup & Restore
  settings.
- Scheduled backups should reuse the same backup service path as manual backups.
- The first scheduled implementation should register jobs with APScheduler but
  exit quietly while scheduling is disabled.
- Scheduled backup profile should come from `scheduled_backup_profile`.
- Weekly backups should require both `scheduled_backups_enabled` and
  `weekly_backup_enabled`.
- Scheduler time/profile changes may require a scheduler process restart because
  this project registers cron triggers at scheduler startup.
- Scheduler diagnostics should list scheduled backup jobs and show whether they
  are enabled by settings.
- Scheduled backup jobs must not run until manual backup has been tested
  successfully on the production server.

### Slice 10: Remote and Encrypted Backups

- Add encryption.
- Add remote copy.
- Alert on failed remote transfer.

### Slice 11: Test Restore

- Restore into a separate database.
- Run validation checks.
- Produce an operator report.

### Slice 12: Production Restore Wizard

Only consider this after the restore test workflow is proven. A production
restore wizard must require:

- superuser authorization
- current-state backup
- maintenance window confirmation
- scheduler stop confirmation
- app write lock or downtime
- rollback plan confirmation
- post-restore validation checklist
