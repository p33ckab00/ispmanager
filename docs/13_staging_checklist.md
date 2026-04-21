# Staging Checklist

Pre-production validation checklist for `ISP Manager`.

## Purpose

This document defines the staging readiness and validation checklist for `ISP Manager` before:

- production deployment
- PostgreSQL cutover
- scheduler separation rollout
- major billing or telemetry changes

The goal of staging is to catch operational, configuration, and workflow issues before they reach production.

## Staging Environment Principles

A staging environment should be:

- as close to production as practical
- isolated from production data
- safe for testing
- configured with PostgreSQL, not SQLite
- capable of running scheduler, telemetry, and billing flows realistically

## Recommended Staging Stack

Staging should ideally mirror production:

- Ubuntu
- PostgreSQL
- Gunicorn
- Nginx
- environment variables
- scheduler process separated from web process where possible

## 1. Infrastructure Checklist

Confirm the staging environment includes:

- Ubuntu server or equivalent Linux host
- PostgreSQL installed and reachable
- application deployed through the same structure planned for production
- Gunicorn running
- Nginx configured
- environment file loaded correctly
- static files collected
- media path configured

## 2. Database Checklist

Confirm:

- PostgreSQL is used, not SQLite
- application connects successfully
- all migrations are applied
- no pending migration drift exists
- staging DB credentials are separate from production

### Validation

Verify:

- app loads successfully
- migration status is clean
- no DB lock issues under normal staging load

## 3. Security and Environment Checklist

Confirm:

- `DEBUG=False`
- `ALLOWED_HOSTS` is set correctly
- `SECRET_KEY` is not a development placeholder
- secure environment file exists
- staging secrets are not production secrets
- HTTPS behavior is tested if staging uses TLS

## 4. Service Process Checklist

Confirm:

- web service starts correctly
- scheduler service starts correctly if separated
- only one scheduler is active
- Nginx proxies correctly
- PostgreSQL service is healthy

### Important Validation

Ensure:

- scheduler is not unintentionally started by every web worker
- duplicate jobs are not running

## 5. Subscriber Workflow Checklist

Validate all major subscriber flows:

- create subscriber
- edit subscriber
- assign plan
- change plan or rate
- suspend subscriber
- reconnect subscriber
- disconnect subscriber
- archive subscriber
- mark deceased subscriber

### Confirm

- proper status transitions
- billing visibility remains correct
- audit logs are created where expected

## 6. Router Workflow Checklist

Validate:

- add router
- test connection
- sync interfaces
- open router detail
- open interface detail
- live telemetry cache endpoint returns data
- physical ports show correct activity state behavior

### Confirm

- router status changes are reflected correctly
- telemetry pages load without lock or timeout issues
- interface traffic cache is updating

## 7. Billing Checklist

Validate:

- generate invoice for one subscriber
- generate invoices in bulk
- prevent duplicate invoice generation for same cycle
- generate snapshot
- freeze snapshot
- public billing view works
- snapshot PDF view/download works if enabled

### Confirm

- billing dates are correct
- overdue behavior respects grace logic
- current settings are actually reflected in generated records

## 8. Payment Checklist

Validate:

- record payment
- apply oldest-first allocation
- handle partial payment
- handle full payment
- verify payment reflects in invoice balance

### Confirm

- payment allocations are correct
- remaining balances are correct
- subscriber detail view reflects updated state

## 9. Accounting Checklist

Validate:

- income list loads
- expense list loads
- add income works
- add expense works
- accounting dashboard loads
- billing-to-income sync works

### Confirm

- no broken routes
- no incorrect redirects
- accounting totals look consistent

## 10. Notifications Checklist

Validate:

- Telegram settings save correctly
- Telegram test button works
- event-based notifications create rows
- skipped vs failed behavior is visible
- SMS settings save correctly

### Confirm

- dashboard config indicators are accurate
- notification records are created with expected delivery state

## 11. Portal Checklist

Validate:

- request OTP
- verify OTP
- portal dashboard loads
- invoice/snapshot visibility works
- usage chart loads gracefully

### Confirm

- failed OTP SMS is surfaced clearly
- no blank unexplained states
- expired/invalid OTP handling works

## 12. Usage and Telemetry Checklist

Validate:

- usage sampler runs
- usage chart endpoint responds
- subscriber detail shows correct empty-state when no data exists
- portal usage section behaves correctly
- telemetry cache updates without DB contention under expected staging load

### Confirm

- no misleading blank charts
- no uncontrolled write amplification

## 13. Scheduler Checklist

Validate these jobs safely in staging:

- overdue marker
- invoice generation
- snapshot generation
- auto-freeze
- usage sampling
- router status polling
- router traffic caching
- auto-archive
- auto-suspension

### Confirm

- jobs run once
- jobs do not duplicate
- logs clearly show outcomes
- failures are understandable and recoverable

## 14. Performance Checklist

Staging should test at least moderate operational load.

Validate:

- subscriber pages load acceptably
- router detail pages remain responsive
- telemetry polling is stable
- scheduler jobs do not overwhelm DB
- PostgreSQL handles concurrent reads/writes cleanly

### Watch For

- lock contention
- excessive query latency
- telemetry endpoints becoming too chatty
- duplicate scheduler execution

## 15. Backup and Recovery Checklist

Before production, verify in staging:

- backup process runs successfully
- restore process is documented
- restored DB can be opened by the app
- critical row counts can be validated after restore

## 16. Deployment Checklist

Validate staging deployment flow:

- pull or deploy release
- install dependencies
- run migrations
- collect static files
- restart Gunicorn
- restart scheduler if separated
- reload Nginx

### Confirm

- deployment is repeatable
- no manual undocumented steps are required

## 17. Release Readiness Gate

The system is ready to move from staging to production only if:

- no critical broken routes remain
- no data corruption issues remain
- no scheduler duplication exists
- PostgreSQL is stable
- billing workflows are correct
- payment flows are correct
- notifications behave predictably
- telemetry behaves within acceptable DB load

## 18. Critical Blocking Conditions

Do not approve production rollout if any of the following still exist:

- database lock behavior under expected production DB choice
- scheduler duplicates
- broken billing generation logic
- broken payment allocation
- incorrect overdue behavior
- broken portal OTP flow
- dead links or known 404s in critical operational pages
- unresolved production config uncertainty

## 19. Sign-Off Areas

Before go-live, staging sign-off should cover:

- product/operations
- billing/accounting
- network operations
- deployment/infrastructure

## 20. Final Recommendation

Staging should be treated as a mandatory gate, not a nice-to-have.

For `ISP Manager`, production rollout should only proceed after staging validates:

- PostgreSQL behavior
- scheduler behavior
- billing integrity
- subscriber workflows
- telemetry stability
- deployment repeatability

