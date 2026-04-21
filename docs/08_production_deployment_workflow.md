# Production Deployment Workflow

Ubuntu production deployment guide for `ISP Manager` using:

- `PostgreSQL`
- `Gunicorn`
- `Nginx`
- `systemd`

This document is intended to be used when the project is ready for live deployment on Ubuntu Server.

## Purpose

This workflow defines how to deploy `ISP Manager` into a production-ready Ubuntu environment with:

- a dedicated Python virtual environment
- PostgreSQL as the database backend
- Gunicorn as the WSGI application server
- Nginx as reverse proxy and static file server
- systemd-managed services for reliability

## Target Deployment Stack

- `OS`: Ubuntu Server `22.04 LTS` or newer
- `Python`: `3.11` or newer preferred
- `Database`: PostgreSQL `15` or newer
- `App Server`: Gunicorn
- `Reverse Proxy`: Nginx
- `Process Manager`: systemd

## Deployment Topology

### Single-Server Deployment

Good for first production rollout:

- one Ubuntu VM
- PostgreSQL on same host
- Gunicorn on same host
- Nginx on same host

### Recommended Folder Layout

Suggested production paths:

- app root: `/opt/ispmanager`
- virtualenv: `/opt/ispmanager/.venv`
- environment file: `/etc/ispmanager/ispmanager.env`
- Gunicorn socket or port binding under systemd
- static files: `/opt/ispmanager/staticfiles`
- media files: `/opt/ispmanager/media`

## 1. Server Preparation

Before deployment:

- fully update system packages
- set timezone correctly
- create non-root deployment user
- configure SSH access securely
- configure firewall rules

### Recommended Packages

Install at minimum:

- `python3`
- `python3-venv`
- `python3-dev`
- `build-essential`
- `libpq-dev`
- `postgresql`
- `postgresql-contrib`
- `nginx`
- `git`

## 2. Create Deployment User

Use a dedicated Linux user such as:

- `ispmanager`

This user should:

- own the application directory
- run Gunicorn
- not be used as root

Recommended permissions model:

- root manages system services and secrets files
- deployment user owns app runtime files

## 3. Clone or Copy Project to Server

Deploy the project into:

- `/opt/ispmanager`

After copying the project:

- verify permissions
- confirm `.env` or environment file is not committed into source control
- confirm `media/`, `staticfiles/`, and DB secrets are writable only where needed

## 4. Python Environment Setup

### Virtual Environment

Create a dedicated virtual environment under:

- `/opt/ispmanager/.venv`

### Install Python Dependencies

Install:

- project requirements
- PostgreSQL driver
- Gunicorn

For production, ensure the PostgreSQL driver is included in requirements and installed in the same environment as Gunicorn.

## 5. PostgreSQL Preparation

Follow the database setup from:

- [docs/07_postgresql_installation_workflow.md](/mnt/c/Users/Fredjie%20Estilloso/Documents/ispmanager/docs/07_postgresql_installation_workflow.md)

Before starting the app, confirm:

- PostgreSQL is running
- application DB exists
- DB user exists
- DB credentials are correct
- DB is not publicly exposed

## 6. Environment Variable Strategy

Do not hardcode production settings inside source files.

Use a dedicated environment file such as:

- `/etc/ispmanager/ispmanager.env`

### Recommended Variables

- `DJANGO_SETTINGS_MODULE`
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `CSRF_TRUSTED_ORIGINS`
- `CORS_ALLOWED_ORIGINS`

Optional integration variables:

- Telegram bot token
- Telegram chat ID
- Semaphore API key

### File Permission Recommendation

The environment file should be readable only by:

- root
- app service user if necessary

Do not make it world-readable.

## 7. Django Application Preparation

Before first production boot:

- verify settings point to PostgreSQL
- verify `DEBUG=False`
- verify `ALLOWED_HOSTS`
- verify `STATIC_ROOT`
- verify `MEDIA_ROOT`

### Run Migrations

Apply all Django migrations against PostgreSQL before serving traffic.

### Create Admin Account

Create an initial Django superuser for production access.

### Collect Static Files

Run static collection so Nginx can serve production assets.

## 8. Gunicorn Setup

### Gunicorn Role

Gunicorn will:

- run the Django WSGI app
- serve application requests behind Nginx

### Recommended Binding

Use either:

- Unix socket
- localhost TCP port

Preferred:

- Unix socket for same-host deployment

Example path concept:

- `/run/gunicorn-ispmanager.sock`

### Worker Strategy

Start conservatively:

- `2` to `4` workers depending on CPU and memory

Do not over-allocate workers if scheduler, telemetry polling, and DB traffic are still being tuned.

## 9. systemd Service for Gunicorn

Create a dedicated `systemd` service for Gunicorn.

### Service Responsibilities

- load environment variables
- activate Python virtual environment
- run Gunicorn under the deployment user
- restart on failure
- start on boot

### Service Should Define

