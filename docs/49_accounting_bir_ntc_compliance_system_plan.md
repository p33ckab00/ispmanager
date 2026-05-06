# Accounting, BIR, and NTC Compliance System Plan

This document records the full accounting compliance direction discussed for
ISP Manager. It is intended as the starting point for building Accounting v2:
a Philippine ISP-focused double-entry accounting subsystem that supports BIR
books, BIR tax form encoding guides, NTC report packs, financial statements,
and future multi-tenant production use.

## 1. Conversation Summary

The accounting module must move beyond the current income and expense tracker.
The goal is a real accounting system that helps an ISP operator comply with
Philippine BIR and NTC requirements while also making day-to-day operations
easier.

The desired result is not automatic electronic filing into BIR or NTC systems.
Instead, ISP Manager should generate:

- ready-to-print loose-leaf books and supporting schedules
- Excel or CSV schedules for accounting review
- PDF report packs for filing, printing, or attachment
- eBIRForms entry guides showing which amounts go into which fields
- NTC quarterly and annual report packs based on operational and finance data

The system should be production-minded from the beginning, with a clean path to
multi-tenant operation later. For now, the UI can support one company/operator,
but the accounting data model should be shaped so that each accounting record
can eventually belong to a company, tenant, or accounting entity.

## 2. Current System Context

The current codebase already has strong billing foundations:

- `Invoice` is treated as the real receivable ledger row.
- `BillingSnapshot` is the frozen customer-facing statement.
- `Payment` and `PaymentAllocation` track collections and oldest-first payment
  application.
- Payments are mirrored into `IncomeRecord`.
- Accounting currently supports income, expenses, monthly P&L, and CSV export.

This is useful, but it is not yet a double-entry accounting system. The next
accounting version should keep the billing module as the source of subscriber
bills and collections, then post those source documents into a formal general
ledger.

## 3. Product Goal

Build an ISP-focused accounting and compliance subsystem that can:

1. Record all financial activity using double-entry accounting.
2. Generate financial statements from the general ledger.
3. Produce BIR loose-leaf books and supporting schedules.
4. Produce eBIRForms entry guides for applicable tax forms.
5. Produce NTC compliance report packs from finance and operations data.
6. Keep accounting settings inside the Accounting module.
7. Support future multi-tenant deployment without redesigning the ledger.

## 4. Important Scope Boundary

### BIR tax forms

BIR forms should not be treated as "ready-made auto-submit forms" inside the
system. For forms such as 2550Q, 2551Q, 1701Q, 1701, 1702Q, or 1702 series,
ISP Manager should generate an encoding guide:

- form name and version
- return period
- item or line number
- computed amount
- source schedule
- drill-down transactions
- validation warnings
- printable worksheet for the accountant or operator

The user still files through the official BIR channel such as eBIRForms, eFPS,
or the process required by the taxpayer's registration.

### BIR loose-leaf books

Loose-leaf books and schedules are the reports that can be made ready for
printing or export:

- PDF print set
- Excel workbook
- CSV export where useful
- cover page per book
- page numbering
- taxpayer details
- period covered
- prepared by and reviewed by fields
- affidavit helper information such as number of pages or books used

The system should support loose-leaf workflows, but the operator must still
secure and maintain the proper BIR authority or registration for loose-leaf or
computerized books where required.

### NTC reports

NTC reports should be generated as ready-to-submit report packs, but final
submission still follows the NTC's required channel, office, portal, email, or
format. ISP Manager should generate the operational and financial schedules
that are difficult to prepare manually.

## 5. Accounting Module Boundary

Accounting must become its own subsystem. It should not store its core settings
under the general Settings module. General settings should remain for platform
behavior such as billing cutoff, SMS, Telegram, router polling, subscriber
portal security, and automation.

Accounting should own:

