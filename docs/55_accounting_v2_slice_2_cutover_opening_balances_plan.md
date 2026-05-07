# Accounting v2 Slice 2 Cutover and Opening Balances Plan

## Summary

Slice 2 turns the Accounting v2 ledger from a draft-posting workspace into a
cutover-ready accounting subsystem. The goal is to let an ISP operator define a
cutover date, import or enter opening balances, reconcile those balances against
subscriber and billing subledgers, and create a balanced opening journal draft
that an accountant can review and post.

Slice 2 must not silently migrate history into the official GL. It must choose
one controlled approach per balance:

- use opening balances for pre-cutover totals and subledger details
- use source draft posting for post-cutover billing/payment activity
- keep historical source backfill for diagnostics and review, not as a blind
  official ledger import

The first buildable implementation should be **Slice 2A: Opening Balance and
Cutover Foundation**.

## Implementation Status

Slice 2A has been implemented as the cutover/opening balance foundation.

Implemented:

- `CutoverPlan` with one non-voided active plan per accounting entity.
- `OpeningBalanceImport` batches for manual, CSV, XLSX, and future system
  snapshot sources.
- `OpeningBalanceLine` with entity/account validation, line categories,
  optional subscriber/vendor references, validation status, and a database
  check that only debit or credit can be entered.
- Cutover setup page at `/accounting/cutover/setup/`.
- Cutover dashboard at `/accounting/cutover/`.
- Opening balance import creation and detail pages.
- Manual opening balance line entry.
- Import validation that refreshes debit/credit totals, marks invalid lines,
  blocks unbalanced batches, and stores validation errors.
- Draft opening journal generation using source type `opening_balance`.
- Readiness page at `/accounting/cutover/readiness/`.
- Accounting dashboard link and cutover status card.
- Cashier/read-only accounting role presets can view cutover and opening
  balance records; management actions remain restricted to accounting setup
  permissions.
- Focused tests for active plan updates, line one-side validation, unbalanced
  import blocking, balanced opening journal creation, and readiness.

Still not included in Slice 2A:

- CSV/XLSX upload parsing, even though import source types are reserved.
- Bank, wallet, AP, inventory, fixed asset, depreciation, tax, loan, and equity
  detail schedules.
- Cutover approval/live transition.
- Post-cutover blocking of pre-cutover source posting double counts.
- VAT invoice tax breakdown and final VAT cutover reconciliation.

Slice 2B has also been implemented for subscriber-facing reconciliation.

Implemented:

- `CutoverReconciliationSnapshot` for frozen cutover reconciliation runs.
- `CutoverSubscriberBalanceLine` for per-subscriber AR and customer advance
  differences.
- Subscriber AR source snapshot based on invoices created on or before cutover,
  less allocations recorded on or before cutover.
- Paid-after-cutover invoices remain AR in the cutover snapshot.
- Voided or waived invoices are excluded only when the void/waiver happened on
  or before cutover.
- Customer advance source snapshot based on payments received on or before
  cutover, less allocations and credit adjustments effective on or before
  cutover.
- Opening balance comparison against subscriber-level `subscriber_ar` and
  `customer_advance` opening lines.
- Reconciliation page at `/accounting/cutover/reconciliation/`.
- Generate snapshot action that preserves prior snapshots instead of rewriting
  them.
- Readiness checks for latest subscriber reconciliation snapshot and AR/advance
  total differences.
- Snapshot status requires subscriber-level lines to match; aggregate totals
  cannot hide offsetting subscriber differences.

Still not included in Slice 2B:

- Formal frozen source-detail tables for each invoice/payment record represented
  in the snapshot.
- CSV/XLSX export of reconciliation differences.
- Account-level drilldown for one GL control line without subscriber-level
  opening detail.
- Cash, bank, wallet, AP, tax, asset, loan, and equity schedules.
- Final cutover approval/live gate.

## Locked Decisions

- Accounting v2 cutover is explicit. No automatic go-live happens just because
  setup exists.
- Cutover uses a single active `AccountingEntity` for now.
- Opening balances create draft journal entries only.
- Opening balance drafts must balance before posting.
- Posted opening balances are immutable through normal journal rules.
- Pre-cutover billing history must not be double-counted through both opening
  balances and source-posted historical invoices/payments.
