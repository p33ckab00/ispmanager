# Scheduler Production Strategy

Production strategy document for running scheduled jobs safely in `ISP Manager`.

## Purpose

This document defines how background scheduling should work in production for `ISP Manager`, especially after moving to:

- PostgreSQL
- Gunicorn
- Nginx
- systemd-managed services

The main goal is to prevent duplicate schedulers, unstable startup behavior, and database contention caused by running scheduled jobs inside web workers.

## Problem Statement

The current project starts APScheduler from application startup logic.

This is acceptable for lightweight local development, but it becomes unsafe in production because web processes can be:

- restarted
- scaled
- multiplied across workers
- duplicated across instances

If each web process starts a scheduler, then scheduled jobs may run multiple times.

That creates risk for:

- duplicate invoice generation
- duplicate notifications
- duplicate overdue processing
- duplicate router polling
- unnecessary DB load
- concurrency and locking problems

## Current Risk Profile

Given the current system design, the scheduler touches:

- billing generation
- billing snapshot generation
- overdue marking
- SMS dispatch
- subscriber usage sampling
- router status polling
- router traffic caching
- auto-archive
- auto-suspension

These are not safe to run redundantly.

## Recommended Production Principle

`Do not run the scheduler inside Gunicorn web workers.`

Instead:

- run the web app separately
- run the scheduler as a dedicated single process

## Recommended Service Split

Use separate services:

- `ispmanager-web.service`
- `ispmanager-scheduler.service`

This makes responsibility clear:

- web service handles HTTP requests
- scheduler service runs APScheduler jobs

## 1. Why Separate Scheduler from Web

### 1.1 Prevent Duplicate Job Execution

If the scheduler starts in every web worker, then each worker may execute the same job.

Example risks:

- invoice generation job creates duplicate financial records
- SMS reminder job sends duplicate messages
- router polling job multiplies external load

### 1.2 Reduce Startup Side Effects

When the scheduler starts during app initialization, the app performs DB work too early.

That creates:

- startup-time warnings
- DB access during app boot
- harder-to-debug lifecycle issues

### 1.3 Improve Operational Control

A separate scheduler process allows:

- restart only scheduler if jobs fail
- stop scheduler without stopping web traffic
- inspect logs independently
- monitor job health separately

## 2. Recommended Production Architecture

### Web Layer

Run:

- Django app through Gunicorn
- no scheduler startup inside web process

### Scheduler Layer

Run:

- one APScheduler process only
- under systemd
- with same Django settings and environment as the web app

### Database Layer

Use PostgreSQL so scheduler and web traffic can coexist with better concurrency than SQLite.

## 3. Environment Model

### Local Development

Acceptable:

- scheduler may run inside app for convenience

But even in dev, once telemetry and high-frequency writes increase, it is better to allow an option to disable automatic scheduler startup.

### Staging

Recommended:

- use separate scheduler process

### Production

Required:

- use separate scheduler process

## 4. Recommended Scheduler Startup Design

## Development Mode

Possible behaviors:

- auto-start scheduler for convenience
- allow disabling with environment variable

Suggested control variable:

- `ENABLE_INTERNAL_SCHEDULER`

Meaning:

- `true`: allow scheduler to auto-start in local/dev
- `false`: disable internal startup

## Production Mode

Recommended behavior:

- `ENABLE_INTERNAL_SCHEDULER=false`
- Gunicorn should not start APScheduler
- dedicated scheduler service should start it explicitly

## 5. Dedicated Scheduler Process Design

The scheduler process should:

- load Django settings
- connect to the same PostgreSQL DB
- initialize APScheduler once
- register jobs once
- remain running under systemd

### Scheduler Process Responsibilities

- start scheduler
- register recurring jobs
- log execution failures
- expose clean service restart behavior

### Scheduler Process Must Not

- serve web requests
- run multiple copies unintentionally
- be started by every Gunicorn worker

## 6. systemd Strategy

Create a dedicated systemd service such as:

- `ispmanager-scheduler.service`

### Service Responsibilities

- load app environment
- use project virtualenv
- start one scheduler process
- restart on failure
- start on boot

### Operational Advantages

- separate logs through `journalctl`
- restart scheduler independently
- clearer failure boundaries
- easier debugging during outages

## 7. Job Safety Rules

Even with a separate scheduler service, jobs should still be written defensively.

### Rule 1: Jobs Must Be Idempotent

