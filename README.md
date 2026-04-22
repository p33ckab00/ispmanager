# ISP Manager

`ISP Manager` is a unified ISP operations platform for managing subscribers, routers, billing, payments, accounting, notifications, and subscriber self-service in one system.

## Overview

This project is designed for fixed wireless, fiber, and similar ISP operations that need a single back-office platform instead of separate spreadsheets, router-only workflows, and manual billing processes.

It centralizes:

- Subscriber lifecycle management
- Router and interface monitoring
- Billing and statement generation
- Payment posting and allocation
- Overdue handling and service enforcement
- SMS and Telegram notifications
- OTP-based subscriber portal
- Accounting and operational reporting

## Core Modules

- `apps/core` - authentication, dashboard, middleware, audit support
- `apps/settings_app` - billing, router, SMS, Telegram, subscriber, and usage settings
- `apps/routers` - router inventory, interface sync, traffic polling, MikroTik integration
- `apps/subscribers` - plans, subscribers, rate history, OTP, usage, lifecycle actions
- `apps/billing` - invoices, snapshots, payments, allocations, public billing links
- `apps/accounting` - income and expense tracking
- `apps/notifications` - notification records and Telegram integration
- `apps/sms` - SMS sending and logs
- `apps/diagnostics` - health and scheduler diagnostics
- `apps/nms` - network map views
- `apps/landing` - public landing and captive-style content
- `apps/data_exchange` - CSV import/export tools, dry-run validation, and job history

## Architecture

The recommended architecture is a `modular monolith` with background job support.

- Frontend: Django templates and admin/operator views
- API: REST endpoints under `/api/v1/`
- Backend: Django application modules by domain
- Database: PostgreSQL
- Background jobs: APScheduler-based task execution
- Integrations: MikroTik RouterOS API, Semaphore SMS, Telegram Bot API

## Key Features

- Subscriber CRUD and lifecycle state management
- Plan and rate history tracking
- Router inventory and connection validation
- PPP/session synchronization from MikroTik
- Invoice generation with historical rate awareness
- Billing snapshots and public billing URLs
- Payment recording with oldest-first allocation
- Overdue detection
- Portal OTP login for subscribers
- Daily usage rollups and usage charts
- Telegram and SMS notifications
- Accounting dashboards for income and expenses
- CSV import/export workflows for operational data exchange

## Documentation

Project documentation starts here:

- [Master Project Spec](docs/00_master_project_spec.md)
- [Project Setup](docs/01_project_setup.md)
- [Settings App](docs/02_settings_app.md)
- [Routers](docs/03_routers.md)
- [Subscribers](docs/04_subscribers.md)
- [Billing](docs/05_billing.md)
- [PostgreSQL Installation Workflow](docs/07_postgresql_installation_workflow.md)
- [Production Deployment Workflow](docs/08_production_deployment_workflow.md)
- [PostgreSQL Migration Plan](docs/09_postgresql_migration_plan.md)
- [Scheduler Production Strategy](docs/10_scheduler_production_strategy.md)
- [Environment Variables Reference](docs/11_environment_variables_reference.md)
- [Backup and Restore Runbook](docs/12_backup_restore_runbook.md)
- [Staging Checklist](docs/13_staging_checklist.md)
- [Go-Live Checklist](docs/14_go_live_checklist.md)
- [Ubuntu Production Manual Install Guide](docs/21_ubuntu_production_manual_install_guide.md)
- [Ubuntu Scheduler Service Guide](docs/22_ubuntu_scheduler_workaround_guide.md)
- [Production Hardening Checklist](docs/23_production_hardening_checklist.md)
- [Overdue and Palugit Current Workflow](docs/24_overdue_grace_current_workflow.md)
- [Overdue Palugit Implementation Plan](docs/25_overdue_grace_workflow_implementation_plan.md)
- [Overdue Grace Implementation Notes](docs/26_overdue_grace_implementation_notes.md)
- [Landing Public Homepage and Admin Auth Update](docs/27_landing_public_homepage_and_auth.md)
- [Landing V2 Core Discussion](docs/28_landing_v2_core_discussion.md)
- [Landing V2 Core Implementation Plan](docs/29_landing_v2_core_implementation_plan.md)
- [Landing V2 Core Implementation Notes](docs/30_landing_v2_core_implementation_notes.md)
- [Landing Nav UX Refinement](docs/31_landing_nav_ux_refinement.md)
- [Data Exchange V1 Implementation Notes](docs/32_data_exchange_v1_implementation_notes.md)
- [Router Telemetry UX Upgrade](docs/33_router_telemetry_ux_upgrade.md)
- [Landing Helper Copy Cleanup](docs/34_landing_helper_copy_cleanup.md)
- [Ubuntu Env Template](deploy/ispmanager_ubuntu.env.template)

## Current Product Direction

Based on the current project design:

- Billing should start from system go-live or `billing_effective_from`
- Historical subscriber `start_date` should be preserved for reference
- Full backtracking of already-paid legacy billing periods is not recommended
- Live telemetry should be redesigned with a backend cache/sampler layer before moving to sub-second UI refresh

## Production Goals

- Accurate invoice generation
- Reliable payment posting and allocation
- Consistent router and subscriber state
- Better collections through reminders and self-service access
- Clear operational visibility for staff and NOC users

## Suggested Next Technical Priorities

- Fix routing and scheduler runtime issues
- Strengthen Telegram and notification wiring
- Improve subscriber usage sampling visibility
- Redesign live telemetry polling for near-real-time charts and port activity UI
- Harden settings so all configurable values are actually wired into runtime behavior

## PostgreSQL Configuration

The project now runs on PostgreSQL only.

Required database environment variables:

1. `POSTGRES_DB`
2. `POSTGRES_USER`
3. `POSTGRES_PASSWORD`
4. `POSTGRES_HOST`
5. `POSTGRES_PORT`
6. `POSTGRES_CONN_MAX_AGE`

Recommended setup flow:

1. Install dependencies with `pip install -r requirements.txt`
2. Copy `.env.example` values into your real `.env`
3. Fill in `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT`
4. Run `python manage.py migrate`
5. Verify scheduler, billing, router sync, accounting, and usage tracking against PostgreSQL
