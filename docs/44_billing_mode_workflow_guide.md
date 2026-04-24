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
| Subscriber overrides | `apps/subscribers/models.py` | Stores per-subscriber `cutoff_day`, `billing_due_days`, and `is_billable`. |

## Settings Fields

| Field | Meaning in current code |
| --- | --- |
| `billing_day` | Default cutoff day, limited to 1-28. Used when a subscriber has no custom `cutoff_day`. |
| `due_days` | Legacy/default due-day fallback. Used only when no subscriber due override exists and `billing_due_offset_days` is `0` or blank. |
| `billing_due_offset_days` | Preferred global due offset after cutoff when non-zero. |
| `billing_mode` | Stored/displayed mode, but not used by calculation logic today. |
| `billing_snapshot_mode` | Controls snapshot status: `auto` freezes immediately, `draft` creates draft, `manual` skips scheduler snapshot generation. |
| `draft_auto_freeze_hours` | Auto-freeze age for draft snapshots. |
| `enable_auto_generate` | Enables the daily invoice generation job. |
| `enable_auto_disconnect` | Enables auto-suspend for subscribers with overdue invoices. |
| `grace_period_days` | Extra days after due date before invoices are marked overdue. |

Due offset precedence:

1. Subscriber `billing_due_days`, when set. A subscriber value of `0` means due on the cutoff date.
2. Global `billing_due_offset_days`, when non-zero.
3. Global `due_days`, when non-zero.
4. `0`.

Important nuance: because the global fallback uses `billing_due_offset_days or due_days or 0`, setting global `billing_due_offset_days = 0` does not force same-day due if `due_days` is still greater than `0`. For global same-day due, set both fields to `0`. Subscriber-level `billing_due_days = 0` works because subscriber override is checked with `is not None`.

## Current Cutoff Advance Workflow

All current invoice and snapshot generation flows use `resolve_billing_profile()`.

1. Resolve cutoff day:
   - Use subscriber `cutoff_day` if set.
   - Otherwise use `BillingSettings.billing_day`.
2. Resolve target service period with `get_next_cutoff_period(cutoff_day, reference_date)`.
   - If `reference_date.day >= cutoff_day`, period starts the day after this month's cutoff and ends on next month's cutoff.
   - If `reference_date.day < cutoff_day`, period starts the day after the previous month's cutoff and ends on this month's cutoff.
3. Set `cutoff_date = period_start - 1 day`.
4. Resolve due offset using subscriber override, global due offset, then legacy/default due days.
5. Set `due_date = cutoff_date + due_offset_days`.
6. Use the rate effective on the reference date.
7. Create or reuse one invoice per subscriber and `period_start`.

Example for a subscriber with cutoff day `10`:

| Reference date | Target period | Cutoff date | Due date if offset is 7 |
| --- | --- | --- | --- |
| April 10, 2026 | April 11-May 10, 2026 | April 10, 2026 | April 17, 2026 |
| April 11, 2026 | April 11-May 10, 2026 | April 10, 2026 | April 17, 2026 |
| April 9, 2026 | March 11-April 10, 2026 | March 10, 2026 | March 17, 2026 |

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
- Filters subscribers whose resolved cutoff day matches today's day.
- Checks if a snapshot already exists for that subscriber and today's cutoff date before creating one.
- Calls `generate_snapshot_for_subscriber()`.

Snapshot creation:

- Uses the same billing profile as invoice generation.
- Ensures the current-cycle invoice exists by calling `generate_invoice_for_subscriber()`.
- Adds previous open, partial, and overdue invoice balances except the current-cycle invoice.
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
- The scheduler prevents duplicate same-day snapshots; the manual path should be used carefully because the model does not enforce a unique `(subscriber, cutoff_date)` snapshot constraint.

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

## Implementation Gap and Future Work

If the product needs a true distinction between `Legacy Due Day` and `Cutoff Advance Billing`, implement and test an explicit branch in the billing profile resolver.

Suggested implementation checklist:

- Define exact legacy semantics for period start, period end, cutoff date, and due date.
- Branch in `resolve_billing_profile()` based on `billing_settings.billing_mode`.
- Decide whether schedulers should filter by cutoff day, due day, or both in legacy mode.
- Decide whether `billing_due_offset_days` should replace or coexist with `due_days`.
- Add tests for both modes around month boundaries and subscriber overrides.
- Update settings copy so admins know whether they are choosing a real calculation mode or a compatibility label.