- working directory
- environment file path
- user and group
- ExecStart command
- restart policy

### Recommended Behavior

- `Restart=always` or `Restart=on-failure`
- boot-time enablement
- log visibility through `journalctl`

## 10. Nginx Setup

### Nginx Responsibilities

- receive incoming HTTP/HTTPS requests
- proxy app traffic to Gunicorn
- serve static files
- serve media files
- enforce production headers

### Nginx Site Should Handle

- `/static/`
- `/media/`
- `/` app proxy

### Reverse Proxy Recommendation

Proxy requests to:

- Gunicorn socket or localhost app port

### Recommended Header Handling

Ensure proxy passes:

- `Host`
- `X-Forwarded-For`
- `X-Forwarded-Proto`

This matters for correct URL generation and secure request handling.

## 11. HTTPS and TLS

Production deployment should use HTTPS.

### Recommended Approach

Use:

- `Let's Encrypt`
- `certbot`

### TLS Checklist

- valid certificate installed
- Nginx configured for HTTPS
- HTTP redirected to HTTPS
- `CSRF_TRUSTED_ORIGINS` updated
- secure cookies enabled where appropriate

## 12. Static and Media Files

### Static Files

Static files should be served by Nginx from:

- `STATIC_ROOT`

### Media Files

User-uploaded and generated files should be served from:

- `MEDIA_ROOT`

Examples in this project may include:

- ISP logo uploads
- generated billing PDFs if stored

### Permission Considerations

- Gunicorn app user needs write access only where runtime-generated files are stored
- Nginx needs read access to static/media directories

## 13. Scheduler and Background Jobs

This project currently starts APScheduler from application startup.

### Important Note

For production, this needs careful handling.

If you run multiple Gunicorn workers, starting APScheduler in app initialization may cause:

- duplicate scheduler instances
- repeated jobs
- startup-time DB warnings
- lock contention

### Recommended Production Direction

Long term, move the scheduler into a separate dedicated process instead of tying it to web worker startup.

### Safer Production Model

Use:

- one web service for Gunicorn
- one separate scheduler service for scheduled jobs

This reduces:

- duplicate job execution
- app startup side effects
- worker lifecycle issues

## 14. Logging

Production should log:

- Django errors
- Gunicorn service logs
- Nginx access and error logs
- scheduler warnings and failures

### Recommended Log Sources

- `journalctl` for systemd services
- Nginx log files
- Django application logs

### Important Events to Monitor

- DB connection failures
- migration errors
- billing generation failures
- notification dispatch failures
- router polling failures
- telemetry cache freshness

## 15. Health Verification After Deployment

After deployment, verify all of the following manually:

- app homepage loads
- login works
- dashboard loads
- subscribers page loads
- routers page loads
- billing pages load
- static assets load correctly
- admin panel works
- DB-backed reads and writes succeed
- scheduler is running only once if enabled
- Nginx returns expected responses

### Additional Functional Checks

- create or edit subscriber
- open router detail
- record payment
- generate invoice
- access portal OTP flow
- verify Telegram/SMS settings screens work

## 16. Deployment Sequence

Use this rollout order:

1. Prepare Ubuntu server
2. Install PostgreSQL
3. Create app DB and DB user
4. Install Python and dependencies
5. Deploy project files
6. Configure environment variables
7. Run migrations
8. Create superuser
9. Collect static files
10. Configure Gunicorn service
11. Configure Nginx
12. Test app locally on server
13. Enable HTTPS
14. Start services
15. Validate application behavior

## 17. Rollback Strategy

If deployment fails:

- stop Gunicorn service
- restore previous environment file or release
- restore database backup if schema/data changed incorrectly
- re-enable previous known-good app version

### Minimum Rollback Requirements

- keep previous release copy
- keep DB backup before migration
- document exact deployment time and change set

## 18. Production Security Checklist

Before go-live:

- `DEBUG=False`
- strong `SECRET_KEY`
- database not publicly exposed
- environment file permissions locked down
- HTTPS enabled
- firewall enabled
- only needed ports open
- deployment user non-root
- admin credentials strong
- backup jobs enabled

## 19. Suggested systemd Service Layout

Recommended service split:

- `ispmanager-web.service`
- `ispmanager-scheduler.service` later, once scheduler is separated
- `postgresql.service`
- `nginx.service`

This gives a cleaner future path than running everything in a single web process.

## 20. Operational Recommendation

For first serious production release of `ISP Manager` on Ubuntu:

- use PostgreSQL, not SQLite
- use Gunicorn behind Nginx
- use systemd-managed services
- keep scheduler under control and avoid duplicate startup
- plan early for separating scheduler from web workers

## 21. Final Recommendation

When this project reaches production on Ubuntu, the safest stack is:

- `Ubuntu + PostgreSQL + Gunicorn + Nginx + systemd`

This gives the best balance of:

- stability
- maintainability
- scalability
- compatibility with Django
- readiness for telemetry, billing, scheduler, and concurrent writes

