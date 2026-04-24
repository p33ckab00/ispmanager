# Internal Server Error Recovery Runbook

## Summary

This guide documents the practical recovery workflow for `Internal Server Error`, `502 Bad Gateway`, and related deployment/runtime failures in the current `ISP Manager` production setup.

It is written so an operator can resolve the issue even without AI assistance.

This runbook is based on the current live service layout on this host:

- app code lives in `/opt/ispmanager`
- web app runs as `gunicorn` on `127.0.0.1:8193`
- web systemd unit is `ispmanager-web.service`
- scheduler systemd unit is `ispmanager-scheduler.service`
- nginx fronts the web app on port `80`

## Current Production Service Layout

### Web Service

- unit: `ispmanager-web.service`
- working directory: `/opt/ispmanager`
- process user: `root`
- command:

```bash
/opt/ispmanager/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8193 config.wsgi:application
```

### Scheduler Service

- unit: `ispmanager-scheduler.service`
- working directory: `/opt/ispmanager`
- process user/group: `ispmanager:ispmanager`
- command:

```bash
/opt/ispmanager/.venv/bin/python manage.py run_scheduler
```

### Reverse Proxy

- nginx listens on port `80`
- gunicorn listens only on `127.0.0.1:8193`

This means:

- browser errors may be caused by nginx or by gunicorn
- a `502` does not always mean Django is broken
- a Django `500` and an nginx `502` must be triaged differently

## Most Common Failure Pattern Seen In This Project

The most important failure pattern already seen in this deployment is:

1. code is updated
2. migrations are applied
3. gunicorn is still running old in-memory code
4. browser shows `Internal Server Error` or nginx shows `502`
5. logs show import or model mismatch errors

Example of the exact kind of failure already encountered:

- new NMS code referenced `Endpoint`
- database and code were already updated
- gunicorn workers were still serving old loaded modules
- result: import failure until `ispmanager-web.service` was restarted

So one of the first questions should always be:

`Was code changed or were migrations applied without restarting the running services?`

## Safe Triage Order

Follow this exact order.

### Step 1: Confirm Which Layer Is Failing

Check direct app response:

```bash
curl -I http://127.0.0.1:8193/
```

Check nginx/public response:

```bash
curl -I http://127.0.0.1/
```

Interpretation:

- if `127.0.0.1:8193` fails, the Django/gunicorn layer is the problem
- if `127.0.0.1:8193` works but port `80` fails, the nginx/proxy layer is the problem
- if both fail, start with the app layer first

### Step 2: Check Service Status

```bash
systemctl --no-pager --full status ispmanager-web.service
systemctl --no-pager --full status ispmanager-scheduler.service
```

Look for:

- `active (running)` vs failed state
- recent crash loop messages
- import errors
- migration/model errors
- permission errors

### Step 3: Read Recent Logs

```bash
journalctl -u ispmanager-web.service -n 100 --no-pager
journalctl -u ispmanager-scheduler.service -n 100 --no-pager
```

If the browser shows `Internal Server Error`, this is usually the fastest way to find the real exception.

### Step 4: Run Django Health Checks From The App Directory

Always use the project virtualenv Python:

```bash
cd /opt/ispmanager
/opt/ispmanager/.venv/bin/python manage.py check
/opt/ispmanager/.venv/bin/python manage.py makemigrations --check --dry-run
```

If there are unapplied migrations:

```bash
/opt/ispmanager/.venv/bin/python manage.py showmigrations
```

### Step 5: Check Whether A Restart Is Needed

If code changed, migrations were applied, or logs show stale import/model errors, restart services:

```bash
systemctl restart ispmanager-web.service
systemctl restart ispmanager-scheduler.service
```

Then re-check:

```bash
systemctl --no-pager --full status ispmanager-web.service
curl -I http://127.0.0.1:8193/
curl -I http://127.0.0.1/
```

## Standard Recovery Workflow

Use this when the app is down after deploy, migration, or NMS changes.

### Recovery Sequence

1. Go to the project directory:

```bash
cd /opt/ispmanager
```

2. Confirm git/worktree state:

```bash
git status --short
git branch --show-current
```

3. Run Django checks:

```bash
/opt/ispmanager/.venv/bin/python manage.py check
/opt/ispmanager/.venv/bin/python manage.py makemigrations --check --dry-run
```

4. If migrations are pending, apply them:

```bash
/opt/ispmanager/.venv/bin/python manage.py migrate
```

