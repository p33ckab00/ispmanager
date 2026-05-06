# Accounting v2 Slice 1C Billing and Payment Draft Posting

This document defines the next Accounting v2 implementation slice. Slice 1C
connects existing billing activity to the Accounting v2 ledger by creating
draft journal entries only. It must not auto-post to the official GL and must
not break existing billing, payment allocation, or legacy income/expense
behavior.

Compliance reference used for the EWT/CWT gap: BIR Form 2307 is the
Certificate of Creditable Tax Withheld at Source and captures payee, payor,
income payment, ATC, and tax withheld details for the covered period.

## Summary

Slice 1C adds source-driven draft journals for:

- invoices
- payments
- customer expanded withholding tax or creditable withholding tax claimed
  through BIR Form 2307
- customer advance application
- refund-due and refund-paid credit adjustments
- credit forfeiture
- invoice waivers and voids

The source journal workflow is:

1. Billing service creates or updates the business source document.
2. Accounting service creates or reuses a draft `JournalEntry`.
3. `SourceDocumentLink` records the source document and posting type.
4. Draft entries appear in an Accounting review queue.
5. Admin/accountant reviews and posts them manually.

Trial Balance and Accounting v2 reports continue to use posted journals only.

## Implementation Status

Slice 1C-A is the first implemented vertical of this plan. It includes:

- `AccountingSourcePosting` records for draft, posted, blocked, and skipped
  source posting review.
- `CustomerWithholdingTaxClaim` records for customer EWT/CWT and BIR Form 2307
  follow-up data.
- seeded COA support for `1210 Creditable Withholding Tax Receivable` and
  `2110 Refunds Payable`.
- non-VAT invoice draft posting:
  `Dr 1100 Accounts Receivable / Cr 4000 Internet Service Revenue`.
- payment draft posting for cash, bank, GCash, Maya, wallet/gateway clearing,
  AR settlement, customer advances, and CWT receivable.
- advance application draft posting only when a prior customer advance is later
  applied to an invoice; immediate allocations are marked skipped to avoid
  double posting.
- fail-soft billing hooks so invoices/payments still complete when Accounting
  v2 setup, period, or account mapping is missing.
- `/accounting/review/` source review queue and dashboard counts for source
  drafts and blocked source postings.

Slice 1C-B adds the operator workflow for customer EWT/CWT:

- payment recording can capture net cash received plus customer EWT/CWT claimed
  for BIR Form 2307.
- `CustomerWithholdingAllocation` links the withholding claim to the invoice
  balance it settled.
- invoice settlement can now be cash allocation plus EWT/CWT allocation while
  `Payment.amount` remains actual cash received.
- payment source draft journals use the withholding allocation amount for
  `Dr 1210 Creditable Withholding Tax Receivable`.
- `/accounting/withholding/2307/` lists pending, received, validated, and other
  customer 2307/CWT records for follow-up.

Remaining Slice 1C gaps after Slice 1C-B:

- VAT invoice posting is still blocked until invoice tax breakdown or explicit
  VAT posting settings are added.
- 2307 upload attachments and finalized SAWT/2307 export schedules are not yet
  implemented.
- refund-due, refund-paid, credit forfeiture, waiver, and void posting services
  are still pending.
- retry blocked source posting and backfill management commands are still
  pending.

## Current Source Model Facts

The current billing module has these source objects:

- `Invoice`: real receivable row, one per subscriber billing cycle.
- `Payment`: recorded collection with method, reference, paid date, and amount.
- `PaymentAllocation`: oldest-first application of a payment to an invoice.
- `AccountCreditAdjustment`: refund due, refund paid, and credit forfeiture.
- `BillingSnapshot`: client-facing billing statement, not the accounting source.
- `IncomeRecord`: legacy mirror created from payment recording.
- `ExpenseRecord`: legacy expense/refund helper.

Slice 1C must post from `Invoice`, `Payment`, `PaymentAllocation`, and
`AccountCreditAdjustment`. It must not post from `BillingSnapshot`.

Current gap: `Payment.amount` currently represents the recorded collection
amount and is mirrored to legacy `IncomeRecord`. It does not separately track
cash received versus tax withheld by a customer. Slice 1C must not overload
`Payment.amount` as gross settlement when a customer withholds EWT/CWT.

