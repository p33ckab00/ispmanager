# Accounting v2 Slice 3 Financial Statements Plan

## Summary

Slice 3 starts the financial statement layer on top of the posted Accounting v2
ledger. Slice 3A delivered the core accountant-facing reports. Slice 3B adds
basic export and print ergonomics while still avoiding BIR/NTC claims,
immutable filing packages, and full subledger engines.
Slice 3C-A adds the two remaining ledger-derived statements that can be built
without vendor/subscriber aging subledgers.
Slice 3C-B adds operational aging and tax workpapers tied back to GL control
accounts where the current data model allows it.
Slice 3D-A adds accountant-facing report ergonomics for repeat review runs.

## Slice 3A Implemented

Implemented:

- Shared report service functions for posted journal lines only.
- Trial Balance report now uses shared service math instead of view-local
  calculations.
- General Ledger page at `/accounting/general-ledger/`.
- Income Statement page at `/accounting/income-statement/`.
- Balance Sheet page at `/accounting/balance-sheet/`.
- Accounting dashboard links for the new statement pages.
- General Ledger supports date range and optional account filtering.
- General Ledger includes opening balance and running balance per account.
- Income Statement includes revenue, direct cost, operating expense, other
  income, other expense, and net income sections.
- Balance Sheet includes assets, liabilities, equity, total liabilities and
  equity, and difference.
- Balance Sheet includes unclosed current earnings in equity so reports can
  balance before formal period close and closing entries exist.

## Slice 3B Implemented

Implemented:

- CSV exports for Trial Balance, General Ledger, Income Statement, and Balance
  Sheet.
- CSV exports preserve the active period/date/account filters from each report.
- Trial Balance CSV includes account code, account name, account type, debit,
  credit, balance, and a final total/balanced row.
- General Ledger CSV includes account sections, opening balance rows, posted
  journal lines, running balances, and closing balance rows.
- Income Statement CSV includes section totals and gross profit, operating
  income, and net income summary rows.
- Balance Sheet CSV includes assets, liabilities, equity, total liabilities and
  equity, difference, and balanced status rows.
- Print-friendly browser layouts for the same four reports hide navigation,
  filters, and actions while preserving report headers and tables.
- Regression coverage was added for the CSV report endpoints.

## Slice 3C-A Implemented

Implemented:

- Cash Flow page at `/accounting/cash-flow/`.
- Changes in Equity page at `/accounting/changes-in-equity/`.
- CSV exports and print-friendly layouts for both new statement pages.
- Cash Flow uses posted journal activity against the ISP cash-equivalent
  accounts seeded by the COA templates: cash on hand, bank accounts, and
  e-wallet/gateway clearing.
- Cash Flow classifies entries into operating, investing, and financing
  activities based on the non-cash counterparty accounts.
- Cash Flow reconciles opening cash plus net cash change to closing cash.
- Changes in Equity reports opening equity, equity-account movement, period net
  income, ending equity, and difference against Balance Sheet equity.
- Balance Sheet now displays a visible warning when unclosed current earnings
  are included because closing entries are not posted.
- Accounting dashboard and statement navigation now link to the new statements.

## Slice 3C-B Implemented

Implemented:

- AR Aging page at `/accounting/ar-aging/`.
- AP Aging page at `/accounting/ap-aging/`.
- Tax Ledger page at `/accounting/tax-ledger/`.
- CSV exports and print-friendly layouts for all three new schedules.
- AR Aging uses current unpaid subscriber invoices and compares the schedule
  total to the posted GL AR control account.
- AP Aging uses cutover AP vendor schedule lines when available, then falls
  back to validated opening AP vendor lines, and compares the schedule total
  to the posted GL AP control account.
- Tax Ledger reports opening balance, debit, credit, movement, and ending
  balance for active VAT, percentage tax, withholding, and CWT accounts.
- Tax Ledger also includes optional 2307/EWT claim rows for the selected
  period so claimed customer withholding can be reviewed beside tax GL
  balances.
- Dashboard and statement navigation now link to the aging and tax schedules.

## Slice 3D-A Implemented

Implemented:

- Date range presets for General Ledger, Income Statement, Cash Flow, Changes
  in Equity, and Tax Ledger.
- As-of date presets for Balance Sheet, AR Aging, and AP Aging.
- Trial Balance can include zero-balance accounts for full COA review.
- General Ledger can include zero-balance account sections for account review
  and print/export completeness.
- CSV export links preserve preset and zero-balance filter selections.
- Regression coverage was added for zero-balance report service behavior and
  preset-aware CSV endpoints.

## Report Rules

- Only `posted` journal entries are included.
- Draft, blocked, and reviewed-but-unposted source entries are excluded.
- Balance Sheet is an as-of report using posted lines through the selected
  date.
- Income Statement is a date-range report.
- Cash Flow is a date-range report based on posted movements in configured
  cash-equivalent accounts.
- Changes in Equity is a date-range report that includes unclosed income when
  period closing entries are not posted yet.
- AR Aging is an operational schedule based on current invoice balances as of
  the selected date, with a GL AR control comparison.
- AP Aging is a cutover/vendor schedule based on AP support lines, with a GL AP
  control comparison.
- Tax Ledger is a date-range GL tax account report with optional 2307/EWT claim
  support rows.
- Date presets are UI/report conveniences only; generated reports still show
  the resolved exact dates.
- Zero-balance inclusion applies to Trial Balance and General Ledger only.
- Trial Balance is period-based for now.
- General Ledger is date-range based and can show all active accounts or one
  selected account.

## Remaining Slice 3 Gaps

- PDF and XLSX exports are not implemented for the new reports.
- CSV exports are direct downloads only; they are not yet archived as immutable
  compliance packages or tracked in Data Exchange history.
- Formal period close and closing entries are not implemented yet.
- Department, area, service-type, and subscriber dimensions are not yet present
  in journal lines.
- Cash Flow classification is GL-account based. It will become more exact once
  journal lines carry service area, asset class, settlement, and source document
  dimensions.
- AR Aging is not historical-payment accurate yet because invoice balances are
  current-state operational balances.
- AP Aging is not a full post-live vendor invoice subledger yet; it depends on
  cutover/opening AP support until expense/AP posting is upgraded.
- Tax Ledger is a GL workpaper and optional 2307 support schedule, not a
  finalized BIR return package or SLSP/QAP/MAP file.
- Presets and zero-balance toggles are not yet saved per user.

## Next Slice Candidate

Slice 3D-B should harden report outputs before BIR/NTC books:

- PDF/XLSX export support for the report set.
- Archived report package manifests and generated-file hashes.
- Full post-live AP vendor invoice subledger design.
