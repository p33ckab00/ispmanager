# Billing Mode Workflow Guide

This guide documents the current `Settings > Billing > Billing Mode` behavior in the codebase.

## Summary

`BillingSettings.billing_mode` has two choices:

- `legacy` - `Legacy Due Day`
- `cutoff_advance` - `Cutoff Advance Billing`

Current implementation note:

- The setting is saved by the billing settings form and exposed through the settings API.
- The invoice, billing snapshot, usage cutoff snapshot, SMS, and overdue workflows do not branch on `billing_mode`.
- In practice, both `Legacy Due Day` and `Cutoff Advance Billing` currently use the same cutoff-based advance billing calculation.

Treat `billing_mode` as a UI/config label until a mode-specific branch is implemented in `apps/billing/services.py`.

## Source Map

| Area | File | Current role |
| --- | --- | --- |
| Billing mode choices and defaults | `apps/settings_app/models.py` | Defines `legacy` and `cutoff_advance`; default is `cutoff_advance`. |
| Settings form | `apps/settings_app/forms.py` | Saves `billing_day`, `due_days`, `billing_due_offset_days`, `billing_mode`, snapshot settings, and toggles. |
| Settings page | `templates/settings_app/billing_settings.html` | Shows Billing Mode dropdown plus default cutoff and due fields. |
| Core billing calculation | `apps/billing/services.py` | Resolves cutoff day, period, due offset, due date, invoices, snapshots, and overdue status. |
| Billing scheduler | `apps/core/scheduler.py` | Runs invoice generation, snapshot generation, draft auto-freeze, overdue marking, SMS, and auto-suspend jobs. |
| Subscriber overrides | `apps/subscribers/models.py` | Stores per-subscriber `cutoff_day`, `billing_type`, `billing_due_days`, and `is_billable`. |

## Settings Fields

| Field | Meaning in current code |
| --- | --- |
| `billing_day` | Default cutoff day, limited to 1-31. Used when a subscriber has no custom `cutoff_day`; short months use month-end fallback. |
| `due_days` | Legacy/default due-day fallback. Used only when no subscriber due override exists and `billing_due_offset_days` is `0` or blank. |
| `billing_due_offset_days` | Preferred global due offset after cutoff when non-zero. |
| `billing_mode` | Stored/displayed mode, but not used by calculation logic today. |
| `billing_snapshot_mode` | Controls snapshot status: `auto` freezes immediately, `draft` creates draft, `manual` skips scheduler snapshot generation. |
| `draft_auto_freeze_hours` | Auto-freeze age for draft snapshots. |
| `enable_auto_generate` | Enables the daily invoice generation job. |
| `enable_auto_disconnect` | Enables auto-suspend for subscribers with overdue invoices. |
| `grace_period_days` | Extra days after due date before invoices are marked overdue. |

Due offset precedence:

1. Subscriber `billing_due_days`, when set. A subscriber value of `0` means use the billing-type base due date.
2. Global `billing_due_offset_days`, when non-zero.
3. Global `due_days`, when non-zero.
4. `0`.

Important nuance: because the global fallback uses `billing_due_offset_days or due_days or 0`, setting global `billing_due_offset_days = 0` does not force same-day due if `due_days` is still greater than `0`. For global same-day due, set both fields to `0`. Subscriber-level `billing_due_days = 0` works because subscriber override is checked with `is not None`.

## Current Cutoff and Billing Type Workflow

Current invoice and snapshot generation flows use `resolve_billing_profile()`.

1. Resolve cutoff day:
   - Use subscriber `cutoff_day` if set.
   - Otherwise use `BillingSettings.billing_day`.
2. Resolve the effective cutoff date for the month.
   - Cutoff supports `1-31`.
   - If the configured cutoff does not exist in a month, use that month's last day.
3. Resolve target service period based on subscriber `billing_type`.
   - `postpaid`: use the cycle containing the reference date; due date normally equals `period_end`.
   - `prepaid`: use the next advance-billed cycle; due date normally equals `period_start`.
4. Set `cutoff_date = period_end`.
5. Set `generation_date`.
   - `postpaid`: `generation_date = period_end`.
   - `prepaid`: `generation_date = period_start - 1 day`.
6. Resolve due offset using subscriber override, global due offset, then legacy/default due days.
7. Add due offset to the billing-type base due date.
8. Use the rate effective on the reference date.
9. Create or reuse one invoice per subscriber and `period_start`.

Example for a postpaid subscriber with cutoff day `28`:

| Reference date | Target period | Cutoff date | Generation date | Due date if offset is 0 |
| --- | --- | --- | --- | --- |
| May 25, 2026 | Apr 29-May 28, 2026 | May 28, 2026 | May 28, 2026 | May 28, 2026 |
| May 28, 2026 | Apr 29-May 28, 2026 | May 28, 2026 | May 28, 2026 | May 28, 2026 |

Example for a prepaid subscriber with cutoff day `28`:

| Reference date | Target period | Cutoff date | Generation date | Due date if offset is 0 |
| --- | --- | --- | --- | --- |
| May 28, 2026 | May 29-Jun 28, 2026 | Jun 28, 2026 | May 28, 2026 | May 29, 2026 |

## Planned Billing Model

This section documents the agreed target direction. It is a planning record, not a description of the current implementation.

### Cutoff day 1-31 with month-end fallback

Target rule:

- Cutoff day should support `1-31`.
- When the month is shorter than the configured cutoff day, use the last day of that month.

Examples:

| Configured cutoff | February 2026 | February 2028 | April 2026 | May 2026 |
| --- | --- | --- | --- | --- |
| `28` | Feb 28 | Feb 28 | Apr 28 | May 28 |
| `30` | Feb 28 | Feb 29 | Apr 30 | May 30 |
| `31` | Feb 28 | Feb 29 | Apr 30 | May 31 |

Important implementation rule:

- Billing logic must compare against the effective cutoff date for the current month, not only the raw cutoff number.
- Example: if configured cutoff is `30`, February 28, 2026 is already the effective cutoff date even though `28 < 30`.

This affects:

- billing profile period calculation
- invoice generation timing
- billing snapshot generation timing
- usage cutoff snapshot generation
- scheduler filters
- settings validation
- subscriber validation
- data import validation
- UI helper text
- documentation examples
- tests around February, leap years, April 30, and December-January rollover

The current raw-day scheduler filter is not enough for this target model. Subscribers with cutoff `30` or `31` must still be selected on February 28 or February 29 when that is the effective cutoff date.

### Cycle boundaries

Target cycle rule:

- A cycle starts the day after the previous effective cutoff.
- A cycle ends on the current effective cutoff.

Example:

| Service start | Cutoff day | Billing period |
| --- | --- | --- |
| Apr 29, 2026 | `28` | Apr 29-May 28, 2026 |

This is calendar-cycle billing, not fixed 30-day billing.

