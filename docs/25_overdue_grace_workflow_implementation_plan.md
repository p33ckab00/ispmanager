# Overdue With Palugit Workflow Implementation Plan

Discussion and implementation plan for adding a per-subscriber palugit workflow before changing code.

## Goal

Add a workflow where:

- a subscriber can become overdue
- the admin can still allow service temporarily
- the connection stays active during the approved palugit period
- auto-suspend does not override the admin decision
- the admin can still suspend manually at any time
- when suspended, the MikroTik PPP secret is disabled

## Business Rule

The intended business rule should be:

- `Overdue` means the account has unpaid collectible balance
- `Palugit` means the account may stay active temporarily even while overdue
- `Suspended` means service is intentionally cut
- `Disconnected` means account termination or closure

This keeps financial state and network enforcement separate.

## Final Business Definition

For this implementation, `palugit` means:

- temporary extension of service access
- temporary hold on service enforcement
- no change to invoice period
- no change to invoice due date
- no rewrite of billing ledger

Recommended internal naming should therefore reflect the real behavior:

- `suspension_hold_until`
- `suspension_hold_reason`
- `suspension_hold_by`

## Recommended Product Behavior

### Standard overdue flow

1. invoice becomes overdue
2. subscriber remains `active`
3. admin may:
   - do nothing yet
   - grant palugit
   - suspend now

### Palugit flow

1. subscriber is overdue
2. admin grants palugit until a specific date and time
3. subscriber remains `active`
4. scheduler does not auto-suspend while palugit is active
5. once palugit expires:
   - subscriber becomes eligible again for auto-suspend
   - unless admin extends palugit or manually suspends/reconnects

### Manual suspend flow

1. admin clicks `Suspend`
2. subscriber status becomes `suspended`
3. PPP secret is disabled on MikroTik
4. audit trail records who suspended and why

### Reconnect flow

1. admin clicks `Reconnect`
2. subscriber status becomes `active`
3. PPP secret is re-enabled on MikroTik

## Recommended Data Model Changes

Add subscriber-level fields such as:

- `suspension_hold_until`
- `suspension_hold_reason`
- `suspension_hold_by`
- `suspension_hold_created_at`

Optional additional field:

- `skip_auto_suspend`

Recommended interpretation:

- `suspension_hold_until` is the main operational field
- `skip_auto_suspend` is optional if you want an indefinite exemption mode

## Recommended Minimum Version

To keep the first implementation clean, start with:

- `suspension_hold_until`
- `suspension_hold_reason`
- `suspension_hold_by`

This already supports the main real-world workflow.

## Scheduler Logic Change

Current auto-suspend logic should change from:

- all active subscribers with overdue invoices

To:

- active subscribers with overdue invoices
- and no active palugit hold

Meaning:

- ignore subscriber if `suspension_hold_until` is still in the future

## UI/UX Changes

### Subscriber detail page

Add actions:

- `Grant Palugit`
- `Extend Palugit`
- `Remove Palugit`
- `Suspend Now`
- `Reconnect`

### Subscriber detail status area

Show:

- overdue state
- active palugit badge
- palugit expiry date/time
- palugit note/reason

Example display:

- `OVERDUE`
- `PALUGIT UNTIL Apr 25, 2026 5:00 PM`
- `Service stays active; billing remains overdue`

### Billing settings page

Rename misleading label:

- from `Auto-disconnect after grace period`
- to `Auto-suspend overdue subscribers`

This matches the actual code behavior.

## Recommended Audit and Notification Behavior

Create audit log entries for:

- palugit granted
- palugit extended
- palugit removed
- auto-suspend skipped because palugit is active
- manual suspend
- reconnect

Optional Telegram notifications:

- subscriber placed on palugit
- palugit expired
- subscriber auto-suspended after palugit expiry

## Recommended Admin Workflow

### Case A: Client asks for extension

1. subscriber is overdue
2. admin opens subscriber page
3. admin grants palugit until agreed date
4. subscriber remains active
5. scheduler respects hold

### Case B: Client misses extension promise

1. palugit expires
2. scheduler sees overdue + no active hold
3. subscriber gets auto-suspended if global auto-suspend is enabled

### Case C: Admin wants full manual control

1. keep global auto-suspend disabled
2. use overdue as financial flag only
3. use palugit note for staff visibility
4. admin manually suspends when needed

This is still valid operationally, but the subscriber-level palugit fields remain useful for visibility and audit.

## Technical Implementation Plan

### Phase 1: Data model and admin workflow

1. add subscriber palugit fields
2. create migration
3. expose fields in admin/subscriber form where appropriate
4. add grant/remove palugit actions on subscriber detail
5. add audit logging

### Phase 2: Scheduler enforcement

1. update overdue auto-suspend query
2. ignore subscribers with active palugit hold
3. log skipped subscribers when hold is active

### Phase 3: UI clarity

1. rename billing setting label from auto-disconnect to auto-suspend
2. show palugit state in subscriber detail
3. show optional badge in subscriber list

### Phase 4: Safety improvements

1. improve suspend flow so MikroTik enforcement result is clearer
2. show explicit warning if app status changed but PPP secret was not disabled
3. optionally add reconnect recommendation after successful payment

## Non-Goals for First Implementation

To keep the first version manageable, do not include yet:

- fully automatic reconnect on payment
- multiple staged collection levels
- SMS promise-to-pay automation
- collections dashboard scoring

Those can come later.

## Recommended First Release Scope

Implement only:

1. per-subscriber palugit fields
2. grant/remove palugit UI
3. scheduler skip logic
4. label cleanup from auto-disconnect to auto-suspend
5. audit trail

This gives a high-value operational result without making billing logic too complex.

## Final Recommendation

The best design is:

- keep `overdue` as billing truth
- keep `suspended` as service enforcement truth
- add `palugit` as an admin-controlled temporary hold layer

This is the cleanest workflow for real ISP operations.

## GO Signal

If this plan looks correct, reply only with:

`GO overdue grace`

Then implementation can start.
