# Ubuntu Scheduler Service Guide

Production operations guide for running the `ISP Manager` scheduler safely on Ubuntu.

## Purpose

This document explains how to run scheduled jobs without letting Gunicorn workers own APScheduler execution.

## Recommended Production Rule

Use two separate services:

- `ispmanager-web.service`
- `ispmanager-scheduler.service`

And keep this in the shared environment file:

```env
DISABLE_SCHEDULER=1
```

Why this is correct:

- the web service should not auto-start APScheduler
- the scheduler should run once as an intentional long-running process
- logs, restarts, and failures become easier to reason about

## Scheduler Entry Point

The project now includes a dedicated scheduler command:

```bash
python manage.py run_scheduler
```

This command is intended to be the process target for the scheduler service.

## Recommended systemd Service

Create `/etc/systemd/system/ispmanager-scheduler.service`:

```ini
[Unit]
Description=ISP Manager Scheduler Service
Wants=network-online.target
After=network-online.target postgresql.service

[Service]
User=ispmanager
Group=ispmanager
WorkingDirectory=/opt/ispmanager
EnvironmentFile=/etc/ispmanager/ispmanager.env
ExecStart=/opt/ispmanager/.venv/bin/python manage.py run_scheduler
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ispmanager-scheduler
sudo systemctl start ispmanager-scheduler
sudo systemctl status ispmanager-scheduler
```

## What the Scheduler Service Owns

The scheduler service is the correct place for recurring jobs such as:

- invoice generation
- billing snapshot generation
- scheduled billing SMS
- overdue marking
- auto-suspension logic
- subscriber usage sampling
- router polling
- telemetry cache refresh

## What the Web Service Must Not Do

The web service should:

- serve HTTP requests
- use `DISABLE_SCHEDULER=1`
- avoid owning recurring job execution

Do not rely on Gunicorn workers to run scheduler jobs in production.

## Verification Checklist

Confirm:

- `ispmanager-web.service` is running
- `ispmanager-scheduler.service` is running
- PostgreSQL is running
- `journalctl -u ispmanager-scheduler` shows job activity without repeated duplicate startups
- billing and telemetry jobs execute from the scheduler service, not from the web service

## Troubleshooting

### Scheduler service exits immediately

Check:

```bash
sudo journalctl -u ispmanager-scheduler -n 100 --no-pager
```

Common causes:

- broken env file
- PostgreSQL connection failure
- missing app dependencies
- migrations not applied

### Jobs do not appear to run

Check:

- service status
- scheduler logs
- database connectivity
- application settings related to billing, usage, router polling, and notifications

### Duplicate job behavior appears

Check:

- web service env still has `DISABLE_SCHEDULER=1`
- only one `ispmanager-scheduler.service` instance exists
- you are not manually running `manage.py run_scheduler` in another shell at the same time

## Final Recommendation

For Ubuntu production, treat scheduler execution as a first-class service, not as a side effect of web startup.

That gives the cleanest operational model for the current codebase.
