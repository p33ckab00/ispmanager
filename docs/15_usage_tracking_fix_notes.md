# Usage Tracking Fix Notes

## Summary
This change set repairs the subscriber usage pipeline so the feature is closer to operational truth instead of only rendering empty or misleading charts.

## Problems Addressed
- PPP usage sampling was saving rows, but sampled counters were always zero.
- The `by_cycle` usage view had no producer path for `SubscriberUsageCutoffSnapshot` rows.
- Usage delta comparison was not session-aware and could compare against the wrong prior session sample.
- The "this cycle" usage chart was not aligned with the billing-cycle resolver.
- The portal usage cards labeled the last chart point as "today," which was not explicit or reliable.

## Changes Implemented

### 1. PPP Active Stats Query
Updated the MikroTik PPP active fetch path to prefer a stats-capable query and fall back to the plain session list when stats are unavailable.

Files:
- `apps/routers/mikrotik.py`
- `apps/subscribers/services.py`

### 2. Counter Parsing Hardening
Added a counter parser that can read multiple possible byte-counter keys instead of assuming only one exact field name.

Files:
- `apps/subscribers/services.py`

### 3. Session-Aware Delta Calculation
Usage sampling now compares the current sample against the last sample for the same `session_key` when available.

Files:
- `apps/subscribers/services.py`

### 4. Cutoff Snapshot Generation
Added cutoff snapshot generation into the usage scheduler path so the `by_cycle` usage view has real source data.

Files:
- `apps/subscribers/services.py`
- `apps/core/scheduler.py`

### 5. Billing-Aligned Usage Window
Updated `this_cycle` usage chart calculation to use the billing profile resolver so usage charts align better with the subscriber billing cycle.

Files:
- `apps/subscribers/services.py`

### 6. Portal Usage Label Cleanup
Changed the portal usage cards to use explicit daily rollup values for "GB today" instead of using the last chart point.

Files:
- `apps/subscribers/views.py`
- `templates/subscribers/portal_dashboard.html`

## Validation Performed
- `manage.py check`
- `manage.py makemigrations --check --dry-run`
- local service sanity checks for billing-profile and usage function wiring

## Remaining Notes
- Real counter availability still depends on what the target MikroTik device returns from `/ppp/active` stats.
- For production-scale telemetry and usage workloads, PostgreSQL remains the recommended database backend.
