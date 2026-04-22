# PostgreSQL Post-Cutover Audit

## Summary

A post-cutover audit was run after switching the local project from SQLite to PostgreSQL.

Result:

- No PostgreSQL blocker was found
- Core application pages and billing/accounting flows passed validation
- Existing SQLite-specific safeguards now correctly resolve to PostgreSQL behavior

## Audit Checks Performed

### Database and migrations

- Confirmed Django now uses `django.db.backends.postgresql`
- Confirmed all migrations are applied on PostgreSQL
- Confirmed imported row counts match the original SQLite data for core models

### HTTP validation

The following routes returned `200` during audit:

- `/`
- `/subscribers/`
- `/subscribers/<id>/`
- `/subscribers/<id>/usage-chart/?view=this_cycle`
- `/routers/`
- `/routers/<id>/`
- `/routers/<id>/live-traffic-cache/`
- `/accounting/`
- `/accounting/income/`
- `/billing/snapshots/`

### Billing and accounting validation

Rollback-safe validation confirmed:

- `record_payment_with_allocation()` still creates linked accounting income on PostgreSQL
- `generate_snapshot_for_subscriber()` succeeds on PostgreSQL
- validation left no extra records behind

### Telemetry and usage data

Observed on PostgreSQL during audit:

- interface traffic cache rows present
- subscriber usage samples present
- subscriber daily usage rows present

This confirms the migrated dataset includes operational telemetry/usage data and the PostgreSQL-backed app can read it successfully.

## Findings

### No blocker found

No schema mismatch, migration drift, or PostgreSQL-specific runtime blocker was detected in the audited flows.

### Minor warning

Django emitted a staticfiles warning in the test client environment because the local `staticfiles` directory is not present yet.

This is not a PostgreSQL issue, but it should still be addressed before a formal production-style local verification pass.

## Recommended Next Steps

1. Restart the local Django server so all running processes use the PostgreSQL-backed `.env`
2. Manually test the UI in-browser for payment, snapshot, and router telemetry flows
3. Change the generated `postgres` superuser password if it has not been rotated yet
4. Add a PostgreSQL backup routine before doing additional schema or data work