5. Restart the web and scheduler services:

```bash
systemctl restart ispmanager-web.service
systemctl restart ispmanager-scheduler.service
```

6. Verify service status:

```bash
systemctl --no-pager --full status ispmanager-web.service
systemctl --no-pager --full status ispmanager-scheduler.service
```

7. Verify direct app response:

```bash
curl -I http://127.0.0.1:8193/
```

8. Verify reverse proxy response:

```bash
curl -I http://127.0.0.1/
```

9. Open the system in the browser and test:

- dashboard
- subscribers list
- subscriber detail
- NMS map
- billing page

## Quick Decision Guide

### Case A: `ispmanager-web.service` Is Not Running

Run:

```bash
systemctl restart ispmanager-web.service
journalctl -u ispmanager-web.service -n 100 --no-pager
```

If it still fails:

- inspect the latest Python exception
- run `manage.py check`
- confirm there is no missing migration or import error

### Case B: `ispmanager-web.service` Is Running But Browser Shows `500`

Run:

```bash
journalctl -u ispmanager-web.service -n 100 --no-pager
```

Then:

```bash
/opt/ispmanager/.venv/bin/python manage.py check
```

Common causes:

- bad import
- model mismatch
- view/template error
- missing database migration

### Case C: Browser Shows `502 Bad Gateway`

First split the problem:

```bash
curl -I http://127.0.0.1:8193/
curl -I http://127.0.0.1/
```

Interpretation:

- gunicorn fails too: app layer issue
- gunicorn works but nginx fails: proxy layer issue

Then check:

```bash
systemctl --no-pager --full status ispmanager-web.service
journalctl -u ispmanager-web.service -n 100 --no-pager
```

### Case D: Error Happened Right After Migration Or Code Pull

Assume stale processes until proven otherwise.

Run:

```bash
/opt/ispmanager/.venv/bin/python manage.py migrate
systemctl restart ispmanager-web.service
systemctl restart ispmanager-scheduler.service
```

This is the most common safe fix after deploy-time failures.

## Premium NMS-Specific Recovery Notes

Because Premium NMS adds models, migrations, and runtime workflows, these checks matter after NMS changes:

```bash
/opt/ispmanager/.venv/bin/python manage.py showmigrations nms
/opt/ispmanager/.venv/bin/python manage.py check
```

Then validate these pages:

- `/nms/`
- `/nms/links/`
- `/nms/nodes/`
- `/subscribers/<id>/`
- `/nms/subscribers/<id>/`

If NMS code was deployed but the web service was not restarted, expect import/model mismatch errors.

## What Not To Do

Do not do these during incident recovery:

- do not run `git reset --hard` on production unless explicitly approved
- do not delete migrations just because the app is failing
- do not manually edit database rows first when the error is clearly an app import/runtime issue
- do not assume nginx is the problem before checking gunicorn directly
- do not assume Django is broken before checking whether services were simply not restarted

## Post-Recovery Validation Checklist

After recovery, confirm all of the following:

- `ispmanager-web.service` is `active (running)`
- `ispmanager-scheduler.service` is `active (running)`
- direct gunicorn endpoint responds:

```bash
curl -I http://127.0.0.1:8193/
```

- nginx/public endpoint responds:

```bash
curl -I http://127.0.0.1/
```

- Django checks pass:

```bash
/opt/ispmanager/.venv/bin/python manage.py check
```

- no pending model drift:

```bash
/opt/ispmanager/.venv/bin/python manage.py makemigrations --check --dry-run
```

- core pages load:
  - dashboard
  - subscribers
  - billing
  - NMS map

## Suggested Deployment Habit To Prevent Repeat Incidents

Every production code rollout should end with this sequence:

```bash
cd /opt/ispmanager
git pull origin main
/opt/ispmanager/.venv/bin/python manage.py migrate
/opt/ispmanager/.venv/bin/python manage.py check
systemctl restart ispmanager-web.service
systemctl restart ispmanager-scheduler.service
curl -I http://127.0.0.1:8193/
curl -I http://127.0.0.1/
```

This simple habit prevents the most common mismatch between:

- updated code
- updated database
- stale running processes

## One-Line Operator Summary

If the site breaks after deploy or migration:

1. check `journalctl -u ispmanager-web.service`
2. run `manage.py check` and `manage.py migrate`
3. restart `ispmanager-web.service` and `ispmanager-scheduler.service`
4. verify `127.0.0.1:8193` first, then port `80`

