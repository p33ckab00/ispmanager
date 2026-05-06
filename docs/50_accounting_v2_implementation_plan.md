# Accounting v2 Implementation Plan

This document turns the Accounting, BIR, and NTC compliance concept into an
implementation plan for the Accounting v2 upgrade. It preserves the locked
product decisions, the complete release direction, and the next buildable slice
so the work can be implemented without rereading the planning conversation.

## 1. Summary

Build Accounting v2 as one production-oriented release, internally phased but
delivered as a complete subsystem. The first release will use:

- draft-then-approve posting
- backfill and reconciliation cutover
- template-selectable taxpayer setup
- BIR loose-leaf and eBIRForms guide mode only

Current billing PDFs remain billing statements, not official BIR invoices.

Regulatory boundary: v1 will generate books, worksheets, schedules, archives,
and filing guides. It will not claim CAS/CBA/EIS readiness or direct BIR/NTC
submission.

## 1A. Implementation Status

Slice 1A, the backend ledger foundation, has been implemented as an additive
change beside the existing income and expense tracker. It does not replace any
current accounting pages yet.

Implemented in Slice 1A:

- `AccountingEntity`
- `AccountingSettings`
- `AccountingPeriod`
- `ChartOfAccount`
- `JournalEntry`
- `JournalLine`
- `SourceDocumentLink`
- four seedable ISP COA templates
- monthly accounting period generation
- manual draft journal creation service
- balanced-posting validation
- posted journal immutability
- locked or closed period posting block through open-period-only posting
- management command: `seed_accounting_v2_foundation`
- focused tests for template seeding, periods, posting, locked periods, line
  validation, and posted immutability

Explicitly not included in Slice 1A:

- no setup wizard UI yet
- no chart, period, journal, or trial balance pages yet
- no billing/payment automatic draft posting yet
- no BIR/NTC exports yet
- no official BIR invoice behavior
- no CAS/CBA/EIS claim

The existing `/accounting/` dashboard, income pages, expense pages, and payment
to `IncomeRecord` mirror remain unchanged for compatibility.

Slice 1B workspace UI has also been implemented for manual Accounting v2 use.
It adds setup, chart, periods, journal list/detail/create/post, trial balance,
dashboard status links, and read-only ledger role preset permissions.

Slice 1C billing/payment draft posting has started in
`docs/53_accounting_v2_slice_1c_billing_payment_draft_posting.md`. That plan
documents the source-event gaps, resolved posting rules, idempotency behavior,
customer EWT/2307 handling, review queue, and tests needed before
the remaining source-posting work. Slice 1C-A implements the safe first
vertical: source posting review records, non-VAT invoice draft journals,
payment draft journals, customer advance application drafts, and customer
EWT/CWT claim tracking for BIR Form 2307 follow-up.
Slice 1C-B adds the guided payment workflow for customer EWT/CWT, withholding
allocations against invoice balances, and the `/accounting/withholding/2307/`
follow-up schedule.

## 2. Locked Decisions

- Accounting v2 is a complete subsystem, not a small extension of the current
  income and expense tracker.
- Existing `IncomeRecord` and `ExpenseRecord` remain readable for legacy review,
  migration, and reconciliation.
- The first release uses draft-then-approve journal posting.
- Billing/payment/expense events may create draft accounting entries, but they
  do not affect official GL reports until approved and posted.
- Historical data uses a backfill and reconciliation cutover, not a blind hard
  migration.
- Taxpayer setup is selected from templates rather than hard-coded to one
  entity type.
- BIR v1 output is loose-leaf books and eBIRForms encoding guides only.
- Current billing statement PDFs remain non-BIR billing statements in v1.
- CAS/CBA/EIS-related fields may exist for future readiness but are not enabled
  as official operating modes in v1.
- Single accounting entity is shown in the UI for now, while models stay
  tenant-ready through `AccountingEntity`.

## 3. Key Implementation Changes

Replace the lightweight accounting surface with an Accounting v2 workspace while
keeping `IncomeRecord` and `ExpenseRecord` readable for migration and
reconciliation.

Add accounting-owned setup:

- `AccountingEntity`
- `AccountingSettings`
- `TaxProfile`
- `AccountingPolicy`
- `DocumentSeries`
- `TaxCode`

Seed four chart-of-accounts templates:

- ISP Non-VAT Sole Proprietor
- ISP VAT Sole Proprietor
- ISP Non-VAT Corporation
- ISP VAT Corporation

Require the setup wizard before Accounting v2 posting or reporting is marked
live.

Add ledger core:

- `ChartOfAccount`
- `AccountingPeriod`
- `JournalEntry`
- `JournalLine`
- `SourceDocumentLink`

Journal states:

- `draft`
- `posted`
- `reviewed`
- `locked`
- `reversed`
- `voided`

Draft journal entries must balance before approval. Posted entries cannot be
edited after period lock.

Add source-document posting:

- Billing invoice creates draft `Dr AR / Cr Revenue / Cr Output VAT if
  applicable`.
- Payment creates draft `Dr Cash/Bank/Wallet Clearing / Cr AR` or customer
  advance logic.
- Expense creates draft AP/cash/input VAT entries.
- Refund, waiver, bad debt, credit forfeiture, and advance application get
  explicit posting services.

Add cutover workflow:

- `OpeningBalanceImport`
- `OpeningBalanceLine`
- import and reconcile AR per subscriber, credits, cash/bank/wallet balances,
  AP, inventory, fixed assets, taxes, loans, and equity
- block Accounting v2 go-live until GL control accounts reconcile with
  subledgers

Add approval workflow:

- Draft source journals are created automatically but do not hit official GL
  reports until approved and posted.
- Add review queues for unapproved, unbalanced, unmapped, and period-blocked
  entries.
- Corrections after lock use reversal or adjustment entries only.

Add financial statements:

- Trial Balance
- General Ledger
- Balance Sheet
- Income Statement
- Cash Flow
- Changes in Equity

Add ISP schedules:

- AR aging
- subscriber deposits
- customer advances
- revenue by service and area
- network assets
- depreciation
- CPE inventory
- VAT
- withholding
- bad debts and waivers

Add reconciliation:

- `PaymentSettlementBatch`
- `BankStatementImport`
- `BankReconciliation`
- track cash, bank, GCash, Maya, and gateway clearing from recorded payment to
  settlement
- support gateway fees, duplicate references, reversals, chargebacks, and
  refunds

Add BIR compliance:

- Loose-leaf books: General Journal, General Ledger, Cash Receipts, Cash
  Disbursements, Sales Journal, Purchase/Expense Journal, Sales Invoice
  Register, Collection Register, AR/AP subsidiary ledgers, VAT ledgers, and
  asset/inventory ledgers.
- `BirFormMapping` powers versioned eBIRForms guides for 2550Q, 2551Q,
  1701/1701Q, and 1702/1702Q as applicable.
- Add schedules for 2307/CWT, SAWT/MAP/QAP/SLSP if enabled, annual inventory
  list, depreciation, and VAT reconciliation.
- Finalized exports include manifest, page counts, file hashes,
  prepared/reviewed metadata, and immutable archive.

Add NTC compliance:

- `NtcReportTemplate`
- report runs
- filing checklist
- fee tracker
- archive record
- generate quarterly VAS-style packs, annual finances/operations pack,
  subscriber counts, revenue by service type, service area,
  facilities/network summary, QoS, incident, and complaint summaries
- keep templates configurable because NTC office/report layouts may vary

Add compliance calendar:

- `ComplianceCalendarItem` tracks BIR/NTC due dates, preparation, review, filed
  date, filing channel, reference number, attachments, and amended status.

Exports and interfaces:

- Server-rendered Accounting UI follows the existing Django template style.
- PDF uses the existing `xhtml2pdf`/ReportLab path.
- Add `openpyxl` dependency for `.xlsx` workbooks.
- Keep REST API minimal/read-only for v1 reports unless an existing page
  requires async data.
- Add Data Exchange exports for COA, journals, trial balance, GL, BIR books,
  and compliance package manifests.

## 4. Slice Roadmap

### Slice 1A - Ledger Foundation

Build accounting entity, accounting settings, COA templates, periods, manual
draft journal service, post validation, source link model, and backend tests.

This slice is additive and keeps the legacy accounting pages working.

### Slice 1B - Accounting Workspace

Build setup wizard, chart of accounts page, period page, manual journal UI,
posting action, permissions, trial balance, and dashboard status cards.

### Slice 1C - Billing and Payment Draft Posting

Build draft journal creation from existing billing/payment source documents.

This slice connects billing to accounting, but only as draft accounting entries.
It does not approve/post source journals automatically.
The detailed implementation plan is in
`docs/53_accounting_v2_slice_1c_billing_payment_draft_posting.md`.

No BIR/NTC exports, no official BIR invoices, no CAS/EIS claims, no opening
balance cutover, and no financial statements beyond Trial Balance.

### Slice 2 - Cutover and Opening Balances

Add opening balance import, subscriber AR reconciliation, credit reconciliation,
cash/bank/wallet opening balances, AP, inventory, fixed assets, taxes, loans,
equity, and go-live readiness checks.