### Subscriber billing type

Target rule:

- Each subscriber should have a billing type.
- `postpaid` means the subscriber uses the service first, then pays for the completed/current service cycle.
- `prepaid` means the subscriber pays before using the next service cycle.

Recommended source of truth:

- subscriber-level billing type
- optional global default later
- optional plan-level default later

Subscriber-level should win because real ISP operations often mix prepaid and postpaid accounts.

### Postpaid due-date behavior

For postpaid accounts:

- The subscriber uses the service during the cycle.
- Due date should normally be the cycle end date, unless a due offset is explicitly configured.

Example:

| Service start | Cutoff day | Billing period | Due date |
| --- | --- | --- | --- |
| Apr 29, 2026 | `28` | Apr 29-May 28, 2026 | May 28, 2026 |

This matches the desired behavior: the client uses the plan first, then receives billing near or at the end of the covered period.

### Prepaid due-date behavior

For prepaid accounts:

- The subscriber should pay before or at the beginning of the service cycle.
- Recommended due date is the cycle start date.

Example:

| Cycle | Cutoff day | Billing period | Due date |
| --- | --- | --- | --- |
| Current cycle | `28` | Apr 29-May 28, 2026 | Apr 29, 2026 |
| Next cycle | `28` | May 29-Jun 28, 2026 | May 29, 2026 |

This keeps prepaid easy to explain: payment is due when the prepaid service period starts.

## Current Billing SMS Workflow

The billing SMS workflow now has a due-date reminder schedule with duplicate tracking.

Current SMS behavior:

- Send billing SMS based on the frozen billing snapshot due date.
- Send only while the invoice still has an unpaid balance.
- Stop reminders once paid.
- Avoid duplicate sends for the same billing snapshot and reminder date.
- Track reminder stage, reminder run date, and billing due date on `SMSLog`.

Current SMS settings:

| Setting | Purpose |
| --- | --- |
| `billing_sms_days_before_due` | First reminder lead time, for example `3` days before due date. |
| `billing_sms_repeat_interval_days` | Repeat interval, for example every `2` days. |
| `billing_sms_send_after_due` | Enables collections reminders after the due date. |
| `billing_sms_after_due_interval_days` | Repeat interval after the due date. |
| `enable_billing_sms` | Master switch for scheduled billing SMS. |

Example postpaid reminder schedule:

| Billing period | Due date | SMS setting | Send dates |
| --- | --- | --- | --- |
| Apr 29-May 28, 2026 | May 28, 2026 | 3 days before due, repeat every 2 days, send on due date | May 25, May 27, May 28 |

If payment is recorded on May 26, the May 27 and May 28 reminders should not send.

Important generation timing:

- If SMS should send before the due date, the invoice or snapshot must already exist before the first reminder date.
- For postpaid billing, this means the billing job should create the bill once its due date is inside the SMS lead window, not only on the cutoff date itself.

Example:

| Date | Desired behavior |
| --- | --- |
| Apr 29, 2026 | Service period starts. |
| May 25, 2026 | Bill exists and first reminder can be sent. |
| May 27, 2026 | Repeat reminder can be sent if unpaid. |
| May 28, 2026 | Due-day reminder can be sent if unpaid. |

### SMS eligibility after billing generation

Target rule:

- Send billing SMS based on the due-date reminder schedule, not just the billing generation event.

Billing generation creates or freezes the bill. It should not automatically mean "send SMS immediately" unless the bill is already eligible under the reminder schedule.

SMS eligibility rules:

- SMS can send only after the invoice or billing snapshot exists.
- If the bill is generated before the reminder window, wait until the configured reminder date.
- If the bill is generated inside the reminder window, send on the next scheduled SMS run.
- If the bill is generated on the due date, send a due-day SMS only when due-day reminders are enabled.
- If the bill is generated after the due date, send only when after-due reminders are enabled.
- If the invoice is fully paid before the scheduled SMS run, do not send.
- If the invoice is partially paid, reminders may continue using the remaining balance.

Example postpaid schedule:

| Billing period | Due date | Bill generation date | SMS rule | Expected SMS behavior |
| --- | --- | --- | --- | --- |
| Apr 29-May 28, 2026 | May 28, 2026 | May 20, 2026 | 3 days before due, repeat every 2 days, send on due date | Wait until May 25, then send May 25, May 27, and May 28 if unpaid. |
| Apr 29-May 28, 2026 | May 28, 2026 | May 25, 2026 | Same settings | Send on the next scheduled SMS run on or after May 25 if unpaid. |
| Apr 29-May 28, 2026 | May 28, 2026 | May 28, 2026 | Due-day reminders enabled | Send on the next scheduled SMS run on May 28 if unpaid. |
| Apr 29-May 28, 2026 | May 28, 2026 | May 29, 2026 | After-due reminders disabled | Do not send scheduled billing SMS. |
| Apr 29-May 28, 2026 | May 28, 2026 | May 29, 2026 | After-due reminders enabled | Send according to the after-due reminder policy if unpaid. |

## Planned Implementation Checklist

1. Define a reusable effective cutoff date rule for any configured cutoff day `1-31`.
2. Replace raw day comparisons with effective cutoff date comparisons.
3. Update billing period calculation to use previous and current effective cutoffs.
4. Update scheduler filters so cutoff `30` and `31` subscribers are selected on month-end fallback dates.
5. Add subscriber billing type, starting with `postpaid` and `prepaid`.
6. Define due date rules for prepaid and postpaid accounts.
7. Update invoice and snapshot generation so billing can be created before due date when SMS reminders require it.
8. Add SMS repeat scheduling and duplicate-send protection.
9. Keep overdue and auto-suspend based on invoice due date plus grace period.
10. Keep settings form validation aligned with cutoff `1-31`.
11. Keep subscriber form validation aligned with cutoff `1-31`.
12. Update data import validation for cutoff day `1-31`.
13. Update UI helper text and docs to explain month-end fallback behavior.
14. Add tests for cutoff `28`, `29`, `30`, and `31`, including February leap and non-leap years.

## Planned Flow Against Current Codebase

The current codebase already has the right major building blocks:

| Current module | Future role |
| --- | --- |
| `apps/billing/services.py` | Main billing engine for cutoff calculation, cycle resolution, invoice generation, snapshot generation, due dates, and overdue status. |
| `apps/core/scheduler.py` | Daily orchestration for invoice generation, snapshot generation, SMS reminders, overdue marking, and auto-suspend. |
| `apps/sms/services.py` | Billing SMS sender, reminder scheduler logic, and duplicate tracking. |
| `apps/billing/models.py::Invoice` | Accounting and receivable source of truth. |
| `apps/billing/models.py::BillingSnapshot` | Client-facing billing statement. |
| `apps/subscribers/models.py::Subscriber` | Subscriber-level billing settings, including future prepaid/postpaid type. |