- Subscriber AR, customer advances, wallet/bank/cash balances, AP, assets,
  taxes, loans, and equity must reconcile before Accounting v2 is marked live.
- Current billing statement PDFs remain billing statements, not BIR invoices.
- Remaining Slice 1 compliance gaps, such as VAT invoice tax breakdown and
  2307 attachment/export schedules, are not blockers for opening balance
  foundation, but they are blockers for final VAT/BIR compliance completeness.

## Slice 2 Roadmap

### Slice 2A - Opening Balance Foundation

Add cutover date, opening balance imports, opening balance lines, validation,
and a draft opening journal generator.

Deliverables:

- `CutoverPlan`
- `OpeningBalanceImport`
- `OpeningBalanceLine`
- opening balance categories and account mapping
- manual opening balance entry UI
- CSV import UI or management command
- balanced debit/credit validation
- draft opening journal generation
- cutover readiness page

### Slice 2B - Subscriber AR and Credit Reconciliation

Reconcile subscriber-facing balances against GL control accounts.

Deliverables:

- AR per subscriber snapshot at cutover date: implemented.
- customer advances/unallocated credits snapshot: implemented.
- excluded invoice rules for paid, waived, voided, and zero-balance invoices:
  implemented for cutover as-of logic.
- reconciliation report: implemented for subscriber AR and customer advances.
- Remaining improvement: add CSV/XLSX export and richer source-detail drilldown.

### Slice 2C - Cash, Bank, Wallet, AP, and Tax Reconciliation

Add non-subscriber balance schedules and reconciliation checks.

Deliverables:

- cash on hand schedule
- bank account opening balances
- GCash/Maya/gateway clearing opening balances
- AP/vendor opening balances
- CWT/EWT receivable opening balance
- VAT/percentage tax payable opening balance placeholders
- tax and clearing account reconciliation warnings

### Slice 2D - Inventory, Fixed Assets, Loans, and Equity

Add operational ISP balance schedules that are needed for financial statement
readiness.

Deliverables:

- CPE and network inventory opening schedule
- fixed asset opening schedule
- accumulated depreciation opening line support
- loans payable opening schedule
- owner capital/share capital/retained earnings balancing workflow

### Slice 2E - Cutover Approval and Live Gate

Add final readiness gate and live status transition.

Deliverables:

- all required reconciliation checks green or explicitly waived
- opening journal posted
- cutover lock that prevents editing finalized opening imports
- Accounting settings status can move from `foundation_ready` to `live`
- post-cutover dashboard warning if source postings are blocked
- post-cutover source posting policy:
  - draft-only
  - block official close if unreconciled

## Data Model Plan

### CutoverPlan

Purpose: one active cutover plan per accounting entity.

Fields:

- entity
- cutover_date
- status: `draft`, `reconciling`, `ready_for_review`, `approved`, `live`,
  `voided`
- source_policy: `opening_balances_only_pre_cutover`,
  `source_backfill_review_only`, `manual`
- prepared_by
- reviewed_by
- approved_by
- notes
- created_at
- updated_at
- approved_at
- live_at

Rules:

- only one non-voided plan per entity
- cutover date cannot be after the first posted Accounting v2 source journal
  without an explicit warning
- live status requires posted opening journal and passing readiness checks

### OpeningBalanceImport

Purpose: container for one import or manual opening balance batch.

Fields:

- entity
- cutover_plan
- import_type: `manual`, `csv`, `xlsx`, `system_snapshot`
- status: `draft`, `validated`, `journal_created`, `posted`, `voided`
- source_filename
- source_hash
- total_debit
- total_credit
- validation_errors
- created_by
- reviewed_by
- created_at
- updated_at

Rules:

- cannot create opening journal unless total debit equals total credit
- cannot edit after linked opening journal is posted
- voiding a posted opening import requires reversal or adjustment, not direct
  deletion

### OpeningBalanceLine

Purpose: one opening balance detail line.

Fields:

- import batch
- entity
- account
- line_type:
  - `gl_control`
  - `subscriber_ar`
  - `customer_advance`
  - `cash`
  - `bank`
  - `wallet_gateway`
  - `ap_vendor`
  - `inventory`
  - `fixed_asset`
  - `accumulated_depreciation`
  - `tax`
  - `loan`
  - `equity`
  - `other`
- debit
- credit
- subscriber, optional
- vendor_name, optional
- reference
- description
- source_object_type
- source_object_id
- validation_status
- validation_message