Examples:

- invoice generation should not recreate same invoice for same cycle
- overdue marking should be safe to rerun
- router status polling should only update state as needed

### Rule 2: Jobs Must Tolerate Partial Failure

Examples:

- if one router fails, all routers should not stop processing
- if one SMS fails, billing generation should remain successful

### Rule 3: Jobs Must Log Clearly

Every job should log:

- start
- completion
- count of affected records
- failure reason where relevant

### Rule 4: Jobs Must Avoid Unbounded Frequency

Production-safe polling intervals matter.

Do not run:

- excessive sub-second DB-heavy scheduler jobs

without validating DB capacity and locking behavior.

## 8. Job Categories in ISP Manager

## Financial Jobs

High-risk, must be strongly protected:

- invoice generation
- snapshot generation
- overdue marking
- auto-suspension

These should:

- be idempotent
- run in one scheduler only
- never duplicate silently

## Communication Jobs

Examples:

- billing SMS send
- Telegram notifications triggered by jobs

These should:

- avoid duplicate sends
- support clear delivery state

## Telemetry Jobs

Examples:

- router status polling
- traffic cache updates
- usage sampling

These should:

- use safe polling intervals
- avoid excessive write amplification
- be tuned for DB capacity

## Maintenance Jobs

Examples:

- auto-archive
- cleanup tasks

These should:

- be safe to rerun
- log what they changed

## 9. Scheduler and Database Considerations

### SQLite

SQLite is not a production-safe scheduler backend for this workload because:

- concurrent writes lock easily
- APScheduler execution logging also writes to DB
- telemetry polling adds frequent writes

### PostgreSQL

PostgreSQL is the expected production DB because:

- better concurrency
- safer scheduler coexistence
- stronger locking behavior for multi-process workloads

## 10. APScheduler Job Store Considerations

If using `django_apscheduler` in production:

- ensure only one scheduler service is writing job execution state
- avoid multiple schedulers sharing the same DB job store unintentionally

### Important Warning

Even with a persistent job store, multiple running schedulers are still a design risk.

Persistent job store is not a substitute for single-scheduler discipline.

## 11. Failure Scenarios and Mitigation

### Scenario 1: Gunicorn restarts

Risk:

- if scheduler lives inside Gunicorn, jobs may duplicate on worker restart

Mitigation:

- never bind scheduler lifecycle to Gunicorn workers in production

### Scenario 2: Scheduler process crashes

Risk:

- missed billing or telemetry jobs

Mitigation:

- restart with systemd
- alert on service failure
- monitor recent successful executions

### Scenario 3: Job runs too long

Risk:

- overlap with next schedule
- DB pressure

Mitigation:

- tune frequency
- add runtime logging
- make jobs incremental where possible

### Scenario 4: PostgreSQL outage

Risk:

- scheduler jobs fail
- state updates stop

Mitigation:

- alerting
- restart after DB recovery
- jobs should fail clearly, not silently

## 12. Monitoring Recommendations

Monitor the scheduler separately from the web app.

### Track

- scheduler service running state
- last successful execution per critical job
- consecutive failure count
- runtime duration
- lock or DB contention signals

### Critical Jobs to Watch

- invoice generation
- overdue marking
- auto-suspension
- router traffic cache updates
- subscriber usage sampling

## 13. Logging Recommendations

Scheduler logs should include:

- job name
- timestamp
- execution outcome
- affected counts
- error details

### Suggested Log Categories

- financial jobs
- telemetry jobs
- maintenance jobs
- notification jobs

## 14. Deployment Recommendation

When deploying to Ubuntu production:

- disable internal scheduler startup in web app
- run one dedicated scheduler service
- verify only one scheduler instance is active
- confirm PostgreSQL is used before enabling frequent telemetry jobs

## 15. Migration Path from Current Setup

### Phase 1

- keep current internal scheduler for local convenience
- add toggle to disable internal startup

### Phase 2

- create dedicated scheduler entrypoint/process
- create `systemd` scheduler service

### Phase 3

- disable scheduler from Gunicorn production workers completely
- run scheduler only as separate service

## 16. Final Recommendation

For production:

- `one web service`
- `one scheduler service`
- `PostgreSQL backend`
- `no scheduler inside Gunicorn workers`

This is the safest operational model for `ISP Manager` as it grows in:

- billing complexity
- telemetry frequency
- background automation
- concurrent runtime activity

