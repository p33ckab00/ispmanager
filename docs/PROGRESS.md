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
| diagnostics | DONE | Disk, DB, router ping, scheduler status |
| landing | DONE | Homepage editor, captive portal, publish toggle |
| nms | DONE | Leaflet map, router + NAP + subscriber markers |

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