- taxpayer profile
- accounting periods
- fiscal year
- chart of accounts
- tax setup
- BIR document series
- book of accounts configuration
- BIR report mappings
- NTC report mappings
- financial statement settings
- posting rules
- period locks
- accountant and preparer details

Accounting rules affect compliance, financial statements, tax computations, and
auditable records. They should be protected by accounting permissions and period
locking rules.

## 6. Proposed Accounting Menu

```text
Accounting
  Dashboard
  Chart of Accounts
  Journal Entries
  Receivables
  Payables
  Fixed Assets
  Taxes
  Books of Accounts
  Financial Statements
  BIR Compliance
  NTC Compliance
  Accounting Settings
  Period Closing
```

## 7. Accounting Settings

The Accounting Settings area should include these sections.

### Company and taxpayer profile

- registered name
- trade name
- entity type: sole proprietor, corporation, partnership, cooperative, other
- TIN
- branch code
- RDO code
- registered address
- line of business
- calendar year or fiscal year
- tax filer type
- accredited tax agent or accountant details, if any

### Tax settings

- VAT registered or non-VAT
- percentage tax applicable or not
- income tax type
- individual 8 percent option if applicable
- graduated or regular income tax treatment
- withholding tax setup
- input VAT tracking
- output VAT tracking
- creditable withholding tax tracking
- default tax codes

### Book of accounts settings

- book type: manual, loose-leaf, computerized books, CAS/CBA
- permit to use or acknowledgement certificate details
- book registration details
- loose-leaf print format
- page numbering format
- prepared by and reviewed by signatories
- year-end binding/export rules

### BIR document series

- invoice type: VAT Invoice, Non-VAT Invoice, Billing Invoice, Service Invoice
- ATP/PTU/permit details where applicable
- invoice prefix and starting number
- collection receipt or payment receipt series, if used as supplementary proof
- void and cancellation policy
- branch-specific series support

### Posting rules

- default accounts for subscriber receivables
- default accounts for revenue by service type
- default cash, bank, GCash, Maya, and payment gateway accounts
- default output VAT and input VAT accounts
- default discount, waiver, bad debt, refund, and customer advance accounts
- default expense mapping
- default CPE, inventory, and fixed asset mapping

### NTC profile

- permit or registration type: VAS, ISP, PTE/CPCN, CATV, or other
- authorized service areas
- registered services
- facilities or network lease providers
- report period settings
- service category mappings
- subscriber count grouping rules
- revenue by service type rules

## 8. ISP-Focused Chart of Accounts

The sample chart of accounts provided during discussion looked like a generic
corporate chart. It is too broad in areas that do not matter to a small or
medium ISP, and it misses ISP-specific ledgers.

The system should provide ISP-specific templates:

1. ISP - Non-VAT Sole Proprietor
2. ISP - VAT Sole Proprietor
3. ISP - Non-VAT Corporation
4. ISP - VAT Corporation

The operator or accountant can customize accounts later, but the default should
already support ISP billing, network costs, network assets, BIR reporting, and
NTC reporting.

### Account numbering pattern

```text
10000 Assets
20000 Liabilities
30000 Equity
40000 Revenue
50000 Direct Network Costs
60000 Operating Expenses
70000 Other Income and Expenses
80000 Income Tax and Closing Accounts
```

### Assets

```text
10000 Assets
  10100 Cash on Hand
  10200 Bank Accounts
  10300 GCash Clearing
  10400 Maya Clearing
  10500 Payment Gateway Clearing
  11000 Accounts Receivable - Subscribers
  11100 Accounts Receivable - Installation and Activation
  11200 Allowance for Doubtful Accounts
  12000 Input VAT
  12100 Creditable Withholding Tax Receivable
  13000 Inventory - ONU, Modem, Router, and CPE
  13100 Inventory - Fiber Cable, Drop Wire, Connectors, and Materials
  13200 Inventory - Spares and Network Supplies
  14000 Prepaid Expenses
  14100 Prepaid NTC or Permit Fees
  15000 Network Property and Equipment
    15100 Fiber Backbone
    15200 OLT and Core Network Equipment
    15300 Routers and Switches
    15400 ONU and CPE Issued to Subscribers
    15500 Poles, Towers, Cabinets, NAP Boxes
    15600 Batteries, UPS, Solar, and Generator Equipment
    15700 Construction in Progress - Network Build
  15900 Accumulated Depreciation - Network Assets
```

