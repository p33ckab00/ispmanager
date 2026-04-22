# Payment To Accounting Wiring Fix

## Summary

The subscriber `Record Payment` flow now creates an accounting `IncomeRecord`
automatically inside the same transactional billing workflow.

## Problem Before

The system had a gap between billing and accounting:

- `Record Payment` created a billing `Payment`
- invoice balances and statuses were updated correctly
- accounting income was not created automatically
- a separate manual sync route existed as a fallback
- the manual sync path referenced `payment.billing_record`, which does not exist on the `Payment` model

## What Changed

### Billing payment flow

The billing payment service now:

- creates the `Payment`
- creates the linked accounting `IncomeRecord`
- allocates the payment to the subscriber's open invoices
- updates invoice statuses in the same transaction

### Accounting fallback sync

The accounting sync service now:

- uses the correct relationship: `payment.subscriber`
- reuses the same helper used by the billing flow
- remains available as a repair or backfill tool instead of being the primary path

## Resulting Behavior

When staff records a payment from the subscriber page:

1. a `Payment` row is created
2. an `IncomeRecord` row is created automatically
3. allocations are applied to the oldest open invoices
4. invoice balances and statuses are updated

This keeps billing and accounting aligned without requiring a separate manual sync step.

## Architectural Direction

This matches the intended architecture better:

- `Payment` is the billing truth for money received
- `IncomeRecord` is the accounting mirror of that payment
- `/accounting/sync/` is now a reconciliation tool, not the main workflow

## Files Updated

- `apps/billing/services.py`
- `apps/accounting/services.py`
