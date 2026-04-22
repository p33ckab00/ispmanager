# Ubuntu Scheduler Workaround Guide

Temporary production operations guide for `ISP Manager` while the codebase does not yet expose a dedicated standalone scheduler entrypoint.

## Purpose

This guide explains how to run the application safely on Ubuntu today, without accidentally starting duplicate APScheduler instances under Gunicorn.

## Current Limitation

The current codebase still starts the scheduler from Django app startup logic.

Safe web deployment therefore requires preventing scheduler startup inside the Gunicorn service.

## Recommended Temporary Production Rule

For the web service environment, set:

```env
DISABLE_SCHEDULER=1
```

This prevents the web workers from starting APScheduler.

## What This Means Operationally

With `DISABLE_SCHEDULER=1` enabled in production web service:

- HTTP pages work normally
- PostgreSQL works normally
- billing, accounting, and router pages remain available
- automatic scheduled jobs should be considered disabled until a dedicated scheduler service is implemented

That affects:

- auto invoice generation
- auto billing snapshot generation
- scheduled billing SMS
- overdue marking
- auto-suspension
- usage sampling
- router status polling
- telemetry cache refresh

## Temporary Workaround Options

### Option 1: Manual operational triggers

Use this if the deployment is early-stage or controlled by staff.

Examples:

- generate snapshots manually from subscriber pages
- record payments manually
- use manual accounting sync/reconciliation tools if needed
- use router sync buttons manually
- use diagnostics routes manually for controlled checks

### Option 2: Controlled maintenance window runs

If a job absolutely must run before the dedicated scheduler entrypoint exists, run it manually in a controlled admin shell session instead of letting Gunicorn workers do it implicitly.

Do this only when:

- you know exactly which job you are running
- the job is idempotent or low risk
- you monitor DB writes during the run

## systemd Guidance

### Web service

The production web service should include:

```ini
EnvironmentFile=/etc/ispmanager/ispmanager.env
```

And the env file should contain:

```env
DISABLE_SCHEDULER=1
```

### Do not do this yet

Do not create a fake second Gunicorn service hoping it will behave like a scheduler service.

That would still rely on Django app startup side effects and can reintroduce duplicate or unclear job execution.

## Recommended Next Implementation

The long-term fix should be a dedicated scheduler entrypoint such as:

- a management command
- or a dedicated scheduler runner module

Then production can use:

- `ispmanager-web.service`
- `ispmanager-scheduler.service`

with the scheduler process intentionally started once.

## Verification Checklist

When using this workaround, confirm:

- Gunicorn starts successfully
- pages load normally
- scheduler is not silently running inside every worker
- operators understand which jobs are now manual
- billing automation is not assumed to be active

## Risk Reminder

This workaround keeps the deployment safer than running duplicate web-started schedulers, but it is still an operational compromise.

Treat it as a temporary production-safe workaround until the dedicated scheduler process is implemented in code.