### Slice 3 - Financial Statements and Subledgers

Add General Ledger, Balance Sheet, Income Statement, Cash Flow, Changes in
Equity, AR aging, AP aging, VAT ledger, fixed asset schedule, depreciation
schedule, and CPE/inventory schedule.

### Slice 4 - BIR Books and Guides

Add loose-leaf books, BIR form guide registry, VAT and percentage-tax schedules,
withholding/2307 schedules, annual inventory list support, PDF/XLSX exports,
manifest, file hashes, and immutable package archives.

### Slice 5 - NTC Compliance Packs

Add NTC profile, configurable templates, quarterly VAS-style packs, annual
finances/operations pack, subscriber/service-area schedules, network/facility
schedules, QoS/incident/complaint summaries, filing checklist, and archive
records.

### Slice 6 - Reconciliation, Calendar, and Hardening

Add bank/wallet/gateway reconciliation, settlement batches, compliance
calendar, filing status workflow, amendment workflow, archive verification,
multi-tenant hardening, and full compliance diagnostics.

## 5. Slice 1C: Billing and Payment Draft Posting

### Summary

Build the source-posting portion of the first Accounting v2 release. Slice 1C-A
now covers the safe billing/payment foundation: billing invoices, payments, and
advance applications can create or reuse Accounting v2 draft journal entries
for review. Customer EWT/CWT claimed through BIR Form 2307 is tracked
separately from cash receipts so gross AR can be settled by net cash plus
creditable withholding tax receivable.

Existing `IncomeRecord` and `ExpenseRecord` stay intact as legacy records for
later migration.

Remaining Slice 1C work is refund-due/refund-paid posting, credit forfeiture,
waiver/void posting, retry/backfill tooling, 2307 attachment/export schedules,
and full VAT invoice posting after invoice tax breakdown support exists.

### Key Changes

Use the Accounting v2 models already added under `apps/accounting`:

- `AccountingEntity`: single active company for now; tenant-ready
- `AccountingSettings`: compliance mode, fiscal year, currency, setup status
- `AccountingPeriod`: monthly periods with `open`, `closed`, `locked`
- `ChartOfAccount`: account code, name, account type, normal balance, active
  flag
- `JournalEntry`: `draft`, `posted`, `reviewed`, `reversed`, `voided`
- `JournalLine`: debit/credit lines linked to accounts
- `SourceDocumentLink`: bridge for billing/payment/expense draft posting

Add billing/payment draft posting:

- invoice generation creates or reuses a draft journal entry:
  `Dr Accounts Receivable / Cr Internet Service Revenue / Cr Output VAT if VAT`
- payment recording creates or reuses a draft journal entry:
  `Dr Cash/Bank/Wallet Clearing / Cr Accounts Receivable`
- unallocated payment or overpayment creates/reuses customer advance logic:
  `Dr Cash/Bank/Wallet Clearing / Cr Customer Advances`
- payment allocation creates/reuses a draft application entry only when needed
  by the customer advance workflow
- customer EWT/CWT claimed through BIR Form 2307 creates/reuses a CWT receivable
  draft line and does not reduce VAT, revenue, discount, waiver, or bad debt
- refund completion creates/reuses a draft refund journal entry
- waiver, bad debt, and credit forfeiture create/reuse explicit draft journal
  entries
- source posting is idempotent through `SourceDocumentLink`, keyed by source
  model, source ID, and posting type
- source draft journals appear in a review queue before posting

Add UI routes:

- `/accounting/review/`
- retry blocked source posting from review queue

Update Accounting dashboard:

- show unreviewed source draft count
- show blocked source posting count

Add permissions and role presets:

- review source draft entries
- ISP Admin gets all
- cashier remains read-only for Accounting v2 source drafts unless explicitly
  granted review/post permissions

### Implementation Notes

- Use `Decimal` for all amounts.
- Enforce exactly one side per journal line: debit or credit, not both.
- Account normal balance:
  - debit: assets, expenses, contra-liability/equity/revenue if later needed
  - credit: liabilities, equity, revenue
- Account types for this slice:
  - `asset`
  - `liability`
  - `equity`
  - `revenue`
  - `direct_cost`
  - `expense`
  - `other_income`
  - `other_expense`
- Draft journals may be edited/deleted.
- Posted journals cannot be edited/deleted.
- Reversal is not required in this slice, but status/model fields must allow it
  later.
- Wire billing invoice/payment services to create draft journals only.
- Do not approve or post source-created draft journals automatically.
- Billing must remain fail-soft while Accounting v2 is not live. Missing setup,
  period, or account mapping should create a blocked review result or skip
  posting without breaking invoice/payment creation.