Current limitation:

- The system has started moving beyond cutoff-advance billing by adding subscriber `billing_type`.
- Cutoff behavior now supports `1-31` with month-end fallback in the billing profile foundation.
- Due date now uses the subscriber billing type base date plus due offset.
- Invoice generation runs daily for all active or suspended billable subscribers.
- Snapshot generation runs when today's date matches the effective cutoff date.
- Scheduled billing SMS uses frozen snapshots whose due date is inside the configured lead window.
- Repeat billing SMS scheduling and duplicate reminder-date tracking are implemented through `SMSLog`.

Target billing flow:

1. The daily billing job checks active or suspended billable subscribers.
2. For each subscriber, the billing engine resolves the configured cutoff day.
3. If the configured cutoff does not exist in the target month, the effective cutoff becomes the last day of that month.
4. The billing engine calculates the cycle from the previous effective cutoff plus one day through the current effective cutoff.
5. The subscriber billing type determines the due date:
   - `postpaid`: due date normally equals `period_end`.
   - `prepaid`: due date normally equals `period_start`.
6. The billing job creates an invoice and snapshot when the due date is inside the billing or SMS lead window.
7. The SMS job sends reminders only for unpaid invoices or snapshots.
8. Reminder sending follows SMS settings such as first reminder lead days, repeat interval, and due-day reminder.
9. Reminders stop once the invoice is fully paid.
10. Overdue and auto-suspend continue to use invoice due date plus grace period.

Example postpaid flow:

| Date | Behavior |
| --- | --- |
| Apr 29, 2026 | Service period starts for Apr 29-May 28. |
| May 25, 2026 | Invoice/snapshot should already exist so the first reminder can send 3 days before due. |
| May 27, 2026 | Repeat SMS can send if the account is still unpaid. |
| May 28, 2026 | Due-date SMS can send if enabled and still unpaid. |
| After May 28, 2026 | Overdue handling starts according to grace period settings. |

Example prepaid flow:

| Date | Behavior |
| --- | --- |
| Apr 29, 2026 | Payment is due for Apr 29-May 28 service. |
| May 26, 2026 | First reminder can send for the next May 29-Jun 28 prepaid cycle if configured as 3 days before due. |
| May 28, 2026 | Repeat reminder can send if still unpaid. |
| May 29, 2026 | Due-date reminder can send for the next prepaid cycle if enabled and still unpaid. |

### Planned payment behavior

The billing model should allow normal real-world payment timing. A subscriber billing type describes when payment is expected, but it should not prevent valid payment scenarios.

Target rules:

- Early payment is allowed.
- Advance payment is allowed.
- Partial payment is allowed.
- Overpayment becomes account credit.
- Account credit should auto-apply to the oldest unpaid invoice first.
- SMS reminders should stop only when the invoice is fully paid.
- If an invoice is partially paid, reminders may continue but should show the remaining balance.
- Overdue status should be based on remaining balance plus due date and grace period.

Postpaid early payment example:

| Billing type | Billing period | Due date | Payment date | Expected behavior |
| --- | --- | --- | --- | --- |
| `postpaid` | Apr 29-May 28, 2026 | May 28, 2026 | May 10, 2026 | Payment is accepted. If the invoice exists, it is applied to that invoice. If fully paid, reminders stop and the invoice never becomes overdue. |

If a postpaid customer pays before the invoice exists, the target system should handle this in one of two safe ways:

1. Create the upcoming invoice early and apply the payment to it.
2. Record the payment as account credit and automatically apply that credit when the future invoice is created.

The preferred long-term behavior is formal account credit handling, because it also supports overpayments and other advance-payment cases.

Overdue partial payment example:

| Invoice amount | Current status | Payment | Remaining balance | Expected behavior |
| --- | --- | --- | --- | --- |
| PHP 1,000 | `overdue` | PHP 500 | PHP 500 | Payment is accepted. Invoice remains collectible. Reminder or collection flow may continue using the remaining balance. |

Current-code note:

- The existing payment allocation logic already accepts partial payments against `open`, `partial`, and `overdue` invoices.
- If an overdue invoice receives a partial payment, current code can set it to `partial`.
- The overdue job can later mark it `overdue` again if it is still past due plus grace period.

Target status semantics should be explicit:

| Status | Meaning |
| --- | --- |
| `paid` | Fully settled. |
| `partial` | Partially paid and not yet overdue by due/grace rules. |
| `overdue` | Has remaining balance and is past due/grace rules, even if partially paid. |

Main codebase impact:

- `get_next_cutoff_period()` should be replaced or refactored into a month-aware cutoff/cycle resolver.
- `get_cutoff_day_queryset_filter()` should no longer rely only on raw day equality.
- Invoice and snapshot jobs should generate billing based on due/reminder windows, not only today's cutoff day.
- Subscriber records need a billing type such as `postpaid` or `prepaid`.
- Payment allocation needs formal account credit handling for early payments and overpayments.
- SMS settings need repeat interval, due-day reminder, and optional after-due reminder controls.
- SMS sending needs duplicate protection by invoice or snapshot and reminder date or stage.
- Settings, subscriber forms, import validation, and UI helper text need to support cutoff `1-31`.
- Tests should cover cutoff `29`, `30`, and `31`, including February and leap years.

## Planned Billing System Improvements

These improvements are recommended after the prepaid/postpaid and cutoff `1-31` model is defined. They should be implemented in priority order so the billing truth is stable before adding more automation.

### Priority roadmap

1. Cutoff `1-31` with month-end fallback.
2. Subscriber billing type: `prepaid` and `postpaid`.
3. Due-date based invoice and snapshot generation.
4. Billing SMS reminder engine with duplicate protection.
5. Account credit and advance payment handling.
6. Billing adjustments and billing ledger.
7. Auto-reconnect after full payment.
8. Billing preview before issue.
9. Billing Calendar & Queue workspace.
10. Billing health dashboard.
11. Strong date and payment tests.

### Account credit and advance payments

Current behavior:

- Early payments should be accepted.
- Overpayments should become account credit.
- Payments are allocated oldest-first when recorded.
- Any overpayment remains as unallocated payment credit.
- Future invoices consume available unallocated credit automatically when the invoice is created or reused.
- Billing snapshots show a credit/payment line when those payments reduce the amount due.
- Credit adjustments reduce available account credit without rewriting the original payment record.
- Disconnected accounts can preserve credit, reserve it as refund due, or forfeit it based on Subscriber Settings.
- Pending refund credit can be manually completed later, with an optional matching accounting expense record.

Example:

| Payment | Open invoice | Result |
| --- | --- | --- |
| PHP 1,500 | PHP 1,000 | PHP 1,000 applied to invoice, PHP 500 stored as account credit. |

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `enable_account_credit` | `true` | Formalizes unallocated payment handling. |
| `auto_apply_credit_to_new_invoices` | `true` | Applies credit to future invoices automatically. |
| `credit_apply_order` | `oldest_unpaid_first` | Other modes can be added later if needed. |
| `disconnected_credit_policy` | `preserve_credit` | Implemented. Controls remaining credit when a subscriber is marked disconnected. |

### Billing ledger

Target behavior:

- Each subscriber should have a readable billing ledger.
- Ledger entries should show invoices, payments, credits, adjustments, waivers, voids, and remaining balance.

Example ledger:

| Entry | Amount effect |
| --- | --- |
| Invoice | +PHP 1,000 |
| Payment | -PHP 500 |
| Adjustment | +PHP 100 |
| Credit applied | -PHP 200 |

Recommended settings:

- No user-facing setting is required for the ledger itself.
- Ledger creation should be a fixed system behavior for auditability.

### Adjustments

Target behavior:

- Admin can add controlled adjustments without rewriting invoice history.
- Supported adjustment types should include discount, penalty, correction, one-time charge, installation fee, waiver, refund, and credit memo.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `enable_billing_adjustments` | `true` | Allows controlled corrections and one-time charges. |
| `require_adjustment_reason` | `true` | Keeps audit trail clean. |
| `require_adjustment_approval` | `false` initially | Can be enabled later for stricter finance workflow. |

### Invoice lifecycle

Target behavior:

- Invoice state should be explicit and easy to audit.
- Current statuses can be refined into a clearer lifecycle.

Recommended lifecycle:

| Status | Meaning |
| --- | --- |
| `draft` | Prepared but not issued. |
| `issued` | Officially billed to subscriber. |
| `partial` | Partially paid and not overdue by due/grace rules. |
| `paid` | Fully settled. |
| `overdue` | Has remaining balance and is past due/grace rules. |
| `voided` | Cancelled for a valid audit reason. |
| `waived` | Balance intentionally forgiven. |

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `invoice_issue_mode` | `auto` | Options could be `auto`, `draft_review`, or `manual`. |
| `allow_invoice_voiding` | `true` | Should require reason. |
| `allow_invoice_waiving` | `true` | Should require reason. |

### Payment allocation

Target behavior:

- Payments should allocate clearly and predictably.
- Default should remain oldest unpaid invoice first.
- Admin may later be allowed to choose a specific invoice during payment entry.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `payment_allocation_mode` | `oldest_unpaid_first` | Safest default for collections. |
| `allow_manual_payment_allocation` | `false` initially | Can be enabled when UI is ready. |
| `prevent_duplicate_payment_reference` | `false` initially | Useful if payment channels provide reliable reference numbers. |

### Billing SMS reminder engine

Target behavior:

- SMS reminders should be due-date based.
- Reminders should stop when fully paid.
- Partial balances should continue reminders using remaining balance.
- Duplicate sends are blocked per billing snapshot and reminder date.
- Due-date reminders are included even if the repeat interval does not land exactly on the due date.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `enable_billing_sms` | existing setting | Master switch. |
| `billing_sms_days_before_due` | existing setting, currently `3` | First reminder lead time. |
| `billing_sms_repeat_interval_days` | `2` | Repeat interval while unpaid. |
| due-date reminder | fixed enabled | Sends due-day reminder if unpaid. |
| `billing_sms_send_after_due` | `false` initially | Can be enabled for collections workflow. |
| `billing_sms_after_due_interval_days` | `2` if enabled | Repeat interval after due date. |
| `billing_sms_stop_when_paid` | `true` | Should usually remain fixed true. |

Template recommendations:

- Current bill template.
- Partial balance reminder template.
- Overdue reminder template.
- Payment received template, later if needed.

### Grace period and suspension rules

Target behavior:

- Marking overdue and suspending service should be separate decisions.
- Palugit should continue to skip auto-suspension.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `grace_period_days` | existing setting | Days after due date before marking overdue. |
| `enable_auto_disconnect` | existing setting | Master switch for auto-suspend. |
| `auto_suspend_after_overdue_days` | `0` initially | Allows delaying suspension after invoice becomes overdue. |
| `skip_auto_suspend_with_active_palugit` | `true` | Should remain true. |

Example:

| Due date | Grace period | Mark overdue | Auto-suspend delay | Auto-suspend |
| --- | --- | --- | --- | --- |
| May 28, 2026 | 3 days | Jun 1, 2026 | 2 days | Jun 3, 2026 |

### Auto-reconnect after payment

Target behavior:

- If a subscriber was suspended because of overdue billing, full payment can optionally trigger reconnect.
- Reconnect should be logged and should respect router/MikroTik settings.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `auto_reconnect_after_full_payment` | `false` initially | Implemented. Safer to launch with manual review unless operations wants full automation. |
| `auto_reconnect_requires_no_open_balance` | `true` | Implemented as fixed behavior. Reconnect only runs when all open, partial, and overdue balances are fully paid. |
| `notify_admin_on_auto_reconnect` | `true` | Future enhancement for a dedicated admin notification beyond existing audit/UI messages. |

### Billing preview

Target behavior:

- Admin can preview billing before issuing invoices or snapshots.
- Preview should show period, due date, current charge, previous balance, credit, adjustments, total due, and SMS schedule.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `require_billing_preview_before_bulk_issue` | `false` initially | Can be enabled for stricter finance control. |
| `show_sms_schedule_in_preview` | `true` | Helps catch wrong reminder timing before issue. |

### Billing health dashboard

Target behavior:

- Finance/admin should see billing risk and workload at a glance.

Recommended dashboard indicators:

- bills due today
- bills due in the next reminder window
- overdue count
- partial count
- total receivables
- total account credits
- SMS pending, sent, and failed
- subscribers without rate
- subscribers without phone
- subscribers with invalid billing setup

Recommended settings:

- No core setting required.
- Dashboard thresholds can be added later if alerts become noisy.

### Tests and safeguards

Target tests:

- cutoff `28`, `29`, `30`, and `31`
- February non-leap and leap years
- April 30 and May 31
- December-January rollover
- prepaid due date
- postpaid due date
- early payment
- overpayment/account credit
- overdue partial payment
- SMS first reminder, repeat reminder, due-day reminder, and duplicate prevention

Recommended settings:

- No user-facing setting required.
- These should be automated test safeguards.

### Settings strategy

Not every improvement should become a setting. Some rules should be fixed system behavior to keep billing reliable.

Recommended configurable settings:

- default cutoff day
- default billing type
- due offset behavior, if retained
- invoice issue mode
- SMS reminder lead days
- SMS repeat interval
- due-day SMS toggle
- after-due SMS toggle
- grace period days
- auto-suspend toggle and delay
- auto-reconnect toggle
- adjustment approval requirement

Recommended fixed system behavior:

- month-end fallback for cutoff `29-31`
- invoice duplicate protection
- SMS duplicate protection
- stop SMS when fully paid
- preserve billing ledger
- require audit reason for voids, waivers, and adjustments
- apply payments against real invoice balances only

## Planned Billing Calendar & Queue

This feature should become the billing module's daily operations workspace. It answers the question: "What billing work is coming today, tomorrow, this week, or on a selected date?"

Recommended feature name:

- `Billing Calendar & Queue`

Related terms:

- `Billing Calendar` for calendar/date-based navigation.
- `Upcoming Billing Queue` for actionable work lists.
- `Cutoff Schedule` for subscribers whose effective cutoff falls on a date.
- `Due Schedule` for invoices due on a date.
- `A/R Aging` for overdue receivables grouped by age.

### Feature plan

The workspace should have four core views.

| View | Purpose |
| --- | --- |
| Calendar view | Monthly calendar with badges for cutoffs, due bills, SMS reminders, overdue transitions, and auto-suspend candidates. |
| Daily queue | Work list for a selected date, such as May 1. |
| Upcoming queue | Range-based list for today, tomorrow, next 7 days, next 30 days, this month, or custom range. |
| Work tabs | Focused tabs for generate, review, send SMS, collect, and exceptions. |

Daily queue sections:

- cutoff today
- due today
- SMS scheduled today
- bills to generate
- bills needing review
- subscribers already paid or credit-covered
- missing setup
- overdue soon
- auto-suspend risk

Useful filters:

- today
- tomorrow
- next 7 days
- next 30 days
- this month
- custom date range
- by effective cutoff date
- by due date
- by SMS send date
- by billing type: `prepaid` or `postpaid`
- by invoice status: not generated, generated, partial, paid, overdue
- by snapshot status: missing, draft, frozen
- by SMS status: eligible, sent, failed, skipped

Smart status groups:

- ready to generate
- already generated
- needs review
- SMS eligible
- paid already
- partially paid
- missing rate
- missing phone
- SMS opted out
- has account credit
- overdue soon
- auto-suspend risk
- palugit active
- billing effective date not reached
- duplicate invoice risk

Recommended actions:

- generate selected invoices
- generate selected snapshots
- preview billing
- send selected SMS
- mark reviewed
- record payment
- open subscriber account
- export queue CSV

Recommended columns:

| Column | Purpose |
| --- | --- |
| Subscriber | Customer identity and account link. |
| Billing type | Shows `prepaid` or `postpaid`. |
| Cutoff day | Configured cutoff. |
| Effective cutoff date | Month-aware cutoff date after fallback. |
| Period | Service period covered by the bill. |
| Due date | Payment due date based on billing type. |
| Plan/rate | Billing amount source. |
| Previous balance | Open balance before current cycle. |
| Credit | Available account credit. |
| Total due | Amount still payable. |
| Invoice status | Missing, issued, partial, paid, overdue, voided, waived. |
| Snapshot status | Missing, draft, frozen. |
| SMS status | Eligible, sent, failed, skipped, not due. |
| Phone | SMS destination readiness. |
| Flags | Missing setup, palugit, credit-covered, duplicate risk, etc. |

SMS awareness:

- first SMS date
- next SMS date
- last SMS sent
- reminder stage
- SMS failed reason
- whether SMS will send today
- why SMS will not send, such as paid, no phone, opted out, not generated, or outside reminder window

Billing run summary for a selected date:

| Metric | Example |
| --- | --- |
| Total subscribers in queue | 30 |
| Ready to bill | 25 |
| Already generated | 10 |
| Missing rate | 2 |
| Missing phone | 3 |
| SMS due today | 18 |
| Paid or credit-covered | 4 |
| Expected receivable | PHP 32,500 |

Prepaid and postpaid handling:

- A selected date can include prepaid subscribers whose next cycle starts on that date.
- The same selected date can include postpaid subscribers whose current cycle ends on that date.
- The same date can also include SMS reminders for bills due soon, even if their cutoff is not today.

Exception queue:

- no rate
- no phone
- invalid cutoff
- no billing type
- billing effective date not reached
- duplicate invoice risk
- snapshot missing
- SMS failed
- account credit larger than amount due
- palugit active

### Implementation plan

Phase 1: Billing preview engine

- Build a read-only billing preview service.
- It should compute effective cutoff date, period, due date, billing type, expected invoice amount, previous balance, credit, total due, and SMS eligibility.
- It should not create invoices, snapshots, payments, or SMS logs.
- This preview should be the shared source for the calendar, queue, and future bulk actions.

Current implementation status:

- `get_billing_preview_for_subscriber()` provides a read-only subscriber billing preview.
- `get_billing_previews()` provides batch preview support for a subscriber queryset.
- Preview includes period, cutoff date, generation date, due date, billing type, rate, current charge, previous balance, account credit, credit applied, total due, invoice status, snapshot status, flags, and current SMS eligibility.
- The preview engine does not create invoices, snapshots, payments, allocations, or SMS logs.

Phase 2: Read-only daily queue

Current implementation status:

- `/billing/queue/` exposes the preview engine as a read-only Daily Billing Queue.
- The queue supports selected date, event type, billing type, and subscriber/phone search filters.
- Event filters are:
  - day events
  - generation
  - due
  - SMS
  - attention
  - all subscribers
- The queue summarizes day events, generation count, due count, SMS reminder count, attention count, and expected day total.
- It shows `generation_date` separately from `cutoff_date`, which is important for prepaid subscribers whose bill is generated before the next prepaid cycle starts.
- The queue can now run selected generation actions for generation-ready rows only.
- Supported selected actions:
  - generate selected invoices
  - generate selected statements
- Statement generation uses `generate_snapshot_for_subscriber()`, which also ensures the invoice exists.
- The server re-checks selected subscribers before generating, so non-generation rows, invalid billing profiles, and non-billable accounts are skipped or reported.
- The queue still does not create payments, allocations, or SMS logs.

Phase 3: Read-only calendar

Current implementation status:

- `/billing/calendar/` exposes the preview engine as a read-only monthly Billing Calendar.
- The calendar supports month navigation and billing type filtering.
- Each day shows counts for generation, due, SMS reminder, attention, day event total, and expected amount due.
- Clicking a day opens `/billing/queue/?date=YYYY-MM-DD` for the detailed subscriber list.
- The calendar does not create invoices, snapshots, payments, allocations, or SMS logs.

Remaining calendar enhancements:

- Add overdue transition and auto-suspend candidate counts.
- Add optional range summaries such as next 7 days or next 30 days.
- Add export once the queue export format is defined.

Phase 4: Daily queue enhancements

- Group subscribers by ready to generate, already generated, SMS eligible, paid, partial, missing setup, exceptions, and auto-suspend risk.
- Add optional upcoming range mode such as next 7 days.
- Add export for the selected queue day.

Phase 5: Safe generation actions

