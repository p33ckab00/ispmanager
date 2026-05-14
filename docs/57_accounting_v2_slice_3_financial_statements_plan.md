# Accounting v2 Slice 3 Financial Statements Plan

## Summary

Slice 3 starts the financial statement layer on top of the posted Accounting v2
ledger. The first implemented sub-slice is Slice 3A, which keeps the scope to
core accountant-facing reports and avoids BIR/NTC claims, immutable filing
packages, and full subledger engines.

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

## Report Rules

- Only `posted` journal entries are included.
- Draft, blocked, and reviewed-but-unposted source entries are excluded.
- Balance Sheet is an as-of report using posted lines through the selected
  date.
- Income Statement is a date-range report.
- Trial Balance is period-based for now.
- General Ledger is date-range based and can show all active accounts or one
  selected account.

## Remaining Slice 3 Gaps

- Cash Flow statement is not implemented yet.
- Changes in Equity statement is not implemented yet.
- AR aging and AP aging are not implemented as formal statement schedules yet.
- VAT ledger and tax reconciliation reports remain manual/cutover-level only.
- PDF/XLSX/CSV exports are not implemented for the new reports.
- Formal period close and closing entries are not implemented yet.
- Department, area, service-type, and subscriber dimensions are not yet present
  in journal lines.

## Next Slice Candidate

Slice 3B should add report exports and accountant review ergonomics:

- CSV export for Trial Balance, General Ledger, Income Statement, and Balance
  Sheet.
- Print-friendly layouts for the same reports.
- Report date presets.
- Optional zero-balance account toggle.
- Clear warning when the Balance Sheet relies on unclosed current earnings.

