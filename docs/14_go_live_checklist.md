# Go-Live Checklist

Production launch checklist for `ISP Manager`.

## Purpose

This document defines the final checklist to be completed before and during production go-live for `ISP Manager`.

It is intended to ensure that:

- infrastructure is ready
- PostgreSQL is stable
- deployment is repeatable
- scheduler behavior is safe
- billing and payment workflows are reliable
- rollback is possible if launch fails

## Go-Live Principle

Go-live should not be treated as a single technical command.

It should be treated as a controlled release event with:

- pre-launch verification
- deployment execution
- immediate smoke testing
- rollback readiness

## 1. Pre-Go-Live Approval Gate

Before production launch, confirm all of the following are already complete:

- staging sign-off completed
- PostgreSQL selected and validated
- scheduler production strategy agreed
- deployment workflow tested in staging
- backup and restore process documented
- environment variables finalized
- infrastructure access ready

If any of the above is still uncertain, do not proceed.

## 2. Infrastructure Readiness Checklist

Confirm production infrastructure is ready:

- Ubuntu server provisioned
- PostgreSQL installed and healthy
- Gunicorn configured
- Nginx configured
- systemd services present
- DNS prepared if applicable
- firewall rules configured
- TLS plan ready

### Validate

- server reachable
- app host reachable
- DB reachable only from intended hosts
- enough disk space available
- enough memory available

## 3. Database Readiness Checklist

Confirm:

- PostgreSQL is the active production database target
- correct production DB exists
- correct production DB user exists
- app credentials work
- migrations already tested in staging

### Final DB Checks

- backup taken before launch
- schema is clean
- no migration drift
- no leftover dependency on SQLite in production config

## 4. Environment and Secrets Checklist

Confirm:

- `DEBUG=False`
- `SECRET_KEY` is strong and production-specific
- `ALLOWED_HOSTS` is correct
- `CSRF_TRUSTED_ORIGINS` is correct
- DB credentials are correct
- Telegram/SMS secrets are correct if needed
- environment file is secured

### Security Check

- no secrets in source code
- no development credentials reused in production
- environment file permissions are restricted

## 5. Application Readiness Checklist

Confirm the deployed app version includes:

- required migrations
- correct requirements installed
- static files collected
- production settings enabled
- broken routes fixed
- scheduler duplication risk addressed

### Required Functional Readiness

- subscriber workflows verified
- router workflows verified
- billing verified
- payment allocation verified
- portal OTP flow verified
- settings pages verified

## 6. Scheduler Readiness Checklist

Confirm:

- only one scheduler process will run
- scheduler is not unintentionally tied to every Gunicorn worker
- production scheduler startup model is known
- telemetry polling frequency is production-safe
- billing jobs are idempotent

### Validate

- overdue job safe
- billing generation safe
- auto-suspension safe
- telemetry jobs not over-aggressive

## 7. Communications Readiness Checklist

Confirm:

- Telegram settings are valid
- Telegram test is successful
- SMS settings are valid
- provider credentials are correct
- billing link generation does not rely on localhost

### Validate

- notification state is visible
- failures are understandable
- no silent false-success path remains for critical delivery actions

## 8. Billing and Finance Readiness Checklist

Confirm:

- plans are correct
- subscriber billing-effective dates are correct
- overdue rules are correct
- grace days are correct
- due day / due offset rules are correct
- payment allocation order is correct

### Validate in Production-Like State

- single invoice generation
- bulk invoice generation
- snapshot generation
- payment entry
- payment allocation
- overdue transition

## 9. Backup and Rollback Checklist

Before go-live, confirm:

- fresh DB backup completed
- backup file verified
- backup stored safely
- rollback plan documented
- previous known-good deployment can be restored

### Do Not Proceed Without

- usable database backup
- rollback owner
- rollback decision rule

## 10. Operational Ownership Checklist

Assign responsibility for:

- deployment execution
- DB oversight
- scheduler monitoring
- billing validation
- rollback approval

This avoids confusion during launch.

## 11. Launch Window Checklist

During the planned launch window:

1. pause risky admin changes if needed
2. take final backup
3. deploy release
4. apply migrations
5. collect static files
6. restart services
7. verify app health
8. verify scheduler health
9. perform smoke tests
10. monitor closely

## 12. Smoke Test Checklist Immediately After Launch

Immediately after go-live, verify:

- login works
- dashboard loads
- subscribers list loads
- subscriber detail loads
- routers list loads
- router detail loads
- billing pages load
- accounting pages load
- settings pages load
- diagnostics pages load

### Transactional Smoke Tests

If safe to do so:

- create or edit a subscriber
- open a router telemetry page
- generate one invoice
- record one payment
- test portal OTP flow

## 13. Production Monitoring Checklist

For the first hours after go-live, monitor:

- Gunicorn logs
- Nginx logs
- Django logs
- scheduler logs
- PostgreSQL health
- error tracking if available

### Watch Closely For

- repeated 500 errors
- scheduler duplication
- DB connectivity failures
- notification failures
- telemetry overload
- unexpected billing behavior

## 14. Critical Launch Blockers

Do not continue launch if any of the following are present:

- PostgreSQL connection failure
- migrations failed
- web app cannot start
- scheduler duplication detected
- broken login
- billing route failures
- payment workflow failure
- critical settings not loading
- obvious production secret/config issue

## 15. Rollback Trigger Conditions

Rollback should be considered immediately if:

- app does not serve core pages
- financial workflows are incorrect
- payment posting is broken
- scheduler duplicates jobs
- DB failures persist
- security-critical config is wrong

## 16. First-Day Stabilization Checklist

For the first production day, validate:

- invoices are not duplicating
- payments apply correctly
- overdue jobs behave correctly
- telemetry cache stays fresh
- DB remains healthy
- no unexpected service restarts occur

## 17. Communication Checklist

Before launch:

- inform stakeholders of launch timing
- define maintenance window if needed
- define escalation path

After launch:

- confirm successful deployment
- record release version
- record launch timestamp
- record any issues found

## 18. Launch Sign-Off Areas

Recommended sign-off should include:

- technical/deployment owner
- billing/accounting owner
- network operations owner
- business/product owner if applicable

## 19. Recommended Final Launch Decision Rule

Go live only when:

- staging is validated
- production backup exists
- PostgreSQL is ready
- deployment steps are known
- rollback is ready
- core operational flows are verified

## 20. Final Recommendation

For `ISP Manager`, go-live should happen only after:

- PostgreSQL readiness
- scheduler safety
- billing correctness
- portal and subscriber workflow validation
- operational monitoring readiness

The best production launch is a controlled, boring launch with:

- predictable deployment steps
- minimal surprises
- strong rollback readiness