- VAT draft posting must not guess Output VAT from gross invoices until tax
  breakdown or explicit VAT posting settings exist.
- EWT/CWT withheld by customers must not reduce Output VAT. It is an
  income-tax credit asset supported by received or pending BIR Form 2307.
- Keep `Payment.amount` as actual cash received; record customer withholding in
  a separate Accounting v2 withholding/certificate record.
- Keep the existing `IncomeRecord` payment mirror during this slice, but mark it
  as legacy reporting; official Accounting v2 reports must use posted
  `JournalEntry` rows only.
- Do not double-count legacy `IncomeRecord` values in Trial Balance or any
  Accounting v2 report.
- Do not generate official BIR invoices.
- Do not remove current income/expense summaries.

## 6. Full Release Test Plan

### Ledger integrity

- balanced draft journal required before posting
- posted journal cannot be edited after lock
- reversal creates equal/opposite entry
- trial balance debits equal credits

### Source document scenarios

- VAT invoice full payment
- VAT invoice partial payment
- non-VAT invoice with percentage-tax guide
- advance payment before invoice
- customer credit applied to later invoice
- waiver/service credit
- bad debt write-off
- refund of customer advance
- input VAT expense
- fixed asset purchase and depreciation
- inventory purchase and CPE issuance

### Reconciliation

- AR aging equals GL AR control account
- AP aging equals GL AP control account
- VAT schedule equals VAT ledgers
- wallet/gateway settlement with fees reconciles to bank/clearing
- duplicate/reversed payment remains flagged until resolved

### Compliance outputs

- loose-leaf PDF and XLSX include cover, pages, manifest, hashes
- archived compliance package cannot be overwritten
- BIR form guide uses correct active mapping version
- NTC report template can be generated and archived
- compliance calendar moves through due, prepared, reviewed, filed, amended

### Migration

- opening balances import validates debits/credits
- historical billing AR reconciles to subscriber subledger and GL control
- legacy income/expense records remain accessible after cutover

## 7. Slice 1C Focus Test Plan

The detailed Slice 1C test plan is in
`docs/53_accounting_v2_slice_1c_billing_payment_draft_posting.md`. The summary
below keeps the roadmap-level checks visible.

### Carry-forward foundation checks

- COA template seeds expected required accounts.
- setup wizard creates one active accounting entity.
- setup cannot seed duplicate accounts for the same entity.
- accounting periods are created for all 12 months.
- balanced draft journal can be posted.
- unbalanced draft journal cannot be posted.
- journal line cannot have both debit and credit.
- posted journal is read-only.
- posting into locked period is blocked.
- source-created draft journals remain editable only while draft.

### Billing/payment draft posting tests

- generated billing invoice creates one draft source journal.
- rerunning invoice generation reuses the existing source journal.
- recorded payment creates one draft source journal.
- overpayment creates a customer advance draft journal.
- customer EWT/CWT collection debits cash for net receipt, debits CWT
  receivable for tax withheld, and credits AR for gross settlement.
- payment allocation against a later invoice creates/reuses the required
  customer advance application draft journal.
- refund completion creates one draft refund journal.
- waiver, bad debt, and credit forfeiture create explicit draft journals.
- source-created draft journals do not appear in Trial Balance until posted.
- legacy `IncomeRecord` mirror does not affect Accounting v2 Trial Balance.

### Trial balance regression tests

- posted entries appear in trial balance.
- draft entries do not appear.
- total debits equal total credits.
- account balances follow normal balance correctly.

### Permission regression tests

- unauthorized users cannot manage setup/chart/journals.
- read-only auditor can view but not post.
- admin can complete setup and post journals.

### Regression tests

- existing payment-to-income mirror still works.
- existing accounting dashboard still loads before setup and redirects/prompts
  correctly after setup.

## 8. Assumptions and Defaults

- One Accounting v2 release, implemented internally in phases: foundation,
  posting, cutover, statements, BIR, NTC, reconciliation, hardening.
- Slice 1A created the backend ledger foundation first so the existing
  accounting pages stayed stable.
- Slice 1B completed the first browser workspace.
- Slice 1C is the next billing/payment source draft posting slice.
- One active `AccountingEntity` in UI for now, but all new tables include entity
  foreign keys.
- Default BIR mode is `loose_leaf_guides`; CAS/EIS modes are stored as future
  settings but disabled in UI.
- Current billing statement PDFs remain non-BIR billing statements in v1.
- Accounting v2 creates draft journals automatically; accountant/admin approval
  posts them to GL.