## Gap Review And Resolutions

### Gap: source idempotency is under-specified

Resolution:

- `SourceDocumentLink` must use a posting type as part of the source identity.
- Because the existing unique constraint does not include posting type, encode
  it in `source_model`.
- Use values such as:
  - `Invoice.invoice`
  - `Payment.collection`
  - `PaymentAllocation.advance_application`
  - `AccountCreditAdjustment.refund_due`
  - `AccountCreditAdjustment.refund_paid`
  - `AccountCreditAdjustment.credit_forfeit`
  - `Invoice.waiver`
  - `Invoice.void`
- Re-running a posting service returns the existing draft/posted journal instead
  of creating a duplicate.

### Gap: payment allocation can be immediate or later

Resolution:

- Payment draft posting records the full cash receipt.
- The payment journal credits AR for allocations known at payment-record time.
- The payment journal credits Customer Advances for the unallocated remainder.
- Later use of old unallocated credit against a new invoice creates a separate
  advance application draft:
  `Dr Customer Advances / Cr Accounts Receivable`.
- Slice 1C must avoid double-counting immediate allocations already represented
  in the payment journal.
- If legacy allocation timing is ambiguous, flag it in the review queue rather
  than guessing.

### Gap: customer EWT/CWT and BIR Form 2307 are not represented

Some customers, especially corporate or government customers that are
withholding agents, may pay the invoice net of expanded withholding tax and
issue BIR Form 2307, Certificate of Creditable Tax Withheld at Source. This is
not a discount, waiver, VAT reduction, or bad debt. It is a creditable income
tax withheld by the customer and should become an accounting asset supported by
the 2307 certificate.

Resolution:

- Add an accounting-owned `CustomerWithholdingTaxClaim` or
  `CreditableWithholdingTaxCertificate` model.
- Keep `Payment.amount` as actual cash/bank/wallet received.
- Add separate withholding amount and certificate details so gross AR
  settlement can equal:
  `cash received + EWT/CWT withheld`.
- Add allocation tracking for withholding claims, either through a dedicated
  `CustomerWithholdingAllocation` model or through a settlement service that
  links the withholding claim to invoices.
- Do not include pending or unverified 2307 amounts in SAWT/2307 compliance
  schedules as final certificates.
- Do track pending customer-claimed EWT separately so the operator can follow up
  for the actual 2307.
- EWT/CWT must not reduce output VAT. VAT, if applicable, remains based on the
  invoice tax treatment; the withholding is an income-tax credit asset.

Required fields for the withholding record:

- accounting entity
- subscriber/customer
- related payment, if the customer paid net cash
- related invoice or allocation lines
- income payment amount or gross invoice amount covered
- tax withheld amount
- withholding rate
- ATC, if known
- BIR Form 2307 period from/to
- payor/customer TIN
- payor/customer registered name
- payor/customer address
- certificate number or reference
- certificate date
- received date
- attachment/file reference, if uploaded
- status: `customer_claimed`, `pending_2307`, `received`, `validated`,
  `applied_to_return`, `disallowed`, `canceled`
- notes and validation warnings

Default account mapping:

- CWT/EWT receivable: add `1210 Creditable Withholding Tax Receivable` to the
  Accounting v2 COA templates and posting map.
- If the implementation needs a stricter control account, add a child account
  such as `1211 CWT Receivable - Pending 2307`.

Collection entry when 2307/EWT is claimed:

```text
Dr Cash/Bank/Wallet Clearing              net cash received
Dr 1210 Creditable Withholding Tax Receivable
Cr 1100 Accounts Receivable - Subscribers gross AR settled
```

If the customer claims EWT but the 2307 is not yet received:

- create the draft journal only if the operator explicitly records the pending
  claim
- status the withholding record as `pending_2307`
- show it in the review queue and 2307 follow-up list
- exclude it from finalized SAWT/2307 received schedules until received or
  validated

If the customer short-pays and no EWT claim is recorded:

- leave the invoice partially unpaid
- do not silently create CWT receivable

### Gap: VAT cannot be computed reliably from current invoices

Current `Invoice` stores a gross amount and does not store tax code, VATable
base, VAT amount, or exemption state.