Current implementation status:

- Selected invoice generation is available from `/billing/queue/`.
- Selected statement generation is available from `/billing/queue/`.
- Duplicate invoice protection remains in `generate_invoice_for_subscriber()` through the subscriber and `period_start` check.
- Duplicate statement protection remains in `generate_snapshot_for_subscriber()` through the subscriber and `period_start` check.
- Every bulk action shows created, skipped, and error counts.
- The action is intentionally limited to generation-ready rows. SMS and due-only rows are visible but not selectable for generation.

Remaining generation enhancements:

- Add select-all by visible page or current filtered result.
- Add CSV export for the bulk result.
- Add optional confirmation page for large batches.

Phase 6: SMS eligibility and sending

Current implementation status:

- Billing preview now uses the SMS schedule engine.
- Queue rows show SMS eligibility, next SMS date, and reminder stage.
- Scheduled SMS sends from `send_bulk_billing_sms()` now support:
  - first reminder based on `billing_sms_days_before_due`
  - repeat reminders based on `billing_sms_repeat_interval_days`
  - due-date reminder
  - optional after-due reminders based on `billing_sms_send_after_due`
  - skip when already attempted today
  - skip when already sent today
  - skip when paid or credit-covered
  - skip when opted out, missing phone, or missing frozen statement
- Queue-selected SMS sending is available for SMS-ready rows.
- Queue-selected failed SMS retry is available for failed attempts that were not successfully sent.
- Queue rows link to filtered SMS history for their billing statement.
- `SMSLog` now stores billing snapshot, reminder stage, reminder run date, and billing due date for billing SMS tracking.
- The billing SMS link now uses Django `APP_BASE_URL` correctly instead of the SMS settings object.

Remaining SMS enhancements:

- Add provider API response IDs if the SMS gateway exposes them.
- Add a dedicated collections template if after-due reminders need different copy.

Phase 7: Review, export, and collections tools

- Add mark-reviewed state if draft review is enabled.
- Add CSV export for the selected date or range.
- Add quick links to record payment and subscriber detail.
- Add collection-focused filters for partial, overdue, and auto-suspend risk.

Phase 8: Dashboard integration

- Feed high-level queue metrics into the billing health dashboard.
- Highlight today's billing workload, failed SMS, missing setup, and expected receivables.

Recommended settings:

| Setting | Recommended default | Notes |
| --- | --- | --- |
| `enable_billing_calendar` | `true` | Feature visibility switch if needed. |
| `billing_queue_default_range_days` | `7` | Default upcoming queue range. |
| `billing_queue_show_sms_dates` | `true` | Shows reminder schedule in the queue. |
| `billing_queue_show_credit_covered` | `true` | Helps finance separate paid/credit-covered accounts. |
| `billing_queue_allow_bulk_generate` | `true` | Enables selected invoice/snapshot generation. |
| `billing_queue_allow_bulk_sms` | `true` | Safe now that duplicate SMS tracking is implemented. |
| `billing_queue_require_preview_before_bulk_actions` | `true` | Helps prevent accidental billing blasts. |

Recommended fixed system behavior:

- Calendar and queue must use the same billing preview engine.
- Queue calculations must use effective cutoff dates, not raw day equality.
- Bulk actions must be idempotent.
- Fully paid invoices must not receive billing reminders.
- Exceptions should be visible before bulk actions run.

## Invoice Generation Workflow

Manual bulk generation:

- Entry point: `/billing/invoices/generate/`.
- Calls `generate_invoices_for_all()`.
- Includes subscribers where `status` is `active` or `suspended` and `is_billable=True`.
- Calls `generate_invoice_for_subscriber()` for each subscriber.
- Skips if an invoice already exists for the same `period_start`.

Manual single-subscriber generation:

- Same calculation as bulk generation.
- Uses the selected subscriber only.

Scheduled generation:

- Scheduler job: `job_generate_invoices()`.
- Runs daily at `00:10` when `enable_auto_generate=True`.
- Generates invoices for all active/suspended billable subscribers.
- This job does not filter by today's cutoff day; duplicate protection is the invoice `period_start` check.

## Billing Snapshot Workflow

Scheduled snapshot generation:

- Scheduler job: `job_generate_snapshots()`.
- Runs daily at `00:15`.
- Skips entirely when `billing_snapshot_mode='manual'`.
- Uses `generate_due_billing_snapshots()`.
- Prepares snapshots when the selected cycle reaches its preparation date.
- Preparation date is normally the generation/cutoff date.
- If billing SMS is enabled and the first reminder is earlier than the generation/cutoff date, preparation date becomes the first SMS reminder date.
- This closes the postpaid lead-window gap: a bill due May 28 with SMS 3 days before due can be generated and frozen on May 25.
- Counts only newly created snapshots.

Snapshot creation:

- Uses the same billing profile as invoice generation.
- Skips safely when a snapshot already exists for the same subscriber and `period_start`.
- Ensures the current-cycle invoice exists by calling `generate_invoice_for_subscriber()`.
- Applies existing unallocated payments to the current invoice when the invoice is created or reused.
- Recomputes the billing preview after invoice/credit allocation.
- Uses preview totals for current charge, previous balance, credit/payment applied, and total due.
- Adds previous open, partial, and overdue invoice balances except the current-cycle invoice.
- Adds a credit line item when payments or account credit reduce the amount due.
- Creates a `BillingSnapshot` and line items.
- If snapshot mode is `auto`, status becomes `frozen` and `frozen_at` is set.
- If snapshot mode is `draft`, status remains `draft`.

Draft auto-freeze:

- Scheduler job: `job_auto_freeze_drafts()`.
- Runs hourly.
- Only active when `billing_snapshot_mode='draft'`.
- Freezes drafts older than `draft_auto_freeze_hours`.

Manual snapshot generation:

- Entry point is subscriber detail action.
- Calls `generate_snapshot_for_subscriber()` directly.
- It uses the same profile calculation as the scheduler.
- If a snapshot already exists for the same subscriber and period, the manual path redirects to the existing snapshot instead of creating a duplicate.

Duplicate protection:

- `Invoice` has a database unique constraint on subscriber and `period_start`.
- `BillingSnapshot` has a database unique constraint on subscriber and `period_start`.
- These constraints backstop the application-level duplicate checks and protect against race conditions.

## Billing SMS Reminder Workflow

Scheduled billing SMS:

- Scheduler job: `job_send_billing_sms()`.
- Runs daily at the configured `billing_sms_schedule`.
- Skips entirely when `enable_billing_sms=False`.
- Uses frozen billing snapshots whose due date is inside the configured lead window.
- Calls `send_bulk_billing_sms()`.

Reminder schedule:

- First reminder date is `due_date - billing_sms_days_before_due`.
- Repeat reminders use `billing_sms_repeat_interval_days`.
- The due date is always included as a reminder date while unpaid.
- If `billing_sms_send_after_due=True`, reminders continue after the due date using `billing_sms_after_due_interval_days`.

Duplicate protection:

- Billing SMS logs are linked to `billing_snapshot`.
- `SMSLog.reminder_run_date` records the scheduled reminder date.
- `SMSLog.reminder_stage` records which reminder in the schedule was attempted.
- The scheduler skips a snapshot if it already has any billing SMS attempt for today's reminder date.

Skip rules:

- SMS disabled.
- Paid or credit-covered.
- Subscriber opted out.
- Missing phone number.
- Frozen statement missing.
- Before the SMS window.
- After due date when after-due reminders are disabled.
- Already sent or attempted today.
- Not a scheduled reminder day.

## Legacy Due Day Mode

The current code does not have a separate legacy workflow.

The label `Legacy Due Day` appears to represent the older mental model where `billing_day`/`due_days` drove bill timing. However:

- `billing_day` is now labeled and used as the default cutoff day.
- `due_days` is now a fallback due offset after cutoff.
- `billing_mode='legacy'` is not checked by `resolve_billing_profile()`, invoice generation, snapshot generation, usage cutoff snapshots, overdue marking, SMS sending, or scheduler filters.

Operationally, selecting `Legacy Due Day` today does not change period start, period end, cutoff date, due date, invoice generation, or snapshot generation.

## Usage Cutoff Snapshot Workflow

Usage cutoff snapshots also follow the cutoff-day resolver:

- `create_cutoff_usage_snapshots()` runs from the usage sampling job.
- It exits when `UsageSettings.cutoff_snapshot_enabled=False`.
- It filters active/suspended billable subscribers whose resolved cutoff day matches today.
- It creates one `SubscriberUsageCutoffSnapshot` per subscriber and cutoff date.
- The period comes from `get_next_cutoff_period()` using `today - 1 day` as reference, so the usage snapshot covers the cycle that just ended at today's cutoff.

## Overdue and Auto-Suspend Workflow

Overdue marking:

- Scheduler job: `job_mark_overdue()`.
- Runs daily at `00:05`.
- Calls `mark_overdue_invoices()`.
- Marks `open` and `partial` invoices as `overdue` when `due_date < today - grace_period_days`.

Auto-suspend:

- Scheduler job: `job_auto_suspend_overdue()`.
- Runs every 15 minutes.
- Exits when `enable_auto_disconnect=False`.
- Selects active subscribers with overdue invoices.
- Skips subscribers with an active `suspension_hold_until`.
- Calls `suspend_subscriber()` for the rest.

## Subscriber Billing Readiness and Onboarding Guardrails

Current subscriber module strengths:

- Subscriber records already carry billing fields: `billing_type`, `cutoff_day`, `billing_due_days`, `is_billable`, `start_date`, `billing_effective_from`, and `sms_opt_out`.
- Subscriber lifecycle actions already exist for suspend, reconnect, disconnect, deceased, and archive.
- Palugit / suspension hold is tracked per subscriber and respected by auto-suspend.

Production gaps identified:

- New subscribers synced from MikroTik can be incomplete because router data may not include plan, rate, phone, start date, or billing policy.
- Direct status editing can bypass lifecycle actions if not controlled carefully.
- MikroTik suspend/reconnect currently targets PPP secrets and should become service-type-aware for hotspot, DHCP/IPoE, and static accounts.
- Subscriber pages need a visible billing/SMS readiness indicator.
- Auto-reconnect after full payment is not fully implemented yet.
- Disconnected account billing policy now supports preserve balance, final invoice, or waive open balances.
- Disconnected account credit policy now supports preserve credit, mark refund due, or forfeit credit.
- Phone/OTP flow now normalizes portal phone lookup and blocks duplicate-phone OTP login.
- Subscriber profile edits now write field-level before/after audit logs.
- Subscriber-sensitive actions now use Django permissions instead of only `login_required`.

Implemented guardrail slice:

- New subscribers created by MikroTik sync are imported as `inactive` and `is_billable=False`.
- Admin must complete onboarding before the account enters automatic billing.
- Billing readiness checks:
  - account is billable,
  - status is active or suspended,
  - plan or monthly rate exists,
  - service start date or billing effective date exists,
  - billing type is postpaid or prepaid,
  - resolved cutoff day is valid from subscriber override or billing settings.
- SMS readiness is separate from billing readiness:
  - billing can be ready even if phone is missing,
  - SMS is not ready when phone is missing/incomplete or the subscriber opted out.
- Billing preview, queue, invoice generation, and snapshot generation now surface or block incomplete billing setup with clear reasons.
- Subscriber list and subscriber detail show the readiness badge so onboarding issues are visible before the scheduler reaches the account.

Implemented status transition slice:

- Generic subscriber status changes now route through a formal transition service.
- The edit form can request only serviceable statuses: active, inactive, or suspended.
- Profile edits save subscriber information first, then status changes are applied through lifecycle services.
- Active transitions call the reconnect/activate path and clear active palugit.
- Suspended transitions call the suspend path and clear active palugit.
- Inactive transitions call the deactivate path, disable service where MikroTik auto-suspend is configured, and clear active palugit.
- Disconnected, deceased, and archived are terminal workflow states and cannot be changed through the generic edit form.
- Terminal workflow changes must use their dedicated actions: disconnect, deceased, and archive.
- Suspend/reconnect buttons now use the same formal transition service as edit-driven status changes.
- Audit logs record old status to new status transitions.
- If the database status changes but MikroTik returns a warning, the UI reports the warning instead of hiding it.

Implemented service-type-aware MikroTik access slice:

- Auto-suspend/reconnect no longer assumes every subscriber is PPPoE.
- PPPoE subscribers update `/ppp/secret` by `name=username`.
- Hotspot subscribers update `/ip/hotspot/user` by `name=username`.
- DHCP/IPoE subscribers update `/ip/dhcp-server/lease` using the best available lookup:
  - `mac-address`,
  - then `address`,
  - then `comment=username`,
  - then `host-name=username`.
- Static subscribers now return an explicit warning instead of silently trying to disable a PPP secret.
- Static service suspension needs a defined router policy first, such as a firewall address-list and matching drop/redirect rule.
- The subscriber status still changes in the app when MikroTik returns a warning; the UI surfaces that warning to the operator.

Implemented auto-reconnect after full payment slice:

- Subscriber Settings now has `Auto-reconnect after full payment`.
- The setting defaults to off, so existing deployments keep manual reconnect behavior unless an admin enables it.
- After a payment is recorded and allocated, the system checks the subscriber after the payment transaction commits.
- Auto-reconnect only runs when:
  - the setting is enabled,
  - the subscriber is currently suspended,
  - all open, partial, and overdue invoice balances are fully paid.
