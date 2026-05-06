# Overdue Grace Implementation Notes

Implementation notes for the overdue-with-palugit feature.

## Purpose

This document records what was actually changed in the codebase for the first implementation of subscriber palugit handling.

It is the implementation companion to:

- [Overdue and Palugit Current Workflow](./24_overdue_grace_current_workflow.md)
- [Overdue Palugit Implementation Plan](./25_overdue_grace_workflow_implementation_plan.md)

## Business Definition Used

For this implementation, `palugit` means:

- temporary extension of service access for an overdue subscriber
- temporary hold on automatic service enforcement
- no change to invoice `due_date`
- no change to invoice `period_start`
- no change to invoice `period_end`
- no rewrite of the billing ledger

In short:

- `overdue` remains the billing truth
- `palugit` becomes a service-enforcement hold
- `suspended` remains the actual service cut state

## What Was Added

### Subscriber model fields

Added subscriber-level hold fields:

- `suspension_hold_until`
- `suspension_hold_reason`
- `suspension_hold_by`
- `suspension_hold_created_at`

Also added a convenience property:

- `has_active_suspension_hold`

## New admin workflow

Added a dedicated palugit management flow from the subscriber page:

- `Grant Palugit`
- `Extend Palugit`
- `Remove Palugit`

This was intentionally implemented as a separate action instead of burying it inside the general subscriber edit page.

That keeps service enforcement decisions explicit and easier to audit.

## Scheduler change

Updated overdue auto-suspend behavior so that:

- subscribers with overdue invoices are still eligible for auto-suspend
- but subscribers with active `suspension_hold_until` are skipped

This means palugit now works even when global overdue auto-suspend is enabled.

## Subscriber lifecycle behavior

When a subscriber is:

- suspended
- disconnected
- marked deceased

the system now clears any active palugit hold fields automatically.

This prevents old holds from lingering after a terminal service action.

## UI changes

### Subscriber detail page

Added:

- overdue badge
- active palugit badge
- palugit management action buttons
- palugit state in the account summary sidebar

### Subscriber list page

Added:

- `Palugit` badge for subscribers with active hold

### Billing settings page

Renamed misleading label:

- from `Auto-disconnect after grace period`
- to `Auto-suspend overdue subscribers after grace period`

This matches the actual scheduler behavior.

## New page added

Added:

- `templates/subscribers/palugit_form.html`

This page allows staff to:

- set hold end datetime
- write optional reason/note
- remove an active hold

## Migration added

Added migration:

- `apps/subscribers/migrations/0003_subscriber_suspension_hold_by_and_more.py`

## Validation Performed

The following checks were completed:

- `manage.py makemigrations subscribers`
- `manage.py migrate subscribers`
- `manage.py check`
- `manage.py makemigrations --check --dry-run`

Functional smoke checks also confirmed:

- subscriber detail page loads
- palugit management page loads
- saving a palugit hold persists correctly
- test data was restored after validation

## Important Non-Changes

This implementation did **not** change:

- invoice generation rules
- billing snapshot generation rules
- invoice due-date calculation
- billing cycle period logic
- automatic reconnect after payment

Those remain separate concerns.

## Current Limitations

The first implementation intentionally keeps scope tight.

Still not included:

- collections dashboard logic
- promise-to-pay automation
- palugit expiry notification automation
- static subscriber suspension policy automation

## Recommended Next Follow-Up

The next logical hardening pass would be:

1. define the static-subscriber suspend policy, such as address-list plus firewall rule
2. optionally notify when palugit expires
3. expand collections dashboard workflows around palugit and overdue risk

## MikroTik suspend enforcement update

Suspend now performs a two-step MikroTik enforcement flow when auto-suspend is enabled:

- disable the account or lease first
- remove the current active session or lease only after disable succeeds

Service-specific behavior:

- PPPoE disables `/ppp/secret` by `name=username`, then removes `/ppp/active`
- Hotspot disables `/ip/hotspot/user` by `name=username`, then removes `/ip/hotspot/active`
- DHCP/IPoE disables `/ip/dhcp-server/lease` by MAC, IP, comment, or host-name, then removes the matched lease
- Static subscribers still return a policy warning because they need a configured firewall/address-list enforcement rule

If the account disable succeeds but active removal fails, the subscriber remains `suspended` in the app and the operator receives a MikroTik warning.
