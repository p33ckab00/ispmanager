# PostgreSQL Installation Workflow

Production-oriented setup guide for running `ISP Manager` with PostgreSQL on Ubuntu.

## Purpose

This document defines the recommended PostgreSQL installation, configuration, migration, and operational workflow for `ISP Manager` once the project moves beyond SQLite and is prepared for production deployment on Ubuntu.

This workflow is designed to support:

- Better concurrency than SQLite
- Background scheduler and telemetry writes
- Billing, payments, and notification workloads
- Cleaner long-term scaling path

## Target Environment

- `OS`: Ubuntu Server `22.04 LTS` or newer
- `Database`: PostgreSQL `15` or newer
- `App Runtime`: Django-based `ISP Manager`
- `Deployment Style`: app server + PostgreSQL on same VM or separate DB host

## Recommended PostgreSQL Version

Use:

- `PostgreSQL 15` minimum
- `PostgreSQL 16` preferred for new deployments

Reason:

- stable on Ubuntu
- strong Django compatibility
- better long-term support
- good balance between maturity and current features

## Architecture Recommendation

### Minimum Production Topology

- `1 Ubuntu app server`
- `1 PostgreSQL instance`
- `1 reverse proxy`
- `1 Redis instance` if queue/caching is added later

### Preferred Growth Topology

- app server separated from database host
- PostgreSQL on dedicated storage-backed VM
- backup automation
- monitored disk, memory, and connection usage

## 1. Ubuntu Server Preparation

Before installing PostgreSQL:

- fully update Ubuntu packages
- set correct timezone
- configure firewall
- create non-root deployment user
- install Python runtime and build dependencies

Recommended baseline packages:

- `python3`
- `python3-venv`
- `python3-dev`
- `build-essential`
- `libpq-dev`
- `nginx`
- `git`

## 2. PostgreSQL Installation on Ubuntu

### Install Packages

Install:

- `postgresql`
- `postgresql-contrib`
- `libpq-dev`

Ubuntu package installation should come from the official Ubuntu repositories unless a newer PostgreSQL release is specifically required from the PostgreSQL upstream repo.

### Confirm Service State

After install, verify:

- PostgreSQL service is enabled
- PostgreSQL service is running
- database port is bound locally unless remote DB access is intentionally required

Expected service:

- `postgresql.service`

## 3. Initial PostgreSQL Hardening

### Default Security Rules

For production:

- do not expose PostgreSQL publicly to the internet
- bind PostgreSQL to localhost or private network only
- allow app-to-DB traffic only from trusted hosts
- require password authentication or stronger methods

### Recommended First Security Actions

- set strong password for database role
- disable broad trust-based access
- restrict `pg_hba.conf` entries
- restrict `listen_addresses`
- allow only required application subnet or localhost

### Firewall

If DB is on same host as app:

- do not open port `5432` publicly

If DB is on separate host:

- allow `5432` only from application server IP

## 4. Database and Role Creation

Create:

- one dedicated PostgreSQL database for the app
- one dedicated PostgreSQL role for the app

Recommended naming:

- database: `ispmanager`
- role/user: `ispmanager_user`

### Privilege Rules

The application user should have:

- connect privilege to app DB
- create/use schema objects in app DB
- no superuser privileges
- no broad privileges over other databases

### Optional Environment Split

If using staging:

- `ispmanager_dev`
- `ispmanager_staging`
- `ispmanager_prod`

with separate users or at least separate credentials

## 5. Django Driver Requirements

For Django + PostgreSQL, install:

- `psycopg[binary]` or `psycopg2-binary` for development convenience
- production preference depends on build policy

Recommended direction:

- modern stack: `psycopg`
- legacy-compatible path: `psycopg2`

If you want the cleanest long-term path, use:

- `psycopg`

## 6. Django Settings Migration from SQLite to PostgreSQL

### Current Situation

The project currently uses SQLite in development.

### Required Settings Changes

Update Django `DATABASES` configuration to:

- `ENGINE = django.db.backends.postgresql`
- database name
- database user
- database password
- database host
- database port

### Recommended Environment Variables