### Liabilities

```text
20000 Liabilities
  20100 Accounts Payable - Suppliers
  20200 Accrued Expenses
  20300 Subscriber Deposits
  20400 Customer Advances and Prepaid Internet Credits
  20500 Output VAT Payable
  20600 VAT Payable or Input VAT Adjustments
  20700 Expanded Withholding Tax Payable
  20800 Compensation Withholding Tax Payable
  20900 SSS, PhilHealth, and Pag-IBIG Payable
  21000 Loans Payable
  21100 NTC Fees and Regulatory Payables
  21200 Unearned Revenue
```

### Equity

```text
30000 Equity
  30100 Paid-up Capital
  30200 Additional Paid-in Capital
  30300 Retained Earnings
  30400 Current Year Income
  30500 Dividends or Owner Withdrawals
```

### Revenue

```text
40000 Revenue
  40100 Residential Internet Revenue
  40200 Business Internet Revenue
  40300 Dedicated or Enterprise Internet Revenue
  40400 Installation and Activation Fee Revenue
  40500 Reconnection Fee Revenue
  40600 Equipment Rental Revenue
  40700 Static IP and Add-on Service Revenue
  40800 Managed Router or Managed WiFi Revenue
  40900 Penalty or Late Payment Fee Revenue
  41000 Discounts, Service Credits, and Waivers
```

### Direct network costs

```text
50000 Direct Network Costs
  50100 Upstream Bandwidth or IP Transit
  50200 Backhaul, Leased Fiber, and Transport
  50300 Pole Rental and Attachment Fees
  50400 POP, Tower, Cabinet, or Site Rental
  50500 Network Power and Generator Fuel
  50600 Network Repairs and Maintenance
  50700 Fiber Materials Used
  50800 CPE or ONU Issued Expense
  50900 Contractor Installation Labor
  51000 NOC or Field Technician Direct Labor
```

### Operating expenses

```text
60000 Operating Expenses
  60100 Salaries - Admin, Billing, and CSR
  60200 Office Rent
  60300 Office Utilities
  60400 Software Subscriptions
  60500 SMS and Notification Costs
  60600 Payment Gateway Fees
  60700 Bank Charges
  60800 Accounting, Legal, and Professional Fees
  60900 Permits and Licenses
  61000 NTC and Regulatory Fees
  61100 Marketing and Advertising
  61200 Transportation, Fuel, and Field Travel
  61300 Office Supplies
  61400 Bad Debts Expense
  61500 Depreciation Expense - Network Assets
  61600 Training and Certifications
  61700 Repairs and Maintenance - Office Equipment
```

### Other income and expenses

```text
70000 Other Income and Expenses
  70100 Interest Income
  70200 Gain on Sale of Equipment
  70300 Interest Expense
  70400 Penalties and Surcharges
  70500 Loss on Asset Disposal
```

## 9. Dimensions and Subledgers

The chart of accounts should not create one account per subscriber, barangay,
router, payment method, or package. That would make the general ledger hard to
maintain.

Use the chart of accounts for financial categories. Use dimensions and
subledgers for operational reporting.

Recommended dimensions:

- area or barangay
- POP or site
- router
- service type
- plan or package
- customer type: residential, business, enterprise
- payment channel
- tax code
- NTC service category

Recommended subledgers:

- subscriber AR ledger
- vendor AP ledger
- fixed asset register
- CPE/ONU inventory ledger
- customer advance and deposit ledger
- VAT input and output tax ledger

