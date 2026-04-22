# Diagnostics V2: Incidents and Linux Service Health

## Summary

Diagnostics V2 extends the operations health center with persistent incident tracking, operator acknowledge/resolve workflow, and cached Linux service snapshots for Ubuntu production.

This turns diagnostics from a live-only status page into an operator workflow page that can answer:

- what is wrong right now
- whether someone already saw it
- when it started
- when it cleared
- whether the problem is in the Django app or the Ubuntu service layer

## Scope

Implemented in this phase:

- persistent `DiagnosticsIncident` records
- persistent `DiagnosticsIncidentEvent` history
- `active`, `acknowledged`, and `resolved` incident states
- operator actions to acknowledge and resolve incidents
- automatic incident reopening when a resolved condition returns
- automatic incident resolution when the underlying alert clears
- cached Linux `systemd` service snapshots
- diagnostics scheduler job to refresh incidents and service health

## New Models

Diagnostics V2 adds these models inside `apps/diagnostics`:

- `DiagnosticsIncident`
- `DiagnosticsIncidentEvent`
- `DiagnosticsServiceSnapshot`

### DiagnosticsIncident

Represents one persisted health problem keyed by a stable alert fingerprint.

Important fields:

- `key`
- `source`
- `severity`
- `title`
- `detail`
- `status`
- `first_seen_at`
- `last_seen_at`
- `acknowledged_at`
- `acknowledged_by`
- `resolved_at`
- `resolution_note`
- `current_payload_json`

### DiagnosticsIncidentEvent

Stores history for incident lifecycle changes.

Event types used:

- `detected`
- `updated`
- `acknowledged`
- `resolved`
- `reopened`
- `manually_resolved`

### DiagnosticsServiceSnapshot

Stores cached Linux service health for production-relevant services.

Tracked services:

- `postgresql`
- `nginx`
- `ispmanager-web`
- `ispmanager-scheduler`
- `cloudflared`

## Incident Lifecycle

### Active

A live alert condition currently exists and needs operator attention.

### Acknowledged

An operator has seen the incident and taken ownership, but the condition still exists.

### Resolved

The condition cleared automatically or was manually marked resolved by an operator.

## Resolution Rules

### Auto-resolution

If a previously active or acknowledged alert no longer appears in the live diagnostics alert set, the incident is marked `resolved` automatically.

### Reopen behavior

If the same alert key appears again after resolution, the incident is reopened and an event is written.

### Manual resolution

Operators can resolve an incident directly from the diagnostics page and attach a short note.

## Linux Service Health

Linux service checks are cached into `DiagnosticsServiceSnapshot` instead of running `systemctl` repeatedly on every request.

This keeps page loads fast and avoids tightly coupling diagnostics page rendering to direct shell execution every time.

### Service states

Each tracked service can surface as:

- `healthy`
- `warning`
- `critical`
- `unsupported`
- `unknown`

### Why this matters

For Ubuntu production, app truth is not only:

- database reachable
- scheduler jobs exist

It is also:

- `postgresql` is active
- `nginx` is active
- `ispmanager-web` is active
- `ispmanager-scheduler` is active
- `cloudflared` is healthy when tunnel mode is in use

## Scheduler Integration

A new scheduler job now refreshes diagnostics state:

- job id: `refresh_diagnostics`
- schedule: every 5 minutes

It refreshes:

- persistent incidents
- cached Linux service snapshots

This keeps the diagnostics page current without requiring every page load to fully recompute or reprobe everything from scratch.

## UI Changes

The diagnostics dashboard now includes:

- incident counters
- incident filter tabs
- incident action buttons
- recent incident event history
- Linux service health panel

Available incident views:

- `Active`
- `Acknowledged`
- `Resolved`

Each incident row can now show:

- severity
- source
- first seen
- last seen
- acknowledge status
- resolution note

## API Behavior

The compact diagnostics API at `/api/v1/diagnostics/health/` now reads the same diagnostics truth source but avoids mutating incident state on every dashboard widget poll.

This keeps the widget truthful without creating noisy write activity.

## Validation Performed

The implementation was validated with:

- Python compile checks for updated diagnostics modules
- `manage.py makemigrations diagnostics`
- `manage.py migrate`
- `manage.py check`
- `manage.py makemigrations --check --dry-run`
- Django test-client page checks for:
  - `/diagnostics/`
  - `/diagnostics/?incidents=acknowledged`
  - `/diagnostics/scheduler/`
  - `/api/v1/diagnostics/health/`
- operator flow validation for:
  - acknowledge incident
  - resolve incident with note

## Current Limitations

This phase does not yet include:

- uptime trend charts
- SLA-style summaries
- incident suppression windows
- per-subsystem detail pages
- service restart controls from the web UI

## Recommended Next Step

If diagnostics continues to expand, the strongest next step is a future `V3` focused on:

- trends
- uptime summaries
- subsystem drilldowns
- longer-term incident analytics
