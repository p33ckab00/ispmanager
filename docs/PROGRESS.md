# ISP Manager v3 Enhanced - Build Progress

## Stack
- Backend: Django 5.0.6 + Django REST Framework 3.15.2
- Frontend: Django Templates + TailwindCSS (CDN) + HTMX + Alpine.js + Chart.js
- Database: PostgreSQL
- Deploy Target: Raspberry Pi / mini PC
- PDF: WeasyPrint
- MikroTik API: routeros-api
- SMS: Semaphore REST API
- Notifications: Telegram
- Scheduler: django-apscheduler

---

## All Modules Complete

| Module | Status | Key Features |
|--------|--------|-------------|
| core | DONE | First-run, audit log, dashboard live stats |
| settings_app | DONE | Global + billing + SMS + Telegram + router + subscriber + usage |
| routers | DONE | MikroTik API, port UI, live RX/TX, NAP nodes |
| subscribers | DONE | Full lifecycle, usage tracking, brownout detection, chart |
| billing | DONE | Invoice ledger + BillingSnapshot two-layer, PaymentAllocation, PDF |
| accounting | DONE | Income/expense, monthly P&L, CSV export |
| sms | DONE | Semaphore balance, bulk send, billing SMS from snapshot |
| notifications | DONE | Telegram per-event log, test button |
| diagnostics | DONE | Operations health center, alerts, scheduler truth, router/billing/messaging/usage health |
| landing | DONE | Homepage editor, captive portal, publish toggle |
| nms | DONE | Leaflet map, router + NAP + subscriber markers |
| data_exchange | DONE | CSV exports, subscriber/payment imports, dry-run, job history |

---

## Billing Architecture (Two-Layer)

Invoice = real receivable ledger (accounting truth)
BillingSnapshot = frozen client-facing statement (presentation)
PaymentAllocation = oldest-first payment posting

Rate source of truth: RateHistory with effective dates per subscriber
Snapshot modes: auto / draft (review window) / manual

---

## Subscriber Status Lifecycle

Active -> Suspended (PPP disabled on MikroTik)
Active -> Disconnected (voluntary, billing stops, data preserved)
Active/Suspended -> Deceased (open invoices voided, hidden from NMS)
Any -> Archived (hidden from all active views, data preserved)

---

## Data Exchange

Data Exchange v1 is now part of the operator workflow.

- Quick CSV export for subscribers, invoices, payments, and expenses
- Central Data Exchange dashboard for templates, imports, exports, and job history
- Dry-run validation before subscriber and payment imports
- Payment imports reuse the billing allocation flow so linked accounting income stays consistent

---

## Diagnostics

Diagnostics is now an operations health center instead of a small system-info page.

- overall health badge with active alerts
- PostgreSQL-aware runtime and database checks
- production-aware scheduler diagnostics using persisted APScheduler job history
- router and telemetry freshness checks
- billing integrity and palugit visibility
- messaging and notification failure visibility
- usage sampling freshness
- data exchange recent failures and audit activity
- dashboard widget now uses `/api/v1/diagnostics/health/` for truthful compact health status

---

## How to Run

```bash
# PostgreSQL-backed local/dev start
python manage.py migrate
python manage.py runserver 0.0.0.0:8193
```

## Raspberry Pi Deployment

```bash
pip install gunicorn
gunicorn config.wsgi:application --bind 0.0.0.0:8193 --workers 2
```

## Ubuntu Production Deployment

- Manual production deployment guide updated for fresh Ubuntu rollout
- New one-click installer script added at `deploy/install_ubuntu_fresh.sh`
- Deployment path now assumes:
  - preserve `/opt/libreqos`
  - back up legacy `/opt/isp-manager`
  - deploy fresh app into `/opt/ispmanager`
- Cloudflared tunnel-safe mode added:
  - detect and preserve existing `cloudflared.service`
  - fresh-install `cloudflared` only when absent
  - use localhost-only Nginx origin for tunnel deployments
- Cloudflare route and redeploy support added:
  - dashboard route checklist for tunnel hostname setup
  - `deploy/redeploy_ubuntu_update.sh` for future production updates
