# Accounting v2 Slice 3 Financial Statements Plan

## Summary

Slice 3 starts the financial statement layer on top of the posted Accounting v2
ledger. Slice 3A delivered the core accountant-facing reports. Slice 3B adds
basic export and print ergonomics while still avoiding BIR/NTC claims,
immutable filing packages, and full subledger engines.

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
- PDF and XLSX exports are not implemented for the new reports.
- CSV exports are direct downloads only; they are not yet archived as immutable
  compliance packages or tracked in Data Exchange history.
- Formal period close and closing entries are not implemented yet.
- Department, area, service-type, and subscriber dimensions are not yet present
  in journal lines.

## Next Slice Candidate

Slice 3C should add the missing statement schedules that accountants will need
before BIR/NTC books:

- Cash Flow statement.
- Changes in Equity statement.
- AR aging schedule tied to the AR control account.
- AP aging schedule tied to the AP control account.
- Optional zero-balance account toggle and report date presets.
- Clear warning when the Balance Sheet relies on unclosed current earnings.
