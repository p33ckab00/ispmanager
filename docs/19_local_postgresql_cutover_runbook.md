# Local PostgreSQL Cutover Runbook

## Summary

This runbook documents the completed local database cutover from SQLite to PostgreSQL for `ISP Manager`.

## Environment

- PostgreSQL service: `postgresql-x64-18`
- PostgreSQL host: `127.0.0.1`
- PostgreSQL port: `5432`
- App database: `ispmanager`
- App role: `ispmanager`
- Django DB engine: `django.db.backends.postgresql`

## Safety Steps Performed

- Backed up the original SQLite database before cutover
- Exported SQLite application data using `dumpdata`
- Migrated schema to PostgreSQL using Django migrations
- Imported the exported data into PostgreSQL
- Reset PostgreSQL sequences after import

## Local File and Data Locations

### Current active project database

The project now uses PostgreSQL, not SQLite, as its active database.

Physical PostgreSQL data directory:

```text
C:/Program Files/PostgreSQL/18/data
```

Logical application database name:

```text
ispmanager
```

### Legacy migration artifacts

The original SQLite source and temporary backup were used during cutover and have since been removed from the active local workspace.

## Django Configuration

The live connection is controlled through the local `.env` file.

Expected PostgreSQL keys:

```env
POSTGRES_DB=ispmanager
POSTGRES_USER=ispmanager
POSTGRES_PASSWORD=<local secret>
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60
```

## Validation Steps Completed

- `pg_isready` confirmed PostgreSQL accepts connections on `127.0.0.1:5432`
- `manage.py check` passed
- `manage.py showmigrations` showed all migrations applied on PostgreSQL
- Core record counts matched between SQLite and PostgreSQL
- Key app pages loaded successfully after cutover
- Billing payment validation confirmed automatic accounting income creation still works
- Billing snapshot generation validation passed on PostgreSQL

## Rollback

The project is now PostgreSQL-only. Any future rollback should restore from PostgreSQL backups rather than returning to SQLite.