Example:

```text
Account: 40100 Residential Internet Revenue
Area: San Jose
POP: OLT-01
Plan: Fiber 50 Mbps
Tax Code: VATable
NTC Service: Internet Access
```

## 10. Core Posting Rules

Accounting should post from source documents, not from manual duplicated data.

### Invoice issued

For VAT:

```text
Dr Accounts Receivable - Subscribers
Cr Internet Service Revenue
Cr Output VAT Payable
```

For non-VAT:

```text
Dr Accounts Receivable - Subscribers
Cr Internet Service Revenue
```

### Payment received

```text
Dr Cash, Bank, GCash, Maya, or Payment Gateway Clearing
Cr Accounts Receivable - Subscribers
```

If payment is received before an invoice exists:

```text
Dr Cash, Bank, GCash, Maya, or Payment Gateway Clearing
Cr Customer Advances and Prepaid Internet Credits
```

When later applied to an invoice:

```text
Dr Customer Advances and Prepaid Internet Credits
Cr Accounts Receivable - Subscribers
```

### Expense recorded

For VAT purchase:

```text
Dr Expense or Asset
Dr Input VAT
Cr Cash, Bank, or Accounts Payable
```

For non-VAT purchase:

```text
Dr Expense or Asset
Cr Cash, Bank, or Accounts Payable
```

### CPE or network inventory purchased

```text
Dr Inventory - ONU, Modem, Router, and CPE
Dr Input VAT, if VAT
Cr Cash, Bank, or Accounts Payable
```

### CPE issued to subscriber as consumed cost

```text
Dr CPE or ONU Issued Expense
Cr Inventory - ONU, Modem, Router, and CPE
```

### Network asset capitalization

```text
Dr Network Property and Equipment
Dr Input VAT, if VAT
Cr Cash, Bank, Accounts Payable, or Construction in Progress
```

### Depreciation

```text
Dr Depreciation Expense - Network Assets
Cr Accumulated Depreciation - Network Assets
```

### Waiver or service credit

```text
Dr Discounts, Service Credits, and Waivers
Cr Accounts Receivable - Subscribers
```

### Bad debt write-off

```text
Dr Bad Debts Expense
Cr Accounts Receivable - Subscribers
```

### Refund of customer credit

```text
Dr Customer Advances and Prepaid Internet Credits
Cr Cash or Bank
```

## 11. Financial Statement Reports

The accounting system must produce financial statements, not only books and tax
schedules.

Core reports:

- Statement of Financial Position or Balance Sheet
- Statement of Comprehensive Income or Profit and Loss
- Statement of Cash Flows
- Statement of Changes in Equity
- Trial Balance
- General Ledger
- Notes and supporting schedules

ISP-specific financial schedules:

- AR Aging - Subscribers
- Subscriber Deposits Schedule
- Customer Advances or Prepaid Credits Schedule
- Revenue by Service Type
- Revenue by Area, POP, or Barangay
- Bandwidth and Backhaul Cost Schedule
- Network Asset Register
- Depreciation Schedule
- CPE/ONU Inventory and Issued Equipment Schedule
- NTC Fees and Regulatory Fees Schedule
- VAT Output/Input Schedule
- Withholding Tax Schedule
- Bad Debts, Waivers, and Write-off Schedule

The intended flow is:

```text
Transactions
-> Journal Entries
-> General Ledger
-> Trial Balance
-> Financial Statements
-> BIR and NTC Compliance Reports
```

## 12. BIR Compliance Outputs

### Loose-leaf books and accounting records

The system should generate:

- General Journal
- General Ledger
- Cash Receipts Book
- Cash Disbursements Book
- Sales Journal
- Purchase or Expense Journal
- Sales Invoice Register
- Collection Register
- AR Subsidiary Ledger per subscriber
- AP or Vendor Ledger
- VAT Output Tax Ledger
- VAT Input Tax Ledger
- Fixed Asset Register
- Inventory Ledger for CPE and network materials