Resolution:

- Slice 1C may post non-VAT invoices immediately using the seeded accounts.
- VAT entities need one of these before VAT splitting is enabled:
  - minimal `TaxCode` and invoice tax breakdown, or
  - explicit accounting posting setting that declares VAT-inclusive treatment
    and rate.
- Until that exists, VAT invoice draft posting must create an unmapped or
  blocked review item instead of silently guessing Output VAT.
- The document plan keeps the target VAT entry:
  `Dr Accounts Receivable / Cr Internet Service Revenue / Cr Output VAT`,
  but implementation must not invent VAT amounts from gross invoices without a
  configured rule.

### Gap: account mapping is hard-coded only by COA template

Resolution:

- Add an accounting-owned posting map in Slice 1C or use a service-level default
  map backed by seeded account codes.
- Required defaults:
  - AR: `1100 Accounts Receivable - Subscribers`
  - Cash: `1000 Cash on Hand`
  - Bank: `1010 Bank Accounts`
  - Wallet/gateway clearing: `1020 E-Wallet and Gateway Clearing`
  - Creditable Withholding Tax Receivable: add `1210 Creditable Withholding Tax
    Receivable`
  - Customer Advances: `2100 Customer Advances`
  - Subscriber Deposits: `2200 Subscriber Deposits`
  - Internet Revenue: `4000 Internet Service Revenue`
  - Installation Revenue: `4010 Installation and Activation Revenue`
  - Output VAT: `2300 Output VAT`
  - Refunds Payable: add `2110 Refunds Payable` or use `2000 Accounts Payable`
    as a temporary fallback
  - Waivers/Bad Debts: `6050 Bad Debts and Subscriber Waivers`
  - Other Income: `7000 Other Income`
- Missing mapped accounts must block draft creation with a reviewable error.

### Gap: invoice waiver and void behavior is different

Resolution:

- Waiver means the receivable remains a real bill but collection is forgiven.
  Draft entry:
  `Dr Bad Debts and Subscriber Waivers / Cr Accounts Receivable`
  for the remaining invoice balance.
- Void means the source invoice should no longer be treated as collectible.
  Draft entry depends on whether revenue was already posted:
  - if source invoice draft is still draft, link the void review item to the
    original draft and recommend voiding the draft
  - if source invoice is posted, create reversal/adjustment draft
    `Dr Internet Service Revenue / Cr Accounts Receivable`
    plus VAT reversal when VAT is supported
- Existing bulk waiver/void services must collect affected invoices before
  updating them so one source journal can be created per invoice or per batch
  with source links to each invoice.

### Gap: refund lifecycle needs two steps

Resolution:

- `refund_due` reserves customer credit for refund:
  `Dr Customer Advances / Cr Refunds Payable`.
- `refund_paid` pays the refund:
  `Dr Refunds Payable / Cr Cash/Bank/Wallet Clearing`.
- Existing optional legacy `ExpenseRecord` for refunds remains legacy only and
  must not be used by Accounting v2 Trial Balance.
- If `Refunds Payable` is not available, use AP fallback only with a review flag.

### Gap: credit forfeiture has no posting rule

Resolution:

- Credit forfeiture reduces customer advance liability and recognizes income:
  `Dr Customer Advances / Cr Other Income`.
- It must be source-linked to `AccountCreditAdjustment.credit_forfeit`.

### Gap: missing accounting setup could break billing

Resolution:

- Slice 1C must be fail-soft while Accounting v2 is not live.
- If there is no active `AccountingEntity`, no open period, or missing account
  map, billing must still complete.
- The posting service should return a skipped/blocked result and surface it in
  diagnostics or review UI.
- Later, a stricter setting can block billing when Accounting v2 is marked live.

### Gap: posting dates and periods are not explicit

Resolution:

- Invoice draft date: `invoice.created_at.date()`.
- Payment draft date: `payment.paid_at.date()`.
- Advance application date: `PaymentAllocation.created_at.date()`.
- Credit adjustment date: `AccountCreditAdjustment.effective_at.date()`.
- If no accounting period exists for the date, create a blocked review item and
  do not create an incomplete journal.

### Gap: legacy `IncomeRecord` can cause double-count concerns

Resolution:

- Keep `IncomeRecord` mirroring unchanged for legacy pages.
- Accounting v2 reports must query only posted `JournalEntry` and `JournalLine`.
- Slice 1C review UI should label source drafts as Accounting v2 drafts, not as
  legacy income.

## Posting Rules

### Invoice

Source: `Invoice`

Non-VAT entry:

```text
Dr 1100 Accounts Receivable - Subscribers
Cr 4000 Internet Service Revenue
```

VAT target entry when tax breakdown is available:

```text
Dr 1100 Accounts Receivable - Subscribers
Cr 4000 Internet Service Revenue
Cr 2300 Output VAT
```

Amount basis:

- use `Invoice.amount`
- do not reduce invoice amount by payments or credits
- payment and advance application entries handle settlement separately

### Payment

Source: `Payment`

Payment without EWT/CWT:

For allocated portion:

```text
Dr Cash/Bank/Wallet Clearing
Cr 1100 Accounts Receivable - Subscribers
```

For unallocated portion:

```text
Dr Cash/Bank/Wallet Clearing
Cr 2100 Customer Advances
```

Cash-side account mapping by method:

- `cash` -> `1000 Cash on Hand`
- `bank` -> `1010 Bank Accounts`
- `gcash` -> `1020 E-Wallet and Gateway Clearing`
- `maya` -> `1020 E-Wallet and Gateway Clearing`
- `other` -> `1020 E-Wallet and Gateway Clearing` unless configured otherwise

### Payment With Customer EWT/CWT Claim

Sources:

- `Payment`
- `CustomerWithholdingTaxClaim` or
  `CreditableWithholdingTaxCertificate`

For an invoice where the customer pays net cash and withholds EWT:

```text
Dr Cash/Bank/Wallet Clearing
Dr 1210 Creditable Withholding Tax Receivable
Cr 1100 Accounts Receivable - Subscribers
```

The credit to AR is the gross amount settled. The cash debit is the net amount
received. The CWT debit is the tax withheld supported by, or pending receipt of,
BIR Form 2307.

Do not post EWT as:

- sales discount
- waiver
- bad debt
- output VAT reduction
- negative revenue

If EWT exceeds the open AR being settled, block the source posting for review.
If EWT is claimed on an invoice whose revenue draft is missing or blocked, allow
the collection draft only if AR exists from opening balances or a posted invoice
journal; otherwise block for review.

### Advance Application

Source: `PaymentAllocation`

Used only when a prior customer advance is applied to an invoice after the
payment was originally treated as unallocated.

```text
Dr 2100 Customer Advances
Cr 1100 Accounts Receivable - Subscribers
```

### Refund Due

Source: `AccountCreditAdjustment` with `adjustment_type='refund_due'`.

```text
Dr 2100 Customer Advances
Cr 2110 Refunds Payable
```

### Refund Paid

Source: `AccountCreditAdjustment` with `adjustment_type='refund_paid'`.

```text
Dr 2110 Refunds Payable
Cr Cash/Bank/Wallet Clearing
```

### Credit Forfeiture

Source: `AccountCreditAdjustment` with `adjustment_type='forfeit'`.

```text
Dr 2100 Customer Advances
Cr 7000 Other Income
```

### Waiver

Source: `Invoice` with `status='waived'`.

```text
Dr 6050 Bad Debts and Subscriber Waivers
Cr 1100 Accounts Receivable - Subscribers
```

Use remaining invoice balance, not original invoice amount.

### Void

Source: `Invoice` with `status='voided'`.

If original invoice journal is still draft:

- do not create a financial adjustment draft
- flag original draft for voiding/review

If original invoice journal is posted:

```text
Dr 4000 Internet Service Revenue
Cr 1100 Accounts Receivable - Subscribers
```

VAT reversal waits for tax breakdown support.

## Implementation Plan

1. Add accounting posting service functions under `apps/accounting/services.py`
   or a new `apps/accounting/posting.py`.
2. Add source-link helpers:
   - find existing source journal
   - create source draft
   - mark blocked source posting
3. Add account mapping helper with seeded default account codes.
4. Add CWT/EWT receivable account to the seeded COA templates or create it
   idempotently during Slice 1C setup/backfill.
