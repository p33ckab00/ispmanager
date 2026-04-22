# Overdue and Palugit Current Workflow

Documentation of the current billing-to-service treatment flow for overdue subscribers.

## Purpose

This document explains how the system currently behaves when a subscriber becomes overdue, especially for this real-world scenario:

- the subscriber has overdue unpaid invoices
- the admin wants to give additional palugit
- the connection should stay active until the admin manually decides to suspend
- once suspended, the PPP secret on MikroTik should be disabled

## Current Design Summary

The current system already separates these concerns:

- `overdue` = billing state
- `suspended` = service state
- `disconnected` = account termination state

That separation is good and aligns with ISP operations.

However, the current system does **not** yet support a per-subscriber palugit or service-enforcement hold override.

## Final Business Definition

For this project, `palugit` should mean:

- an admin-approved extension of service access for an overdue subscriber
- without changing invoice period
- without changing invoice due date
- without rewriting billing history

Palugit is therefore a:

- service enforcement hold

It is **not**:

- a new billing cycle
- an invoice rewrite
- an extension of `period_start` or `period_end`

## Current Workflow

### 1. Invoice becomes overdue

An invoice is marked `overdue` when:

- invoice status is `open` or `partial`
- `due_date` is older than `today - grace_period_days`

This uses the global billing setting:

- `grace_period_days`

## 2. Overdue marking does not immediately cut service

Marking an invoice as `overdue` only changes billing state.

It does **not** by itself:

- suspend the subscriber
- disconnect the subscriber
- disable the MikroTik PPP secret

## 3. Actual service interruption happens only on suspend or disconnect

The MikroTik PPP secret is disabled only when one of these actions happens:

- manual `Suspend`
- manual `Disconnect`
- scheduler-driven auto suspend for overdue subscribers

## 4. Manual suspend path

When admin clicks `Suspend` on the subscriber page:

- subscriber status becomes `suspended`
- the system attempts to set MikroTik PPP secret `disabled=yes`
- an audit log entry is created
- a Telegram notification may be sent

This is the path that matches the intended “admin decides when to cut the line” workflow.

## 5. Auto-suspend path

There is a scheduled job that runs every `15 minutes`.

If global billing setting `enable_auto_disconnect` is enabled, the system finds:

- subscribers with `status='active'`
- and at least one `overdue` invoice

Then it calls the same suspend flow used by manual suspend.

Important note:

- despite the UI label saying `Auto-disconnect after grace period`
- the current code actually performs `auto-suspend`, not true disconnect

## 6. What happens if admin wants to give palugit today

### If `enable_auto_disconnect` is disabled

Then the current system can already behave like this:

- invoice becomes `overdue`
- subscriber remains `active`
- connection stays up
- admin manually clicks `Suspend` only when ready

This matches the desired behavior operationally.

### If `enable_auto_disconnect` is enabled

Then the current system does **not** support per-subscriber exemption.

Meaning:

- once subscriber has an `overdue` invoice
- and remains `active`
- the scheduler may suspend the subscriber on the next run

There is no built-in field or admin action for:

- `palugit until`
- `promise to pay`
- `skip auto suspend`
- `service enforcement hold`

## Current Gaps

### Gap 1: No per-subscriber palugit control

The system has:

- global grace period
- global auto suspend toggle

But it does not have:

- subscriber-specific grace extension
- subscriber-specific hold from auto suspend

### Gap 2: Misleading billing setting label

The UI says:

- `Auto-disconnect after grace period`

But the code actually:

- auto-suspends the subscriber
- does not mark them `disconnected`

### Gap 3: Suspended app status can exist even if MikroTik action failed

The suspend service updates subscriber status to `suspended` even when:

- MikroTik auto suspend is disabled
- no router is assigned
- RouterOS API call fails

So the UI state and actual router enforcement can drift.

### Gap 4: Payment does not auto-reconnect

If a subscriber is already suspended and then pays:

- payment allocation works
- accounting income is created
- overdue invoices may become paid

But the subscriber is not automatically reconnected.

Manual `Reconnect` is still required.

## Current Operational Recommendation

If the business wants:

- overdue allowed
- no automatic line cut
- admin decides manually when to suspend

Then for now the safest current setup is:

1. keep overdue marking active
2. turn off global `enable_auto_disconnect`
3. let staff use manual `Suspend` from the subscriber page

That gives the closest working behavior to the desired process.

## Conclusion

The current system can support:

- `overdue but not yet cut`

But only at a global operational level, not per subscriber.

The missing feature is:

- a per-subscriber overdue-with-palugit workflow implemented as a service-enforcement hold

That should be added before relying on automatic suspend in real production operations.