Rules:

- exactly one side must be non-zero
- line account must belong to the same entity
- subscriber AR lines must use AR control or a configured AR subledger account
- customer advance lines must use customer advances or a configured liability
  account
- bank/wallet lines should support references such as account name, gateway, or
  settlement account

## Opening Balance Categories

### Subscriber AR

Default account: `1100 Accounts Receivable - Subscribers`

Include:

- open invoices
- partial invoices
- overdue invoices
- unpaid balance as of cutover date

Exclude:

- paid invoices
- voided invoices
- waived invoices after waiver posting or explicit write-off
- invoices fully settled by customer EWT/CWT claim

Gap to resolve:

- Current invoices do not store a formal tax breakdown. VAT entities can still
  import gross AR, but VAT output reconciliation needs Slice 3/4 tax ledgers.

### Customer Advances and Credits

Default account: `2100 Customer Advances`

Basis:

- payments minus allocations minus completed/forfeited/refund adjustments
- customer advance balance per subscriber at cutover date

Gap to resolve:

- Current `get_account_credit_for_subscriber` uses payments, allocations, and
  credit adjustments. Slice 2 must snapshot this calculation to avoid balances
  changing after the cutover report is generated.

### Cash, Bank, Wallet, and Gateway Clearing

Default accounts:

- `1000 Cash on Hand`
- `1010 Bank Accounts`
- `1020 E-Wallet and Gateway Clearing`

Inputs:

- cash count
- bank statement balance at cutover date
- GCash/Maya/gateway settlement balance
- undeposited collections

Gap to resolve:

- There is no bank/wallet statement import model yet. Slice 2A can enter manual
  balances; Slice 2C should add schedules and references.

### AP, Taxes, Assets, Loans, and Equity

Default accounts:

- `2000 Accounts Payable`
- `1210 Creditable Withholding Tax Receivable`
- `1200 Input VAT`, VAT templates only
- `2300 Output VAT`, VAT templates only
- `2330 Percentage Tax Payable`, non-VAT templates only
- `1300 CPE and Network Inventory`
- `1500 Network Equipment and Facilities`
- `1590 Accumulated Depreciation - Network Equipment`
- `2400 Loans Payable`
- `3000 Owner's Capital` or `3000 Share Capital`
- `3100 Current Year Earnings` or `3100 Retained Earnings`

Gap to resolve:

- AP, inventory, fixed asset, depreciation, and loan modules do not exist yet.
  Slice 2 should allow manual opening lines now, then Slice 3 can add detailed
  schedules and subledgers.

## Double-Counting Rules

This is the most important Slice 2 risk.

Do not post both:

- historical invoice source drafts for pre-cutover sales
- opening AR balances for the same invoices

Recommended rule:

- pre-cutover source backfill stays in review/diagnostic mode
- opening balances become the official starting GL
- source posting becomes official only for documents dated after cutover

Implementation guard:

- when creating or posting source drafts, warn or block if source date is on or
  before the active cutover date and the cutover plan is live
- backfill command should default to review only for pre-cutover records
- opening import should list source documents represented by each subledger
  line where possible

## Cutover Readiness Checks

Minimum checks for Slice 2A:

- active accounting entity exists
- COA exists
- all periods covering cutover date exist
- opening balance import totals debit equals credit
- opening journal draft exists and is balanced
- no opening balance line has an inactive or missing account
- opening AR total is present if there are open invoices at cutover
- customer advances total is present if there are unallocated credits at cutover

Checks for Slice 2B and later:

- AR opening control equals subscriber AR schedule
- customer advances opening control equals customer credit schedule
- cash/bank/wallet lines have references
- AP control equals AP schedule
- CPE/inventory control equals inventory schedule
- fixed asset control equals fixed asset schedule
- accumulated depreciation has a matching contra-asset line
- tax receivable/payable balances have schedule references
- all blocked source postings after cutover are reviewed

## UI Plan

Routes:

- `/accounting/cutover/`
- `/accounting/cutover/setup/`
- `/accounting/cutover/imports/`
- `/accounting/cutover/imports/add/`
- `/accounting/cutover/imports/<id>/`
- `/accounting/cutover/imports/<id>/lines/`
- `/accounting/cutover/imports/<id>/validate/`
- `/accounting/cutover/imports/<id>/create-journal/`
- `/accounting/cutover/readiness/`