Store DB credentials in environment variables such as:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`

Do not hardcode production credentials directly in source code.

### Recommended Production Defaults

- `DB_HOST=127.0.0.1` if DB is on same server
- `DB_PORT=5432`
- use a strong random password

## 7. Migration Strategy from SQLite to PostgreSQL

## Option A: Fresh Production Start

This is the recommended path for this project if production has not started yet.

### Workflow

1. Prepare PostgreSQL
2. Point Django settings to PostgreSQL
3. Run migrations against PostgreSQL
4. Create superuser
5. Reconfigure app runtime
6. Start production with PostgreSQL as the source of truth

### Best For

- new production rollout
- low need to preserve SQLite history
- cleaner deployment path

## Option B: Data Migration from Existing SQLite

Use this only if meaningful live data in SQLite must be preserved.

### Workflow

1. Freeze writes to SQLite
2. Back up SQLite file
3. Export data using Django-native serialization or structured migration process
4. Provision PostgreSQL
5. Run migrations into fresh PostgreSQL schema
6. Import data into PostgreSQL
7. Validate row counts and financial integrity
8. Switch application config to PostgreSQL

### Risks

- inconsistent import ordering
- foreign key issues
- stale or partial scheduler data
- accidentally migrating low-value development noise

### Recommendation

If the project is still pre-production, avoid complex SQLite-to-PostgreSQL history migration and start clean on PostgreSQL.

## 8. Production Ubuntu Deployment Workflow

### Step 1: Install App Dependencies

Prepare:

- project directory
- virtual environment
- Python dependencies
- environment file

### Step 2: Configure PostgreSQL Access

Set:

- app DB credentials
- host/port
- secure file permissions for environment variables

### Step 3: Run Django Migrations

Before app startup:

- run all migrations against PostgreSQL
- verify no migration drift
- confirm required tables exist

### Step 4: Create Admin User

Create initial Django admin/superuser for production operations.

### Step 5: Collect Static Assets

Run static asset collection before enabling web serving.

### Step 6: Start App Server

Run via:

- `gunicorn` recommended
- `systemd` service management

### Step 7: Reverse Proxy

Use:

- `nginx`

Responsibilities:

- terminate HTTP traffic
- serve static files
- proxy to application server

## 9. PostgreSQL Configuration Recommendations

These are safe directional recommendations, not one-size-fits-all absolute values.

### Core Parameters to Review

- `max_connections`
- `shared_buffers`
- `work_mem`
- `maintenance_work_mem`
- `effective_cache_size`
- `wal_level`
- `checkpoint_completion_target`
- `log_min_duration_statement`

### Small Single-Server Deployment Guidance

For small ISP deployment:

- keep `max_connections` moderate
- prefer app connection reuse rather than large connection counts
- enable slow query logging
- monitor storage growth

### For Moderate Growth

Consider later:

- PgBouncer for pooling
- separate DB disk volume
- read replica only if reporting grows significantly

## 10. Backup Strategy

Production backups are mandatory.

### Minimum Backup Set

- daily logical backup using `pg_dump`
- regular full server snapshot or volume snapshot
- retention policy
- periodic restore test

### Recommended Backup Cadence

- daily full logical backup
- more frequent WAL/archive strategy if the business requires tighter recovery windows

### Keep Backups

- off-server
- versioned
- encrypted at rest if stored externally

## 11. Restore Testing

Do not treat backup success as restore success.

Regularly validate:

- database can be restored
- Django app can connect after restore
- critical counts match:
  - subscribers
  - invoices
  - payments
  - snapshots
  - notifications

## 12. Monitoring and Health Checks

Monitor PostgreSQL for:

- DB availability
- connection count
- lock contention
- slow queries
- disk usage
- WAL/storage growth
- table growth for telemetry and usage data

### App-Level Checks

Track:

- migration status
- scheduler stability
- billing generation success
- notification send failure rate
- telemetry cache freshness

## 13. PostgreSQL vs SQLite in This Project

### Why PostgreSQL is Better Here

This project already includes:

- scheduler jobs
- telemetry writes
- notification writes
- usage sampling
- billing and payment workflows
- concurrent admin UI reads

SQLite becomes fragile under this pattern because of write locking.

PostgreSQL is better suited for:

- concurrent writes
- background jobs
- telemetry/cache tables
- future reporting growth
- production reliability

## 14. PostgreSQL vs MySQL

### Recommended Choice

For `ISP Manager`, PostgreSQL is the preferred database.

### Why PostgreSQL Wins

- better concurrency profile
- stronger long-term fit for telemetry and reporting
- very strong Django production compatibility
- better path for future advanced query and indexing needs

### When MySQL is Still Acceptable

Use MySQL only if:

- your organization already standardizes on MySQL
- your hosting or DevOps environment strongly prefers MySQL
- you intentionally trade some long-term flexibility for operational consistency

### Final Recommendation

If migrating away from SQLite:

- `PostgreSQL` is the recommended target

## 15. Production Readiness Checklist

Before going live on Ubuntu with PostgreSQL, confirm all of the following:

- PostgreSQL installed and enabled
- dedicated app DB and user created
- production credentials stored in environment variables
- Django points to PostgreSQL, not SQLite
- migrations applied successfully
- admin account created
- static assets collected
- reverse proxy configured
- backups configured
- restore tested
- DB is not publicly exposed
- scheduler and telemetry jobs verified
- billing, subscriber pages, and notifications tested against PostgreSQL

## 16. Suggested Rollout Strategy

### If Still Pre-Production

Recommended path:

1. Stand up PostgreSQL now
2. Move development/staging config to PostgreSQL
3. Fix any PostgreSQL-specific query or migration issues early
4. Launch production already on PostgreSQL

### If Already Running on SQLite

Recommended path:

1. Freeze production writes
2. Back up SQLite
3. Prepare PostgreSQL
4. Run migrations on PostgreSQL
5. Migrate needed data carefully
6. Validate business-critical records
7. Switch production config
8. Monitor heavily after cutover

## 17. Final Recommendation

For `ISP Manager`, use:

- `SQLite` only for very light local development
- `PostgreSQL` for staging and production

This is the safest long-term choice for:

- live telemetry
- scheduler activity
- billing
- notifications
- concurrent writes
- future scaling

