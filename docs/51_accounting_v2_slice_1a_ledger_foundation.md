# Accounting v2 Slice 1A Ledger Foundation

This document records the first implemented Accounting v2 slice. Slice 1A is a
backend-first foundation that adds the double-entry ledger objects without
replacing the current income and expense accounting pages.

## Delivered Scope

Slice 1A adds these accounting-owned models:

- `AccountingEntity`: one active entity now, entity-keyed records for future
  multi-tenant support
- `AccountingSettings`: compliance mode, fiscal year start, setup status, and
  active COA template
- `AccountingPeriod`: monthly open, closed, or locked accounting periods
- `ChartOfAccount`: entity-specific account code, name, type, normal balance,
  parent, active flag, and system-template flag
- `JournalEntry`: draft, posted, reviewed, locked, reversed, or voided journal
  header
- `JournalLine`: debit or credit line tied to one chart account
- `SourceDocumentLink`: reserved bridge for later billing, payment, expense,
  opening-balance, and adjustment posting

Slice 1A also adds:

- migration `accounting.0002`
- four ISP chart-of-accounts templates:
  - ISP Non-VAT Sole Proprietor
  - ISP VAT Sole Proprietor
  - ISP Non-VAT Corporation
  - ISP VAT Corporation
- idempotent COA seeding service
- 12-month accounting period creation service
- `create_accounting_foundation` bootstrap service
- manual draft journal creation service
- journal posting service
- `seed_accounting_v2_foundation` management command
- accounting model/service tests

## Ledger Rules Implemented

- Journal lines must have exactly one side: debit or credit.
- Draft journal entries may be created unbalanced for review.
- Posting requires at least two lines.
- Posting requires total debits to equal total credits.
- Posting is allowed only when the accounting period is open.
- Posted, reviewed, locked, reversed, and voided journal entries are read-only.
- Lines under posted, reviewed, locked, reversed, and voided journal entries are
  read-only.
- Chart account codes are unique per accounting entity.
- Journal entry numbers are unique per accounting entity.
- Source document links are unique per entity, source app, source model, and
  source ID.

## Compatibility Boundary

Existing behavior intentionally remains unchanged:

- `/accounting/` still loads the legacy income and expense dashboard.
- `/accounting/income/` and `/accounting/expenses/` still use `IncomeRecord`
  and `ExpenseRecord`.
- Billing payment mirroring to `IncomeRecord` remains active.
- Billing, subscriber, SMS, diagnostics, and data exchange imports that refer to
  `IncomeRecord` or `ExpenseRecord` continue to use those models.

Slice 1A does not generate Accounting v2 reports yet, so legacy totals are not
mixed with posted journal totals.

## Command Usage

Seed the foundation with the default Non-VAT sole proprietor template:

```bash
.venv/bin/python manage.py seed_accounting_v2_foundation
```

Seed a corporation VAT template for a specific fiscal year:

```bash
.venv/bin/python manage.py seed_accounting_v2_foundation \
  --name "Example ISP" \
  --legal-name "Example ISP Corporation" \
  --tin "000-000-000-00000" \
  --template isp_vat_corporation \
  --year 2026
```

The command reuses the active accounting entity if one already exists. It
re-seeds missing or changed system accounts and reuses existing periods for the
same fiscal year.

## Not Included In Slice 1A

- setup wizard UI
- chart of accounts UI
- accounting period UI
- journal list/detail/create UI
- trial balance report
- billing invoice draft posting
- payment draft posting
- expense draft posting
- opening balance import
- BIR loose-leaf books or eBIRForms guide output
- NTC report packs
- official BIR invoice generation
- CAS/CBA/EIS operating mode

## Validation Notes

Local validation performed:

- `.venv/bin/python manage.py check`
- `.venv/bin/python manage.py makemigrations --check --dry-run`
- `.venv/bin/python manage.py seed_accounting_v2_foundation --help`
- `.venv/bin/python manage.py sqlmigrate accounting 0002`

The accounting test file was added and discovered by Django, but the local
PostgreSQL role cannot create a test database in this environment:

```text
Got an error creating the test database: permission denied to create database
```

## Next Slice

Slice 1B should complete the original first Accounting v2 slice by adding:

- setup wizard and accounting-owned settings screen
- chart, period, journal, and trial balance pages
- post action from the UI
- permissions and role preset updates
- Accounting dashboard status cards
- billing invoice draft posting
- payment draft posting
- source review queue
- regression checks proving old income/expense pages still load
