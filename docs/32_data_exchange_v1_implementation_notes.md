# Data Exchange V1 Implementation Notes

## Summary

`Data Exchange V1` adds a shared import/export workflow for operational data instead of scattering legacy upload logic across subscribers, billing, and accounting pages.

The feature is designed to support safer onboarding, legacy migration, and reporting workflows while preserving the current billing and payment rules already enforced by the system.

## Scope Implemented

### Central Data Exchange Center

A new internal page is available at:

- `/data-exchange/`

This page serves as the shared control center for:

- import templates
- dry-run imports
- applied imports
- quick export downloads
- import/export job history

### Datasets Included in V1

Exports:

- Subscribers
- Invoices
- Payments
- Expenses

Imports:

- Subscribers
- Payments

## Design Intent

The implementation avoids placing all import/export responsibilities inside the subscribers module alone.

That is important because:

- subscriber data belongs to one domain
- billing data belongs to another
- payments affect invoice allocation
- billing payments also affect accounting income

The shared `Data Exchange` workflow keeps those responsibilities explicit and lets each dataset follow its own rules.

## Export Workflow

V1 exports are CSV-based and optimized for operations staff.

Current export behavior:

- list-level quick exports are available from relevant pages
- exports respect current query filters where applicable
- a central export path is also available from the Data Exchange dashboard
- each export creates a history record

### Export Datasets

#### Subscribers export

Includes:

- identity and contact fields
- service type
- plan name
- billing-related fields
- status fields

#### Invoices export

Includes:

- invoice number
- subscriber identifiers
- billing period
- amount and paid amount
- remaining balance
- status
- plan snapshot
- rate snapshot
- public short code

#### Payments export

Includes:

- subscriber identifiers
- payment amount
- method
- reference
- notes
- paid date/time
- unallocated amount

#### Expenses export

Includes:

- date
- category
- description
- vendor
- reference
- amount
- recorded by

## Import Workflow

V1 imports are CSV-based and follow a `dry-run first` model.

### Import steps

1. Download the correct CSV template
2. Fill the template using the expected headers
3. Upload the file
4. Run `Dry Run`
5. Review preview rows and validation errors
6. Run `Apply Import` only when validation is clean

### Dry Run behavior

Dry run:

- parses the uploaded CSV
- validates rows
- previews create/update/skip decisions
- stores a job history record
- does not mutate production data

### Apply behavior

Apply:

- stops if validation errors exist
- creates a job history record
- performs the import only when the validation result is clean

## Subscriber Import Rules

Subscriber import currently supports:

- create new subscribers
- update existing subscribers matched by `username`

Supported fields include:

- identity and contact fields
- MikroTik-related profile fields
- plan assignment
- rate
- cutoff day
- billing effective date
- due day offset
- billable flag
- start date
- status
- notes
- SMS opt-out

### Validation rules

Current subscriber import validation checks:

- `username` required
- duplicate usernames inside the same file are rejected
- service type must be one of the supported internal service values
- status must be one of the supported subscriber statuses
- plan name must exist if provided
- cutoff day must be between `1` and `28`
- decimal, integer, date, and boolean parsing must be valid
- email format must be valid if provided

## Payment Import Rules

Payment import is intentionally routed through the existing billing payment service instead of writing payment rows directly.

This is the critical design choice in V1.

### Why this matters

Using the existing payment flow means imported payments still:

- create `Payment` records
- allocate against invoices using the current allocation logic
- preserve unallocated credit behavior
- create linked accounting income through the current payment-to-income path

### Validation rules

Current payment import validation checks:

- `subscriber_username` must exist
- amount must be a valid positive decimal
- method must match an allowed payment method
- paid date/time format must be valid
- duplicate rows inside the same file are skipped
- payments already existing in the database with the same signature are skipped

## Job History

Every import and export creates a `DataExchangeJob` record.

Stored details include:

- job type
- dataset
- file name
- dry run or applied mode
- row counts
- create/update/skip/error counts
- compact preview data
- validation error summary
- user who ran the job

This provides basic operational traceability for staff actions.

## UI Placement

V1 uses two access patterns:

### Quick export from list pages

Quick export entry points were added to:

- subscribers list
- invoices list
- expense list

The accounting and billing UI also include shortcuts back into the central Data Exchange page.

### Central Data Exchange page

The sidebar now includes:

- `Data Exchange`

This gives staff one consistent place for import templates, dry runs, history, and cross-domain data work.

## Files Added or Updated

Main implementation files:

- `apps/data_exchange/models.py`
- `apps/data_exchange/forms.py`
- `apps/data_exchange/services.py`
- `apps/data_exchange/views.py`
- `apps/data_exchange/urls.py`
- `templates/data_exchange/dashboard.html`

Integration points:

- `config/settings.py`
- `config/urls.py`
- `templates/partials/sidebar.html`
- `templates/subscribers/list.html`
- `templates/billing/invoice_list.html`
- `templates/accounting/income_list.html`
- `templates/accounting/expense_list.html`

Migration:

- `apps/data_exchange/migrations/0001_initial.py`

## Validation Performed

The following checks were run during implementation:

- `manage.py migrate data_exchange`
- `manage.py check`
- `manage.py makemigrations --check --dry-run`
- route verification for:
  - dashboard
  - CSV templates
  - export endpoints
- subscriber import dry run and apply verification
- payment import apply verification
- confirmation that imported payments still produce linked accounting income

## Current V1 Limitations

This first version is intentionally scoped and does not yet include:

- invoice import
- billing snapshot import
- full ZIP package export
- XLSX support
- background queued imports
- row-mapping UI for arbitrary CSV columns
- expense import
- rollback/revert for completed imports

## Recommended Next Phase

The next safe extension after V1 is:

- invoice import
- opening balance import
- full export package
- richer history/report downloads

That next phase should still preserve the rule that billing truth is driven by invoice/payment logic rather than ad hoc table writes.