Pages:

- cutover dashboard
- cutover setup form
- opening balance import list
- opening balance line grid
- CSV upload result
- validation report
- generated opening journal link
- readiness checklist

## Service Plan

Functions:

- `get_active_cutover_plan(entity)`
- `create_cutover_plan(entity, cutover_date, prepared_by)`
- `snapshot_subscriber_ar(entity, cutover_date)`
- `snapshot_customer_advances(entity, cutover_date)`
- `validate_opening_balance_import(import_batch)`
- `create_opening_balance_journal(import_batch)`
- `build_cutover_readiness(entity)`
- `mark_cutover_ready(cutover_plan)`
- `mark_accounting_live(cutover_plan)`

Journal description:

```text
Opening balances as of YYYY-MM-DD
```

Journal source type:

```text
opening_balance
```

## Import Format

Initial CSV columns:

```text
account_code,line_type,debit,credit,subscriber_username,vendor_name,reference,description
```

Rules:

- debit and credit are decimal amounts
- only one side may be non-zero
- account code is required
- line type is required
- subscriber username is required for `subscriber_ar` and
  `customer_advance`
- vendor name is required for `ap_vendor`

## Test Plan

Model tests:

- only one active cutover plan per entity
- opening balance line requires exactly one debit or credit
- opening balance line account must belong to the same entity
- opening import totals compute correctly
- posted opening import cannot be edited

Service tests:

- balanced import creates one draft opening journal
- unbalanced import is blocked from journal creation
- generated journal lines match import lines
- AR snapshot includes open, partial, and overdue balances
- AR snapshot excludes paid, waived, and voided invoices
- customer advance snapshot equals unallocated credit calculation
- readiness fails without a balanced opening import
- readiness fails when AR schedule differs from AR opening line

UI tests:

- accounting admin can create cutover plan
- admin can add opening lines
- admin can validate import
- admin can create opening journal
- unauthorized user cannot manage cutover
- readiness page loads before and after setup

Regression tests:

- existing accounting dashboard still loads
- existing source review still loads
- post-cutover source posting remains draft-only
- Trial Balance excludes draft opening journal until posted
- Trial Balance includes posted opening journal

## Gaps Found Before Implementation

Resolved in Slice 2A:

- Opening balance models now exist.
- Cutover date/status exists in `CutoverPlan`.
- Manual opening balance batches can validate totals and generate draft opening
  journals.
- Readiness checks exist for the foundation, balanced import, draft opening
  journal, active accounts, and basic AR/credit presence.

Resolved in Slice 2B:

- Frozen subscriber AR and customer advance reconciliation snapshots now exist.
- Cutover readiness can detect missing or mismatched subscriber reconciliation.
- Paid-after-cutover invoices are not lost from opening AR snapshots.
- Customer advances use cutover as-of payment/allocation/adjustment dates
  instead of the live current account credit helper.

Remaining gaps:

- No account mapping table exists beyond service-level default posting codes.
- No formal frozen source-detail table exists for every invoice/payment row
  represented by the subscriber balance snapshot.
- No bank/wallet statement or settlement model exists yet.
- No AP, inventory, fixed asset, loan, or depreciation modules exist yet.
- VAT invoice tax breakdown is still blocked, so VAT cutover can only start
  with manual tax opening balances.
- 2307 attachments and finalized SAWT/2307 exports are not yet implemented.
- Source posting backfill now exists, but Slice 2 must prevent pre-cutover
  backfill from becoming duplicate official GL history after cutover is live.
- PostgreSQL test database creation is blocked in the current environment, so
  implementation verification still needs rollback smokes unless DB privileges
  are updated.

## Definition Of Done For Slice 2A

- cutover plan can be created for the active accounting entity
- opening balance import can be entered manually
- import totals show debit, credit, and difference
- unbalanced import cannot generate an opening journal
- balanced import generates a draft opening journal
- generated opening journal is source type `opening_balance`
- Trial Balance ignores the opening journal until posted
- readiness page shows clear pass/fail items
- docs identify remaining Slice 2B-2E work
- no existing billing/accounting pages break

Slice 2A completion note: this definition of done is implemented except CSV
upload parsing, which remains intentionally deferred to a later import-specific
slice because manual entry is enough for the first cutover foundation.
