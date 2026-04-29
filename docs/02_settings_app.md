# Step 02 - settings_app

## Status: DONE

---

## What Was Built

### New Files

| File | Purpose |
|------|---------|
| apps/settings_app/models.py | All settings models |
| apps/settings_app/forms.py | Forms for each settings section |
| apps/settings_app/views.py | One view per settings section |
| apps/settings_app/urls.py | URL routes for settings pages |
| apps/settings_app/serializers.py | DRF serializers (API key fields write-only) |
| apps/settings_app/api_views.py | GET + PATCH endpoints per settings group |
| apps/settings_app/api_urls.py | /api/v1/settings/ routes |
| apps/settings_app/migrations/0001_initial.py | Auto-generated migration |
| templates/settings_app/base_settings.html | Settings sidebar layout |
| templates/settings_app/index.html | Settings landing page |
| templates/settings_app/system_info.html | ISP name, address, logo |
| templates/settings_app/billing_settings.html | Billing day, due days, auto-generate |
| templates/settings_app/sms_settings.html | Semaphore API key, template, schedule |
| templates/settings_app/telegram_settings.html | Bot token, chat ID, notify toggles |
| templates/settings_app/router_settings.html | API port, poll interval, timeout |

---

## Models

### GlobalSetting
- Key-value store for arbitrary settings
- get(key, default) and set(key, value) classmethods
- Used for one-off settings that do not need a full model

### BillingSettings (singleton pk=1)
- billing_day: default cutoff day (1-31, with month-end fallback for short months)
- due_days: days after billing day before overdue
- grace_period_days: days before disconnection
- currency_symbol: default PHP
- enable_auto_generate: toggle auto bill generation
- enable_auto_disconnect: toggle auto disconnect

### SMSSettings (singleton pk=1)
- semaphore_api_key: stored in DB (write-only in API)
- sender_name: max 11 chars (Semaphore limit)
- billing_sms_schedule: HH:MM time string
- billing_sms_days_before_due: how early to send
- billing_sms_repeat_interval_days: repeat reminder interval while unpaid
- billing_sms_send_after_due: continue collections reminders after due date
- billing_sms_after_due_interval_days: repeat interval for after-due reminders
- billing_sms_template: supports {name} {amount} {currency} {due_date} {link}

### TelegramSettings (singleton pk=1)
- bot_token + chat_id
- enable_notifications master toggle
- Per-event toggles: new subscriber, status change, router status, billing, payment, sms, plan change, settings change, API errors

### RouterSettings (singleton pk=1)
- default_api_port: 8728
- polling_interval_seconds: live telemetry poll rate
- sync_on_startup: auto sync subscribers on boot
- connection_timeout_seconds: MikroTik API timeout

---

## URL Routes

| URL | View | Name |
|-----|------|------|
| /settings/ | settings_index | settings-index |
| /settings/system/ | system_info | settings-system-info |
| /settings/billing/ | billing_settings | settings-billing |
| /settings/sms/ | sms_settings | settings-sms |
| /settings/telegram/ | telegram_settings | settings-telegram |
| /settings/router/ | router_settings | settings-router |

## API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET/PATCH | /api/v1/settings/billing/ | Billing settings |
| GET/PATCH | /api/v1/settings/sms/ | SMS settings |
| GET/PATCH | /api/v1/settings/telegram/ | Telegram settings |
| GET/PATCH | /api/v1/settings/router/ | Router settings |

---

## Key Decisions

- All settings models use singleton pattern (get_or_create pk=1)
- API keys (Semaphore, Telegram bot token) are write_only in DRF serializers
- AuditLog.log() called on every settings save
- Telegram notify fields passed as list of tuples to template for clean rendering

---

## Next Step
Step 03: routers app - MikroTik API connection, port UI, live telemetry