### eBIRForms entry guides

The system should generate encoding guides for applicable forms based on the
taxpayer profile. Examples:

- 2550Q Quarterly VAT Return
- 2551Q Quarterly Percentage Tax Return
- 1701Q Quarterly Income Tax Return for individuals, estates, and trusts
- 1701 or 1701A Annual Income Tax Return for individuals where applicable
- 1702Q Quarterly Income Tax Return for corporations and partnerships
- 1702-RT, 1702-EX, or 1702-MX annual corporate income tax forms where applicable
- withholding forms if enabled by the taxpayer profile

The guide should show:

```text
Form: 2550Q April 2024
Period: Q2 2026
Item: Output VAT on VATable Sales
Amount: PHP 0.00
Source: VAT Output Tax Ledger
Drilldown: linked invoices and adjustments
```

The exact line mapping should be versioned because BIR forms can change.

### BIR report pack

For each period, generate:

- PDF book pack
- Excel book pack
- tax form entry guide
- source schedules
- exception report
- period close checklist

## 13. NTC Compliance Outputs

The NTC side needs both finance and operations data. ISP Manager already has
subscriber, billing, network, and NMS data that can support these reports.

Recommended NTC reports:

- Quarterly VAS Provider Report
- Annual Report of Finances and Operations
- subscriber count by area, status, and service type
- revenue by service category
- network facilities and infrastructure summary
- facilities or network lease schedule
- service area and coverage report
- QoS, availability, and outage summary
- complaints and resolution summary
- incident report summary
- NTC fees and regulatory payment schedule

The NTC pack should export to:

- PDF
- Excel
- CSV where useful

## 14. Multi-Tenant Direction

Even if the current deployment is single-operator, the accounting data model
should be tenant-ready.

Recommended parent entity:

```text
AccountingEntity
```

Every core accounting record should belong to this entity:

- AccountingSettings
- TaxProfile
- ChartOfAccount
- JournalEntry
- JournalLine
- AccountingPeriod
- DocumentSeries
- TaxCode
- BookReportRun
- FinancialReportRun
- ComplianceExport
- FixedAsset
- Vendor
- AccountingDimension

The first UI can hide multi-company support and create only one entity. The
database should not assume global singleton accounting data.

## 15. Candidate Data Models

Initial models to consider:

```text
AccountingEntity
AccountingSettings
AccountingPeriod
ChartOfAccount
AccountingDimension
TaxCode
DocumentSeries
JournalEntry
JournalLine
SourceDocumentLink
Vendor
Payable
FixedAsset
DepreciationRun
BookReportRun
FinancialReportRun
ComplianceExport
BirFormGuideRun
NtcReportRun
```

Important fields:

- posted, draft, reversed, voided states
- source module and source document ID
- accounting date
- tax date
- period
- debit amount
- credit amount
- dimensions
- prepared by
- reviewed by
- locked period behavior
- tenant/accounting entity

## 16. Implementation Phases

### Phase 1 - Accounting foundation

- add AccountingEntity and accounting-owned settings
- add accounting periods
- add chart of accounts
- add journal entry and journal line models
- add basic posting and balancing validation
- add permissions and audit logging

### Phase 2 - ISP chart templates

- seed ISP Non-VAT Sole Proprietor template
- seed ISP VAT Sole Proprietor template
- seed ISP Non-VAT Corporation template
- seed ISP VAT Corporation template
- add setup wizard to select template
- map existing billing and payment events to default accounts

### Phase 3 - Billing to ledger posting

- invoice posting
- payment posting
- advance payment posting
- allocation posting
- waiver and bad debt posting
- refund posting
- diagnostics for unposted source documents

### Phase 4 - Expenses, vendors, inventory, and assets

- vendor capture
- AP and expense posting
- input VAT tracking
- CPE and materials inventory posting
- fixed asset register
- depreciation schedules

