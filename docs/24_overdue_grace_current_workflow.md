# Overdue and Palugit Current Workflow

Documentation of the current billing-to-service treatment flow for overdue subscribers.

## Purpose

This document explains how the system currently behaves when a subscriber becomes overdue, especially for this real-world scenario:

- the subscriber has overdue unpaid invoices
- the admin wants to give additional palugit
- the connection should stay active until the admin manually decides to suspend
- once suspended, MikroTik access should be disabled and any active session or lease should be removed where supported

## Current Design Summary

The current system already separates these concerns:

- `overdue` = billing state
- `suspended` = service state
- `disconnected` = account termination state

That separation is good and aligns with ISP operations.

The current system supports per-subscriber palugit through suspension-hold fields. An active hold keeps the subscriber eligible for billing follow-up while preventing automatic overdue suspension until the hold expires.

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
- disable MikroTik access
- remove active MikroTik sessions or leases

## 3. Actual service interruption happens only on suspend or disconnect

MikroTik access is disabled only when one of these actions happens:

- manual `Suspend`
- manual `Disconnect`
- scheduler-driven auto suspend for overdue subscribers

For service types that support enforcement, suspend first disables the account or lease, then removes active access:

- PPPoE: disable `/ppp/secret`, then remove matching `/ppp/active`
- Hotspot: disable `/ip/hotspot/user`, then remove matching `/ip/hotspot/active`
- DHCP/IPoE: disable the matched `/ip/dhcp-server/lease`, then remove that lease
- Static: return a warning because a firewall/address-list policy is still required

## 4. Manual suspend path

When admin clicks `Suspend` on the subscriber page:

- subscriber status becomes `suspended`
- the system attempts to disable the matching MikroTik account or lease
- if disabling succeeds, the system removes the matching active session or lease
- if no active session exists, the router-side removal is treated as already complete
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

Then subscribers with an active palugit hold are skipped by auto-suspend.

Meaning:

- once subscriber has an `overdue` invoice
- and remains `active`
- and has no active `suspension_hold_until`
- the scheduler may suspend the subscriber on the next run

The built-in hold fields are:

- `suspension_hold_until`
- `suspension_hold_reason`
- `suspension_hold_by`
- `suspension_hold_created_at`

## Current Gaps

### Gap 1: Misleading billing setting label

The UI says:

- `Auto-disconnect after grace period`

But the code actually:

- auto-suspends the subscriber
- does not mark them `disconnected`

### Gap 2: Suspended app status can exist even if MikroTik action failed

The suspend service still updates subscriber status to `suspended` when:

- MikroTik auto suspend is disabled
- no router is assigned
- the initial RouterOS disable action fails
- active session or lease removal fails after the account was disabled

If the status changes but MikroTik returns a warning, the UI surfaces that warning to the operator. This protects the workflow from silently hiding router-side enforcement problems.

### Gap 3: Static subscriber suspension still needs a router policy

Static subscribers do not have a safe generic RouterOS object to disable or remove.

To enforce static subscriber suspension, operations still needs a configured router policy such as:

- address-list membership
- firewall drop or redirect rule
- captive or walled-garden rule

## Payment reconnect behavior

If auto-reconnect after full payment is enabled, a suspended subscriber can be reconnected after all open, partial, and overdue balances are fully paid. Otherwise, staff still use manual `Reconnect`.

## Current Operational Recommendation

If the business wants:

- overdue allowed
- no automatic line cut
- admin decides manually when to suspend

Then for now the safest current setup is:

1. keep overdue marking active
2. use palugit holds for subscriber-specific extensions
3. either turn off global `enable_auto_disconnect` or let it run for accounts without active holds
4. let staff use manual `Suspend` from the subscriber page when collections decides to cut service

That gives the closest working behavior to the desired process.

## Conclusion

The current system supports:

- `overdue but not yet cut`
- per-subscriber palugit holds
- suspend-time MikroTik account disable plus active session or lease removal

The remaining production caveat is static subscriber enforcement, which still needs an explicit RouterOS policy before automatic suspension can reliably cut static access.
