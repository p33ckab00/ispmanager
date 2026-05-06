# Accounting v2 Slice 1B Workspace UI

This document records the second Accounting v2 implementation slice. Slice 1B
makes the Slice 1A ledger foundation usable from the browser while preserving
the current legacy accounting pages.

## Delivered Scope

Slice 1B adds server-rendered Accounting v2 pages:

- `/accounting/setup/`
- `/accounting/chart/`
- `/accounting/periods/`
- `/accounting/journals/`
- `/accounting/journals/add/`
- `/accounting/journals/<id>/`
- `/accounting/trial-balance/`

The existing `/accounting/` dashboard now shows an Accounting v2 status panel
with links to setup, chart, journals, and trial balance. The legacy income and
expense summary remains on the same page.

## User Workflows

An admin can now:

- seed or refresh the active accounting foundation from the browser
- choose one of the four ISP COA templates
- view the seeded chart of accounts
- view monthly accounting periods
- create a manual draft journal entry
- post a balanced draft journal entry
- view posted activity in a basic period trial balance

## Safeguards

- Missing Accounting v2 setup redirects workspace pages to setup.
- Setup remains guarded by `accounting.manage_accounting_setup`.
- Manual journal creation requires `accounting.add_journalentry`.
- Posting requires `accounting.post_journalentry`.
- Cashier role presets receive read-only access to Accounting v2 ledger objects.
- Existing legacy income/expense pages and payment-to-income mirroring are not
  rewired in this slice.

## Trial Balance Boundary

The first trial balance is intentionally basic:

- period-based
- uses posted `JournalEntry` rows only
- excludes draft journals
- excludes legacy `IncomeRecord` and `ExpenseRecord`
- shows debit, credit, and normal-balance amount per active account with posted
  activity

Financial statement formatting, opening balances, comparative periods, and
export-ready books are later slices.

## Not Included

- billing invoice draft posting
- payment draft posting
- expense draft posting
- source review queue
- journal editing UI
- period close/lock UI
- BIR loose-leaf books
- NTC report packs

## Validation Notes

Local validation performed:

- `.venv/bin/python manage.py check`
- `.venv/bin/python manage.py makemigrations --check --dry-run`
- `.venv/bin/python -m py_compile apps/accounting/forms.py apps/accounting/views.py apps/core/role_presets.py`

The environment still cannot run Django database tests because the PostgreSQL
role cannot create a test database.

## Next Slice

Slice 1C is planned in
`docs/53_accounting_v2_slice_1c_billing_payment_draft_posting.md`. It should
add billing and payment draft posting:

- invoice source draft journal
- payment source draft journal
- customer advance handling
- source idempotency through `SourceDocumentLink`
- review queue for unposted source journals
- regression tests proving legacy billing and income mirroring still work
