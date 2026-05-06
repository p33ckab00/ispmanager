# Accounting v2 Slice 1C-G ATC Catalog

## Summary

Slice 1C-G adds an Accounting-owned BIR ATC catalog before moving to Slice 2.
The catalog supports optional customer EWT/CWT and BIR Form 2307 workflows by
giving operators a maintained list of ATC codes instead of free-text-only ATC
entry.

The seed is based on:

- the Taxumo ATC screenshot supplied during planning, used as a cross-check
  shortlist
- BIR Revenue Memorandum Order No. 38-2018 for common 1601-EQ/2307 expanded
  withholding tax ATCs
- BIR Revenue Memorandum Order No. 18-2025 for CREATE MORE Act changes,
  including the modified credit-card company rate, dropped WI760/WC760, and
  new WI820/WC820 and WI830/WC830
- BIR Revenue Memorandum Order No. 46-2025 for WI840/WC840

The catalog is not a final BIR submission engine. It is a controlled reference
table for selecting and tracking ATCs in withholding classes and 2307 claims.

## Implementation

- Added `AlphanumericTaxCode`.
- Added optional `atc_code` links to:
  - `WithholdingTaxClass`
  - `CustomerWithholdingTaxClaim`
- Added `seed_bir_atc_codes`.
- Added management command:

```bash
.venv/bin/python manage.py seed_bir_atc_codes
```

- Added migration seed data so new deployments receive the catalog on migrate.
- Added `/accounting/withholding/atc/` for browsing the catalog.
- Withholding class setup can now select a catalog ATC and automatically use
  its ATC code, rate, and source reference when those fields are blank.
- Payment recording can optionally select an ATC catalog code for a customer
  2307 claim.

## Seed Coverage

The first catalog is focused on 1601-EQ/2307 expanded withholding tax codes
visible in the supplied Taxumo screenshot and cross-checked against BIR RMO
references. It includes common ISP-relevant 2307 choices such as:

- `WI157` / `WC157`: government payments to local/resident suppliers of
  services
- `WI158` / `WC158`: top withholding agent payments to suppliers of goods
- `WI160` / `WC160`: top withholding agent payments to suppliers of services
- `WI820` / `WC820`: e-marketplace operator remittances
- `WI830` / `WC830`: digital financial services provider remittances

Dropped codes such as `WI760` / `WC760` are seeded inactive so historical
records can still be interpreted without offering them as active choices.

## Remaining Gaps

- The catalog is not yet a complete all-tax-type ATC handbook.
- VAT withholding ATCs and final withholding tax ATCs are not fully seeded in
  this slice.
- Future BIR issuances still need a maintenance workflow or import format.
- The accountant still chooses the correct ATC based on the taxpayer facts,
  payor type, COR, and certificate received.

## Test Notes

- Check that common codes such as `WC160`, `WC158`, `WI820`, and inactive
  `WC760` exist after seeding.
- Check that customer 2307 payment workflow can store the selected catalog ATC
  link and fallback text ATC.
- Check that `/accounting/withholding/atc/` loads.