### Phase 5 - Financial statements

- trial balance
- general ledger
- balance sheet
- income statement
- cash flow statement
- changes in equity
- supporting schedules

### Phase 6 - BIR books and form guides

- loose-leaf book exports
- sales invoice register
- VAT schedules
- percentage tax schedules
- income tax worksheets
- eBIRForms guide mapping
- PDF and Excel report packs

### Phase 7 - NTC report packs

- NTC profile settings
- service area mapping
- subscriber count schedules
- revenue by service type
- network/facilities schedule
- QoS and incident summaries
- quarterly and annual report packs

### Phase 8 - Period closing and production hardening

- period locks
- reversal-only corrections after close
- accountant review workflow
- report run snapshots
- export archive
- multi-tenant hardening
- compliance diagnostics

## 17. Acceptance Criteria

Accounting v2 is considered usable when:

- every posted journal entry balances
- billing invoices can create journal entries
- payments can create journal entries
- expenses can create journal entries
- trial balance can be generated for a period
- balance sheet and income statement can be generated from ledger data
- loose-leaf books can be exported to PDF and Excel
- eBIRForms guide entries can be generated from mapped schedules
- NTC report pack can be generated from finance and operations data
- accounting settings are inside Accounting, not General Settings
- periods can be locked
- corrections after lock use reversals or adjustments
- source document drilldown is available from reports
- existing income/expense records can be migrated or bridged safely

## 18. Open Inputs Needed Before Build

The operator or accountant should eventually provide:

- BIR Certificate of Registration details
- entity type
- VAT or non-VAT status
- tax types registered in COR
- TIN, branch code, and RDO
- invoice and document series details
- loose-leaf, manual, or computerized books setup
- current COA if already approved by accountant
- NTC permit type
- service areas
- required NTC report templates from the regional office, if available
- preferred financial statement layout

The system should still provide defaults so the operator is not blocked while
waiting for the accountant.

## 19. Official Reference Points Checked

The discussion was shaped using official BIR and NTC reference points available
at the time of documentation:

- BIR RR 7-2024: invoicing requirements under the Ease of Paying Taxes Act
  https://bir-cdn.bir.gov.ph/BIR/pdf/RR%207-2024%20%28final%29.pdf
- BIR RMC 77-2024: clarification of invoicing requirements
  https://bir-cdn.bir.gov.ph/BIR/pdf/RMC%20No.%2077-2024%20Digest.pdf
- BIR Form 2550Q April 2024 and related guidance
  https://bir-cdn.bir.gov.ph/BIR/pdf/2550Q%20%20April%202024%20ENCS_Final.pdf
  https://bir-cdn.bir.gov.ph/BIR/pdf/2550Q%20guidelines%20April%202024_final.pdf
- BIR Form 2551Q guidance
  https://efps.bir.gov.ph/efps-war/EFPSWeb_war/forms2018Version/2551Q/2551q_guidelines.html
- BIR loose-leaf and computerized books references, including RMC 65-2025 and
  RMC 4-2026 digest references
  https://bir-cdn.bir.gov.ph/BIR/pdf/RMC%20No.%2065-2025%20Digest.pdf
  https://bir-cdn.bir.gov.ph/BIR/pdf/RMC%20No.%204-2026%20Digest.pdf
- NTC annual reports memorandum circular reference
  https://ntc5.ntc.gov.ph/wp-content/uploads/2019/09/MC-04-10-2006-Submission-of-Annual-Report.pdf
- NTC VAS renewal checklist reference mentioning quarterly VAS provider reports
  https://region1.ntc.gov.ph/wp-content/uploads/2020/07/NTC-CCT-2019-FIRST-EDITION-UPDATED-JULY-2020-REGIONAL-OFFICE-FINAL.pdf

These references should be rechecked before implementation of exact form-field
mappings because BIR and NTC requirements can change.
