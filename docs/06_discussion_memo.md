# ISP Manager Discussion Memo

No code generated. No files generated. This document is a discussion-ready Markdown version of the audit and design recommendations.

## 1. Billing Decision: Backtracking vs Forward-Only

### Recommendation
Stick to forward-only billing.

### Why
Full billing backtracking for old subscribers is possible, but it is usually the wrong tradeoff for this system stage because it adds:

- Heavy manual encoding of past cycles
- Risk of incorrect paid/unpaid reconstruction
- Harder reconciliation if the old records were outside the system
- Extra logic for partials, waivers, plan/rate history, and old due dates
- More support burden than business value

### Best Design
For subscribers that started before go-live, for example `September 5, 2025` while the system goes live in `April 2026`:

- Keep `start_date = 2025-09-05` for historical reference
- Set `billing_effective_from = go-live date`
- Generate invoices only from go-live onward
- Treat older periods as `legacy-settled outside system`

### Better Compromise Than Full Backtracking
If historical context is needed later without recreating all old invoices, add a lightweight onboarding concept such as:

- `legacy_onboarding_date`
- `legacy_account_note`
- `legacy_balance_at_go_live`
- `legacy_status = settled | with_balance | unknown`

This is much safer than backfilling `6-12` months of invoices.

### Final Call
Do not backtrack invoices.

Current design direction is better. Use `start_date` for tenure and historical reference, and begin billing from go-live or `billing_effective_from`.

## 2. Live Telemetry Recommendation

### Target
The desired UX is:

- Near-live router status and traffic
- Physical ethernet port cards with LED-like activity
- Smooth line chart like a heartbeat
- `500ms` UI refresh feel

### Recommendation
Do not poll MikroTik directly every `500ms` from the browser path.

### Why
Current live traffic flow is direct router call per refresh through:

- `apps/routers/views.py`
- `apps/routers/services.py`
- `apps/routers/mikrotik.py`
- `templates/routers/interface_detail.html`

That is acceptable for `10s`, but unsafe for `500ms`.

### Best Architecture
Use a two-layer design.

#### Backend Sampler
- Poll routers every `2s` to `5s`
- Collect all required interface stats in batch
- Store latest values in cache or a lightweight latest-state table

#### Frontend Live UI
- Poll a Django endpoint every `500ms`
- Read cached data only
- Update chart and LEDs smoothly
- Avoid direct MikroTik calls on each UI tick

### UI/UX Recommendation
For physical ports in router detail:

- Green pulse: traffic active
- Amber solid: link up, no traffic
- Red solid: down
- Small RX/TX numeric badges
- Chart with last `30s` or `60s` rolling window
- Do interpolation and animation in the frontend, not by forcing router polling to `500ms`

### Best Practical Polling Targets
- Router sampler: `2s` to `5s`
- Browser fetch: `500ms` to `1s`
- Chart window: `60` points maximum for smoothness

## 3. Audit Findings

### High Priority

#### 3.1 Accounting Back Link 404
Confirmed root cause:

- `templates/accounting/expense_form.html`

The back link uses `/accounting/expense/`, but the valid route is `/accounting/expenses/` from:

- `apps/accounting/urls.py`

This matches the reported `404` exactly.

#### 3.2 Diagnostics Scheduler "Run Now" crashes on `pytz`
Confirmed root cause:

- `apps/diagnostics/views.py`

`run_job_now()` hard-imports `pytz`, but `pytz` is not present in:

- `requirements.txt`

This is a real runtime bug.

#### 3.3 Scheduler Auto-Archive has hidden runtime bug
In:

- `apps/core/scheduler.py`

`job_auto_archive()` references:

- `date.today()`
- `models.Q(...)`

but those names are not imported in that function or module scope.

This is another runtime failure waiting to happen.

#### 3.4 Live telemetry path is not built for `500ms`
Current implementation:

- `templates/routers/interface_detail.html`
- `templates/routers/partials/traffic_widget.html`
- `apps/routers/views.py`
- `apps/routers/services.py`

Gap summary:

- Every refresh triggers a router API call
- No cache layer
- No rolling time-series for smooth charting
- No physical-port activity state model

#### 3.5 Usage sampling is fragile and "no data" UX is weak
Files:

- `apps/core/scheduler.py`
- `apps/subscribers/services.py`
- `apps/subscribers/views.py`
- `templates/subscribers/detail.html`

Gaps:

- Usage data only appears if the router is online and PPP session counters are available
- Empty chart state is not handled as a product experience
- No explicit "waiting for first sample" state
- No operator hint explaining why usage is empty

#### 3.6 Telegram status is partially wired, but dashboard check is misleading
Files:

- `apps/notifications/telegram.py`
- `apps/settings_app/serializers.py`
- `templates/core/dashboard.html`

