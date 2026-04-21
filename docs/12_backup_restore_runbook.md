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

