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
Slice 3D-B adds export packages for the full report set using canonical CSV
data, XLSX workbooks, PDF workpapers, and JSON manifests with SHA-256 hashes.
Slice 3E adds formal period close with generated closing entries.
Slice 3F adds immutable report archive records and a guarded period reopen
workflow with reversing closing entries.
Slice 3G-A adds the first post-live AP vendor bill subledger.

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

## Slice 3D-B Implemented

Implemented:

- Shared report export helper for CSV, XLSX, PDF, and JSON manifest downloads.
- Trial Balance, General Ledger, Income Statement, Balance Sheet, Cash Flow,
  Changes in Equity, AR Aging, AP Aging, and Tax Ledger now expose XLSX, PDF,
  and manifest actions beside the existing CSV export.
- Export packages are generated from the same canonical report rows used by
  CSV output, so the PDF/XLSX/manifest payloads stay aligned with the report
  service result.
- Manifests include report name, entity, generated timestamp, generated user,
  active filters, row count, columns, canonical CSV filename, canonical CSV
  byte count, and SHA-256 hash.
- XLSX exports include a `Manifest` sheet and a `Report` sheet.
- PDF exports use the existing `xhtml2pdf`/ReportLab path and fall back to a
  downloadable HTML workpaper if PDF rendering fails.
- `openpyxl` is now a project dependency for `.xlsx` workbooks.
- Regression coverage now includes XLSX, manifest, and PDF export smoke checks.

## Slice 3E Implemented

Implemented:

- Accounting periods now store close metadata: closed timestamp, closing user,
  and linked closing journal.
- Journal entries now have a `closing` source type for mechanical period close
  entries.
- Period close preview page at `/accounting/periods/<id>/close/`.
- Closing preview lists generated temporary-account close lines, net income,
  retained/current earnings account, draft journal blockers, and source review
  blockers.
- Closing is blocked when the period is not open, already has a closing
  journal, has draft journals, or has draft/blocked source postings dated
  inside the period.
- Confirming close posts one balanced closing journal dated on the period end
  and then marks the period `closed`.
- Closing lines zero revenue, direct cost, expense, other income, and other
  expense balances for the period, then transfer net income or loss to the
  seeded equity account `3100`.
- Income Statement excludes mechanical closing entries so the closed-period
  operating result remains visible.
- Balance Sheet now adds unclosed current earnings only after the latest closed
  period, preventing double-counting after a formal close.
- Changes in Equity now shows closing-entry transfer adjustment so net income
  and mechanical closing movements do not double-count.
- Regression coverage was added for close posting, statement behavior after
  close, and draft-journal close blocking.

## Slice 3F Implemented

Implemented:

- `AccountingReportArchive` now stores an immutable metadata record for every
  generated CSV, XLSX, PDF, or manifest export.
- Archive records include report name, export format, filename, content type,
  canonical CSV filename, canonical data SHA-256, generated file SHA-256, file
  size, row count, filters, columns, manifest JSON, generator, and timestamp.
- Export responses now include `X-Accounting-Report-Archive-ID` and
  `X-Accounting-Report-File-SHA256` headers.
- Report Archive page at `/accounting/report-archives/` lists archived export
  metadata with report and format filters.
- Period reopen preview page at `/accounting/periods/<id>/reopen/`.
- Reopen is blocked unless the period is closed, has no later closed/locked
  period, and has not already had its closing journal reversed.
- Confirming reopen posts one reversing `closing` journal dated on the period
  end, clears the period close metadata, and returns the period to `open`.
- Reverse-close journals use `source_type='closing'` so Income Statement still
  ignores mechanical close/reopen lines while Trial Balance and Balance Sheet
  see the close and reversal net together.
- Regression coverage was added for archive creation/immutability and
  close-reopen statement behavior.

## Slice 3G-A Implemented

Implemented:

- `APVendorBill` stores post-live supplier bills with vendor, bill number,
  document date, due date, expense/AP accounts, amount, status, linked draft
  journal, and notes.
- `APVendorPayment` stores payments against AP vendor bills with payment date,
  cash/bank account, amount, reference, and linked draft journal.
- AP bill creation creates a draft journal using `Dr expense/direct cost/asset
  / Cr AP`.
- AP payment creation creates a draft journal using `Dr AP / Cr cash/bank`.
- Draft-then-approve remains intact: AP Aging includes AP vendor bills and
  payments only after their journals are posted.
- AP Aging now reads posted AP vendor bills first, subtracts posted AP vendor
  payments, and compares the result to the GL AP control account.
- Existing cutover AP schedule and opening AP vendor fallback remain in place
  when no posted AP vendor bills exist for the entity/date.
- AP vendor bill pages were added at `/accounting/ap-bills/`, including add,
  detail, and payment draft creation.
- Accounting dashboard and AP Aging now link to AP Bills.
- Cashier role presets receive read-only AP bill/payment access while AP bill
  creation and payment draft creation stay behind the AP management permission.
- Regression coverage was added for posted bill/payment AP Aging behavior and
  GL AP control reconciliation.

## Report Rules

- Only `posted` journal entries are included.
- Draft, blocked, and reviewed-but-unposted source entries are excluded.
- Balance Sheet is an as-of report using posted lines through the selected
  date.
- Income Statement is a date-range report and excludes `closing` source
  journals.
- Balance Sheet includes unclosed current earnings only after the latest
  closed or locked period through the selected as-of date.
- Cash Flow is a date-range report based on posted movements in configured
  cash-equivalent accounts.
- Changes in Equity is a date-range report that includes unclosed income when
  period closing entries are not posted yet.
- AR Aging is an operational schedule based on current invoice balances as of
  the selected date, with a GL AR control comparison.
- AP Aging uses the posted AP vendor bill subledger when present, then cutover
  AP support lines, then opening AP vendor lines, with a GL AP control
  comparison.
- Tax Ledger is a date-range GL tax account report with optional 2307/EWT claim
  support rows.
- Date presets are UI/report conveniences only; generated reports still show
  the resolved exact dates.
- Zero-balance inclusion applies to Trial Balance and General Ledger only.
- Trial Balance is period-based for now.
- General Ledger is date-range based and can show all active accounts or one
  selected account.
- Report exports create immutable archive metadata records with canonical data
  and generated-file hashes.

## Remaining Slice 3 Gaps

- Report archive records store metadata and hashes only; binary file storage
  and bundled package downloads are still future work.
- Period reopen/reverse-close is available, but does not yet have a separate
  reviewer approval workflow.
- Period close does not yet create a persisted close checklist beyond the audit
  log and close metadata.
- Department, area, service-type, and subscriber dimensions are not yet present
  in journal lines.
- Cash Flow classification is GL-account based. It will become more exact once
  journal lines carry service area, asset class, settlement, and source document
  dimensions.
- AR Aging is not historical-payment accurate yet because invoice balances are
  current-state operational balances.
- AP vendor bills do not yet have void/reversal workflow, vendor master records,
  attachment storage, purchase tax breakdowns, or payment settlement matching.
- AP Aging selects the post-live AP bill subledger ahead of cutover/opening
  fallbacks; a merged historical cutover plus post-live AP view is still future
  work.
- Tax Ledger is a GL workpaper and optional 2307 support schedule, not a
  finalized BIR return package or SLSP/QAP/MAP file.
- Presets and zero-balance toggles are not yet saved per user.

## Next Slice Candidate

Slice 3G-B should continue AP hardening before BIR/NTC books:

- AP bill void/reversal and purchase tax breakdowns.
- Vendor master records and attachment storage.
- Binary archive/package storage for generated export files.
- Saved report presets per user.