5. Add customer withholding tax claim/certificate model and allocation support.
6. Add payment form/service support for net cash plus EWT/CWT claimed.
7. Add draft posting service for `Invoice`.
8. Add draft posting service for `Payment`.
9. Add draft posting service for payment with EWT/CWT claim.
10. Add advance application service for later `PaymentAllocation`.
11. Add credit adjustment posting for refund due, refund paid, and forfeiture.
12. Refactor waiver/void service paths to capture affected invoices and create
   reviewable source drafts.
13. Add Accounting review queue:
   - source type
   - source number
   - subscriber
   - date
   - amount
   - status
   - blocked reason
   - linked journal
14. Add dashboard count for source drafts and blocked postings.
15. Add 2307/CWT follow-up and received-certificate schedule.
16. Add management command to backfill draft source journals for recent billing
    data without posting them.

## UI Plan

Add:

- `/accounting/review/`
- `/accounting/withholding/2307/`
- filter by source type, status, blocked reason, and period
- links to source invoice/payment/refund where available
- links to customer 2307/CWT records where available
- link to draft journal detail
- button to retry blocked source posting after setup/mapping is fixed

Existing journal detail remains the posting screen for balanced drafts.

## Tests

### Invoice tests

- invoice creates one draft source journal
- rerunning invoice posting reuses the existing source journal
- non-VAT invoice posts AR and revenue
- VAT entity without tax breakdown creates blocked review result
- missing AR or revenue mapping blocks draft creation
- invoice draft does not appear in Trial Balance until posted

### Payment tests

- full payment against open invoice creates cash debit and AR credit
- partial payment creates cash debit and AR credit for paid amount
- overpayment splits AR credit and Customer Advances credit
- GCash and Maya use wallet clearing account
- rerunning payment posting is idempotent
- legacy `IncomeRecord` mirror still exists and is not included in Trial Balance

### EWT/CWT and 2307 tests

- customer can record net cash received plus EWT/CWT withheld
- `Payment.amount` remains the actual cash received
- gross AR settlement equals cash received plus withholding claim
- draft journal debits cash and CWT receivable, then credits AR
- pending 2307 is listed in the follow-up schedule
- received/validated 2307 is included in the 2307 received schedule
- pending 2307 is excluded from finalized SAWT/2307 compliance exports
- EWT does not reduce output VAT or revenue
- EWT greater than open AR blocks source posting
- missing CWT receivable account blocks source posting

### Advance application tests

- early payment creates Customer Advances credit
- later invoice allocation creates Customer Advances debit and AR credit
- immediate allocations are not double-posted as advance applications

### Credit adjustment tests

- refund due creates Customer Advances debit and Refunds Payable/AP credit
- refund paid creates Refunds Payable/AP debit and cash/bank/wallet credit
- credit forfeiture creates Customer Advances debit and Other Income credit

### Waiver and void tests

- waived open invoice creates waiver expense and AR credit for remaining balance
- voided invoice with draft source journal is flagged for review
- voided invoice with posted source journal creates revenue reversal draft

### Review and failure tests

- no active Accounting v2 entity does not break billing
- missing period creates blocked source posting
- missing mapped account creates blocked source posting
- review queue lists blocked and draft source postings
- source-created drafts remain editable only while draft
- posted source journals cannot be edited

## Explicit Exclusions

Slice 1C does not include:

- automatic posting to official GL
- CAS/CBA/EIS mode
- official BIR invoice generation
- BIR loose-leaf books
- NTC report packs
- complete VAT implementation without tax breakdown
- finalized SAWT generation beyond a received/validated 2307 schedule
- bank settlement reconciliation
- opening balance import

## Definition Of Done

Slice 1C is complete when:

- billing and payment events can create or reuse draft journals
- customer EWT/CWT claims can settle AR as CWT receivable with 2307 tracking
- source posting is idempotent
- Accounting review queue shows draft and blocked source postings
- billing does not fail when Accounting v2 setup is incomplete
- Trial Balance includes source journals only after posting
- legacy income/expense pages still load
- documentation reflects any implementation deviations

## Reference Links

- BIR Form 2307 PDF:
  `https://bir-cdn.bir.gov.ph/local/pdf/2307%20Jan%202018%20ENCS%20v3.pdf`
