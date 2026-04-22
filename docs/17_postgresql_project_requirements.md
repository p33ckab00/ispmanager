# PostgreSQL Project Requirements

## Purpose
This document captures the project-side requirements that must be in place before switching `ISP Manager` from SQLite to PostgreSQL.

## Requirements Added

### 1. PostgreSQL Driver
The project now requires a PostgreSQL driver for Django:

- `psycopg[binary]>=3.2,<4`

This is defined in:

- `requirements.txt`

### 2. Environment Variable Template
A safe environment template is now available in:

- `.env.example`

This includes:

- `USE_POSTGRES`
- `SQLITE_TIMEOUT_SECONDS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_CONN_MAX_AGE`
- `DISABLE_SCHEDULER`

### 3. Django Settings Support
The Django settings already support PostgreSQL mode when:

- `USE_POSTGRES=True`

and the PostgreSQL environment variables are provided.

## Pre-Cutover Checklist

Before enabling PostgreSQL in the real environment, make sure:

1. PostgreSQL is installed and running
2. the target database exists
3. the target DB user exists and has privileges
4. the Python environment has installed the updated `requirements.txt`
5. the real `.env` contains the PostgreSQL connection values
6. scheduler behavior is reviewed before running in a write-heavy environment

## Recommended Local Test Flow

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Update `.env`:

```env
USE_POSTGRES=True
POSTGRES_DB=ispmanager
POSTGRES_USER=ispmanager
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60
```

3. Run migrations:

```bash
python manage.py migrate
```

4. Run checks:

```bash
python manage.py check
```

5. Start the app and validate:

- login
- subscriber detail
- billing snapshot generation
- payment recording
- router telemetry
- usage sampling

## Notes

- The real `.env` file was not modified by this preparation step.
- SQLite remains available for fallback local development.
- PostgreSQL remains the recommended database for staging and production because of scheduler activity, telemetry writes, and billing concurrency.
