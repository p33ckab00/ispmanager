# Diagnostics Operations Health Center

## Summary

The diagnostics module was upgraded from a basic system-info page into an operations health center for the whole ISP Manager project.

This update makes diagnostics reflect the actual architecture of the app:

- PostgreSQL-backed runtime
- APScheduler with persistent job history
- router telemetry and live cache health
- billing integrity and overdue workflow visibility
- SMS and Telegram delivery health
- subscriber usage freshness
- data exchange job failures

## Why this change was needed

The old diagnostics page was too small for the operational surface of the project.

It mainly showed:

- a few count cards
- disk usage
- basic router status
- an in-memory scheduler view

That created two important problems:

1. PostgreSQL deployments could show misleading database size information because the old code treated the database like a local file path.
2. Production scheduler health could be misread because the old page checked only the in-process scheduler singleton, while production uses a dedicated scheduler service backed by `django_apscheduler` tables.

## What changed

### 1. Shared diagnostics aggregation layer

A new aggregation service was added in:

- `apps/diagnostics/services.py`

This layer builds a single diagnostics snapshot for use by the main diagnostics page, the scheduler page, and the internal health API.

### 2. Main diagnostics page became an operations health center

The main diagnostics page now includes:

- overall health badge
- active alerts panel
- runtime and deployment summary
- scheduler and automation health summary
- router and telemetry health
- billing and subscriber operations health
- messaging and notification health
- usage freshness
- data exchange recent failures
- recent audit activity

### 3. Scheduler page is now production-aware

The scheduler page now uses persisted APScheduler state from:

- `django_apscheduler.models.DjangoJob`
- `django_apscheduler.models.DjangoJobExecution`

This means it can show:

- registered jobs
- next run time
- latest success
- latest failure
- stale or missing jobs
- recent exceptions and traceback
- expected scheduler mode vs embedded current-process state

### 4. Dashboard status widget now uses diagnostics truth

A new internal API endpoint was added:

- `/api/v1/diagnostics/health/`

It gives the main dashboard a compact health payload for:

- database
- scheduler
- Telegram
- SMS
- overall health / alert count

This replaces the older loose approach where the dashboard inferred health from page reachability or raw settings flags.

## Checks now surfaced by diagnostics

### Runtime and deployment

- database reachable or failed
- PostgreSQL database size via `pg_database_size(...)`
- query latency
- pending migration count
- static and media path existence / writability
- scheduler mode expectation
- nginx / cloudflared detection
- `DEBUG` status
- `APP_BASE_URL`

### Scheduler and automation

- production-aware scheduler health
- failed jobs
- stale jobs
- pending jobs
- per-job schedule and note
- guarded `run now` behavior for embedded mode only

### Router and telemetry

- online / offline router counts
- stale router `last_seen`
- stale interface telemetry cache rows
- telemetry errors
- quick ping action with live result

### Billing and subscriber operations

- open / partial / overdue invoice counts
- recent billing snapshots
- active overdue subscribers
- overdue subscribers currently on palugit
- palugit expiring soon
- billable subscribers without effective rate
- payments without linked accounting income
- payments with unallocated balance
- stale draft snapshots

### Messaging

- SMS configured or not
- billing SMS automation enabled or not
- today's sent / failed SMS counts
- pending SMS logs
- Telegram configured / enabled state
- failed Telegram deliveries in the last 24 hours
- recent failed SMS and recent failed notifications

### Usage

- usage tracking enabled state
- last raw usage sample
- last daily rollup
- last cutoff snapshot
- subscribers with fresh vs stale/missing usage data
- reset count in the last 24 hours

### Data exchange and activity

- recent import/export jobs
- failed data exchange jobs in the last 7 days
- dry-run / applied import visibility
- recent audit activity

## Alerts model

The new diagnostics page builds active alerts from multiple subsystems.

Examples:

- database check failed
- pending migrations detected
- scheduler automation looks down
- offline routers detected
- stale router telemetry
- payments without accounting income
- billable subscribers missing rates
- stale draft snapshots
- SMS failures today
- Telegram failures in the last 24 hours
- stale or missing usage data
- failed import/export jobs

These alerts roll up into:

- `healthy`
- `warning`
- `critical`

## Files changed

### New

- `apps/diagnostics/services.py`
- `apps/diagnostics/api_views.py`
- `docs/37_diagnostics_operations_health_center.md`

### Updated

- `apps/diagnostics/views.py`
- `apps/diagnostics/api_urls.py`
- `templates/diagnostics/dashboard.html`
- `templates/diagnostics/scheduler.html`
- `templates/core/dashboard.html`
- `README.md`
- `docs/PROGRESS.md`

## Validation performed

The following were validated during implementation:

- `python3 -m py_compile apps/diagnostics/views.py apps/diagnostics/services.py apps/diagnostics/api_views.py`
- `python manage.py check`
- diagnostics dashboard rendered successfully
- scheduler diagnostics page rendered successfully
- diagnostics health API returned valid JSON
- dashboard page includes the new diagnostics health endpoint

## Notes

- No migration was required for this phase.
- This version reuses existing operational models instead of adding a new diagnostics persistence model.
- A remaining warning may still appear locally if `staticfiles/` has not been created yet. That warning is unrelated to diagnostics logic.

## Recommended next phase

Potential follow-up enhancements:

- persistent diagnostics snapshot history
- acknowledgment / resolution workflow for alerts
- diagnostics trend charts
- Linux production service health checks for `systemd`
- optional diagnostics JSON cards for deeper dashboard widgets
