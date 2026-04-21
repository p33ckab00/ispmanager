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

## Architecture

The recommended architecture is a `modular monolith` with background job support.

- Frontend: Django templates and admin/operator views
- API: REST endpoints under `/api/v1/`
- Backend: Django application modules by domain
- Database: currently SQLite in local development, with PostgreSQL recommended for production
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

## Documentation

Project documentation starts here:

- [Master Project Spec](docs/00_master_project_spec.md)
- [Project Setup](docs/01_project_setup.md)
- [Settings App](docs/02_settings_app.md)
- [Routers](docs/03_routers.md)
- [Subscribers](docs/04_subscribers.md)
- [Billing](docs/05_billing.md)

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

## GitHub Publishing

This folder is currently **not initialized as a Git repository**. That means we can still prepare the project for GitHub, but publishing will require:

1. Initializing Git in this project folder
2. Creating the first commit
3. Connecting a GitHub repository under your account
4. Pushing the branch

If you want, I can do that next and help publish it to your GitHub account at `https://github.com/p33ckab00` once you confirm the target repository name.