- Partial payments do not reconnect the subscriber.
- Overpayments still become account credit after invoices are paid.
- The reconnect uses the same formal status transition service as manual reconnect.
- MikroTik reconnect behavior still respects the separate `Auto-reconnect on MikroTik` setting.
- If the app status changes but MikroTik returns a warning, the payment UI reports the warning.

Implemented disconnected final-billing policy slice:

- Subscriber Settings now has `Disconnected billing policy`.
- Default policy is `Preserve existing balance`, so existing deployments keep current behavior unless changed.
- Supported policies:
  - `Preserve existing balance`: disconnects service and keeps invoices/balances unchanged.
  - `Generate final invoice`: generates the current-cycle invoice before the subscriber status becomes disconnected.
  - `Waive open balances`: marks open, partial, and overdue invoices as `waived`.
- Paid, voided, and already-waived invoices are not changed by the waiver policy.
- The disconnect confirmation screen shows the active billing policy before the operator confirms.
- The disconnect workflow still disables service access through the MikroTik service-type-aware path when configured.
- Billing policy warnings are surfaced back to the operator after disconnect.

Implemented disconnected account-credit policy slice:

- Subscriber Settings now has `Disconnected credit policy`.
- Default policy is `Preserve account credit`, so existing deployments keep current account-credit behavior unless changed.
- Supported policies:
  - `Preserve account credit`: keeps remaining unallocated credit available on the subscriber account.
  - `Mark refund due`: creates a pending credit adjustment for the remaining available credit, reserving it so future invoices cannot consume it.
  - `Forfeit account credit`: creates a completed credit adjustment that removes the remaining credit from the available account balance.
- Credit adjustments do not rewrite payment history.
- Available account credit is now calculated as unallocated payments minus pending/completed credit adjustments.
- Future invoice auto-credit application respects credit adjustments and will not apply credit that was reserved for refund or forfeited.
- The disconnect confirmation screen shows available credit and the active credit policy before the operator confirms.
- Subscriber detail now shows unallocated credit, reserved/adjusted credit, available credit, and recent credit adjustments in the Payments tab.

Implemented manual refund completion slice:

- Pending `Refund Due` credit adjustments can be completed from the subscriber Payments tab.
- Only pending refund-due adjustments are eligible for this action.
- Completing the refund changes the adjustment to `Refund Paid` and `Completed`.
- Operators can enter a payout reference, paid-at timestamp, and notes.
- The original payment record remains unchanged.
- The completed adjustment remains part of the credit adjustment ledger, so available account credit stays reduced.
- The workflow can optionally create a matching `ExpenseRecord` under Accounting > Expenses.
- The generated expense uses category `Other`, description `Subscriber refund - <username>`, the refund amount, payout reference, subscriber display name as vendor, and the operator as recorder.
- Refund completion is audit logged.

Implemented phone normalization and duplicate-phone OTP slice:

- Subscriber records now store `normalized_phone` for phone-number lookup while preserving the original display phone.
- Phone normalization strips non-digits and canonicalizes Philippine mobile numbers:
  - `09171234567` becomes `639171234567`.
  - `9171234567` becomes `639171234567`.
  - `+63 917 123 4567` becomes `639171234567`.
- Existing subscriber and OTP rows are backfilled through migration.
- Portal OTP request now searches by normalized phone instead of exact text match.
- Portal OTP login blocks duplicate non-deceased/non-archived matches for the same normalized phone and tells the user to contact support.
- OTP verification now uses the subscriber selected during the OTP request session instead of re-resolving by raw phone text.
- Subscriber billing/SMS readiness now flags shared phone numbers as an SMS readiness issue.
- Subscriber search also checks normalized phone values.

Implemented subscriber audit and permissions slice:

- `Subscriber` now defines custom Django permissions:
  - `manage_subscriber_billing`
  - `manage_subscriber_lifecycle`
  - `import_subscribers`
- Subscriber profile edits require Django's standard `change_subscriber` permission.
- Billing-sensitive subscriber field changes require `manage_subscriber_billing`.
- Rate changes require `manage_subscriber_billing`.
- Lifecycle actions require `manage_subscriber_lifecycle`, including suspend, reconnect, palugit, disconnect, deceased, and archive.
- Router sync and subscriber CSV import require `import_subscribers`.
- Manual subscriber creation requires Django's standard `add_subscriber` permission.
- Plan creation/editing uses Django's standard `add_plan` and `change_plan` permissions.
- Basic node assignment now requires `change_subscriber`.
- Pending refund completion requires `billing.change_accountcreditadjustment`; creating the optional accounting expense also requires `accounting.add_expenserecord`.
- Subscriber edit now logs field-level before/after changes into the existing `AuditLog` table.
- Subscriber action buttons are hidden when the current user lacks the matching permission.

Implemented permission group presets slice:

- The system now creates and syncs common Django auth groups after migrations:
  - `ISP Admin`
  - `ISP Cashier`
  - `ISP Support`
  - `ISP Installer`
  - `ISP Read-only Auditor`
- `ISP Admin` receives all permissions.
- `ISP Cashier` receives billing collection permissions such as invoice/statement generation, payment recording, refund completion, accounting refund expense creation, and billing read access.
- `ISP Support` receives subscriber support permissions such as subscriber edit, lifecycle actions, SMS sending, and read access to billing/router/NMS context.
- `ISP Installer` receives subscriber onboarding/import and network assignment permissions without billing collection authority.
- `ISP Read-only Auditor` receives only `view_*` permissions for local ISP Manager apps.
- Preset syncing is additive by default, so custom permissions added by an admin are not removed during normal migrations.
- A manual command is available:
  - `python manage.py sync_role_groups`
  - `python manage.py sync_role_groups --replace`
- `--replace` resets preset groups to the current code-defined permission set.
- Billing action buttons are hidden when the current user lacks the required permission.
- Billing queue bulk actions now check permissions for invoice generation, statement generation, and SMS sending.
- Payment recording requires `billing.add_payment`.
- Manual SMS sending requires `sms.add_smslog`.

Recommended next subscriber slices:

- Optional static-subscriber firewall/address-list policy for suspend/reconnect.
- User/group management UI for assigning these roles without using Django Admin.

## Implementation Gap and Future Work

If the product needs a true distinction between `Legacy Due Day` and `Cutoff Advance Billing`, implement and test an explicit branch in the billing profile resolver.

Suggested implementation checklist:

- Define exact legacy semantics for period start, period end, cutoff date, and due date.
- Branch in `resolve_billing_profile()` based on `billing_settings.billing_mode`.
- Decide whether schedulers should filter by cutoff day, due day, or both in legacy mode.
- Decide whether `billing_due_offset_days` should replace or coexist with `due_days`.
- Add tests for both modes around month boundaries and subscriber overrides.
- Update settings copy so admins know whether they are choosing a real calculation mode or a compatibility label.
