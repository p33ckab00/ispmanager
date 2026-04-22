# Production Hardening Checklist

Focused hardening checklist for the current `ISP Manager` codebase before public or client-facing production rollout.

## 1. Django Security

Confirm all of the following:

- `DEBUG=False`
- strong `SECRET_KEY`
- strict `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS` configured for the real HTTPS domain
- secure cookie settings reviewed for production
- no real secrets committed in Git

## 2. Database Hardening

Confirm:

- PostgreSQL is the only active app database
- dedicated app role is used instead of `postgres`
- database password is strong
- `5432` is not publicly exposed
- regular PostgreSQL backups are configured
- restore workflow has been tested

## 3. Service Hardening

Confirm:

- Gunicorn runs under dedicated Linux user
- Nginx is the only public entrypoint
- systemd services restart automatically on failure
- production env file is readable only by intended users
- app directories have correct ownership and permissions

## 4. Scheduler Safety

Because the current repo does not yet expose a production-ready standalone scheduler command, confirm:

- web service uses `DISABLE_SCHEDULER=1`
- staff know which jobs are currently manual
- duplicate scheduler startup is not possible through Gunicorn workers
- scheduler separation is tracked as a follow-up implementation

## 5. Billing and Accounting Safety

Confirm:

- payment recording creates linked accounting income
- invoice generation is tested on PostgreSQL
- snapshot generation is tested on PostgreSQL
- overdue processing rules are reviewed before automation is enabled
- SMS and Telegram notifications are tested with production credentials

## 6. Router and Telemetry Safety

Confirm:

- MikroTik credentials are valid from the Ubuntu host
- telemetry pages load without DB errors
- router sync works against PostgreSQL-backed app state
- polling intervals are reviewed for production load
- stale cache and manual recovery behavior are understood

## 7. Static and Media Files

Confirm:

- `collectstatic` runs successfully
- Nginx serves `/static/` correctly
- `/media/` permissions are correct if uploads are used
- app still renders correctly after service restart

## 8. Logging and Monitoring

Minimum recommended:

- `journalctl` checked for Gunicorn and Nginx errors
- PostgreSQL service monitored
- disk space monitored
- backup success monitored
- application smoke test performed after each deploy

## 9. Rollback Readiness

Before each deploy, confirm:

- database backup taken
- previous app version can be restored
- environment file backup exists
- service definitions are backed up
- rollback steps are documented and rehearsed

## 10. Release Gate

Do not call the deployment production-ready unless:

- PostgreSQL is stable
- web service is stable
- HTTPS is working
- billing and accounting flows are validated
- router pages are validated
- scheduler strategy is explicitly understood