Important gap:

- Dashboard checks `d.bot_token && d.enable_notifications`
- Telegram serializer makes `bot_token` write-only
- API `GET` cannot return it
- Result: dashboard can falsely show `Not configured` even when Telegram is configured

#### 3.7 Several settings exist in UI/model but are not fully wired
Files:

- `apps/settings_app/models.py`
- `apps/billing/services.py`
- `apps/core/scheduler.py`
- `apps/sms/services.py`

Observed gaps:

- `due_days` is present but not used in invoice due-date calculation
- `grace_period_days` is present but `mark_overdue_invoices()` ignores it
- `enable_auto_disconnect` exists but no automatic suspend job uses it
- `polling_interval_seconds` exists but scheduler polling is hardcoded
- `sync_on_startup` exists but is not used to trigger sync behavior
- `connection_timeout_seconds` exists but router connector does not use it
- `cutoff_snapshot_enabled` exists but is not used in snapshot workflow
- `billing_sms_schedule` exists but SMS scheduler is hardcoded to `08:00`

### Medium Priority

#### 3.8 Core dashboard has a broken billing quick link
In:

- `templates/core/dashboard.html`

It links to `/billing/generate/`, but billing URLs are defined in:

- `apps/billing/urls.py`

Current valid path is `/billing/invoices/generate/`.

#### 3.9 Hardcoded URLs are causing drift risk
The repository uses many literal paths in templates instead of named routes, including:

- `templates/partials/sidebar.html`
- `templates/accounting/expense_form.html`
- `templates/core/dashboard.html`

This is why small singular/plural mismatches are slipping through.

#### 3.10 Public billing SMS link is hardcoded to localhost
In:

- `apps/sms/services.py`

Billing SMS link uses `http://localhost:8000/...`, which will break in real deployment.

#### 3.11 Portal OTP flow hides SMS send failure
In:

- `apps/subscribers/views.py`

OTP send errors are swallowed with `except Exception: pass`.

Result:

- User sees `OTP sent`
- But SMS may actually have failed

#### 3.12 Notification model is too thin for retry and ops visibility
In:

- `apps/notifications/models.py`

Gaps:

- No channel field
- No retry count
- No `last_attempt_at`
- No payload metadata
- No distinction between skipped-by-setting and failed-to-send

## 4. Telegram Wiring Conclusion

### What is already correct
- Settings form posts to the right view
- Notification events are called from several flows
- Test button uses the same send path
- Event-specific toggles are mapped in `EVENTS`

### What likely causes confusion
- Dashboard config check is unreliable because `bot_token` is write-only in API
- Automated notifications only fire if both of these are true:
  - `enable_notifications = true`
  - Event-specific toggle is true
- If an event is filtered by settings, no clear operator feedback is shown

### Recommendation
Keep the Telegram feature. It is not fundamentally broken.

But it needs:

- Clearer config-state indicator
- Explicit logging for `skipped due to settings`
- Better notification audit state

## 5. Usage Tracking Conclusion

### What is already there
- Raw samples
- Daily rollups
- Chart endpoint
- Portal and detail chart UI

### Main issue
The system is technically wired, but operationally weak because:

- It depends on online router session counters
- There is no cache or live layer
- There is no graceful empty state
- Scheduler failures block confidence in the feature

### Recommendation
Prioritize this after fixing the runtime bugs above.

## 6. Suggested Implementation Order Once You Say GO

### 6.1 Fix hard runtime bugs
- Diagnostics `pytz`
- Scheduler auto-archive imports
- Accounting expense back-link
- Core dashboard broken billing link

### 6.2 Fix misleading or missing settings wiring
- Telegram dashboard status
- Due, grace, and auto-disconnect settings
- Billing SMS schedule usage
- Router timeout and polling settings usage

### 6.3 Stabilize subscriber usage
- Confirm scheduler execution path
- Improve `no data yet` states
- Surface sampling health in UI

### 6.4 Redesign live telemetry properly
- Add backend cache/latest-state layer
- Batch poll router traffic
- Expose lightweight JSON endpoint
- Build `500ms` UI updates from cache, not router
- Add LED state model for physical ports

### 6.5 Improve notifications operational visibility
- Better log states
- Skipped vs failed distinction
- Retry metadata

## 7. GO / No-GO Recommendation

### Recommendation
GO for fixes and telemetry redesign, but not for billing backtracking.

### Scope recommended when approved
- Fix current runtime and routing issues
- Wire settings that currently do nothing
- Make usage tracking visibly functional
- Redesign live router telemetry for smooth UX
- Improve Telegram operational clarity

### Scope not recommended
- Historical invoice backfill for old paid periods

### Final Trigger
If implementation should proceed, the action keyword is:

`GO`
