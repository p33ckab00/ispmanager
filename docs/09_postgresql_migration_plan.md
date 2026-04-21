# PostgreSQL Migration Plan

Migration planning document for moving `ISP Manager` from SQLite to PostgreSQL.

## Purpose

This document defines the migration strategy for transitioning `ISP Manager` from SQLite to PostgreSQL in a way that is safe, practical, and production-oriented.

It covers two paths:

- preferred path: fresh PostgreSQL start before production
- fallback path: move existing SQLite data into PostgreSQL

## Recommended Direction

For this project, the recommended approach is:

- do **not** preserve SQLite as the long-term production database
- move to PostgreSQL before production
- avoid complicated legacy carry-over unless business data already matters

## Why Migration Is Needed

The project now includes workloads that are weak fits for SQLite:

- scheduler writes
- router telemetry cache writes
- usage sampling
- billing and payment writes
- concurrent admin reads
- notification logging

SQLite can still work for light local development, but it becomes unreliable when the application performs frequent concurrent writes.

PostgreSQL is the intended long-term target.

## 1. Migration Strategy Options

## Option A: Fresh PostgreSQL Start

This is the recommended path if production has not yet started.

### Description

Instead of transferring the existing SQLite file and all of its records, create a fresh PostgreSQL database and start the system there as the new source of truth.

### Best Use Case

- pre-production environment
- prototype data only
- test records do not need to be preserved
- easier to avoid importing bad or incomplete development data

### Advantages

- simplest and safest path
- avoids data cleanup burden
- avoids migration mismatches
- avoids carrying legacy scheduler noise and temporary development data
- best fit for a system still being stabilized

### Recommended Workflow

1. Prepare PostgreSQL
2. Point Django settings to PostgreSQL
3. Run migrations into fresh PostgreSQL
4. Create production admin user
5. Re-enter only meaningful setup data
6. Launch staging/production from PostgreSQL

### Recommendation

If the live business has not yet started relying on the SQLite data, choose this option.

## Option B: SQLite to PostgreSQL Data Migration

Use this only if SQLite already contains meaningful operational or financial data that must be preserved.

### Description

Export application data from SQLite, provision PostgreSQL, then import the required data into the new PostgreSQL-backed environment.

### Best Use Case

- real subscriber records already exist
- billing and payments already matter
- business data cannot be discarded

### Risks

- foreign key dependency ordering
- importing incomplete or dirty prototype data
- accidentally moving internal scheduler/job noise
- mismatched historical states
- duplicate or stale operational records

### Recommendation

Choose this only when the stored SQLite data has real business value that justifies migration effort and verification work.

## 2. Recommended Decision Rule

Use this rule:

- if the data is mostly test/demo/dev data: `start fresh on PostgreSQL`
- if the data contains real billing, subscriber, or payment history: `perform a controlled migration`

## 3. Scope Definition Before Migration

Before any migration work begins, define exactly what should move.

### Candidate Data to Preserve

- subscribers
- plans
- rate history
- invoices
- payments
- payment allocations
- billing snapshots
- accounting records
- settings
- routers
- router interfaces
- network nodes

### Candidate Data to Exclude

Usually not worth migrating unless specifically required:

- temporary diagnostics history
- stale OTP records
- failed test notifications
- scheduler execution history
- volatile telemetry cache rows
- old short-lived development logs

### Suggested Rule

Preserve:

- business records
- configuration records
- current operational topology

Do not preserve by default:

- transient runtime noise
- temporary cache-like data
- debugging artifacts

## 4. Pre-Migration Checklist

Before migration starts, confirm:

- PostgreSQL target version selected
- PostgreSQL server provisioned
- database and DB user created
- Django environment ready for PostgreSQL
- full backup of SQLite file created
- application writes can be paused
- rollback plan documented

If migrating real data, also confirm:

- subscriber count known
- invoice count known
- payment count known
- financial totals recorded before cutover

## 5. Fresh Start Workflow

This is the preferred plan.

### Step 1: Provision PostgreSQL

Set up:

- PostgreSQL database
- dedicated database user
- environment variables

### Step 2: Point Django to PostgreSQL

Switch `DATABASES` configuration from SQLite to PostgreSQL.

### Step 3: Run Migrations

Apply all Django migrations against the fresh PostgreSQL database.

### Step 4: Create Superuser

Create the first admin account.

### Step 5: Recreate Required Base Data

Manually or via admin/setup flow:

- ISP system info
- billing settings
- SMS settings
- Telegram settings
- routers
- plans
- subscriber seed records if needed

### Step 6: Validate Core Flows

Test:

- login
- subscriber CRUD
- billing generation
- router detail pages
- payment recording
- settings save

### Step 7: Treat PostgreSQL as New Source of Truth

After this point:

- SQLite is legacy only
- PostgreSQL becomes the official app database

## 6. SQLite-to-PostgreSQL Transfer Workflow

Use only if data must be preserved.

### Step 1: Freeze Writes

Before exporting:

- stop app writes
- stop scheduler
- stop background tasks
- stop web process if necessary

This ensures a consistent SQLite snapshot.

### Step 2: Back Up SQLite

Create a full backup of:

- `db.sqlite3`

Do not proceed without a preserved backup copy.

### Step 3: Inventory Data

Record pre-migration counts for:

- subscribers
- plans
- invoices
- payments
- billing snapshots
- income and expense rows
- routers
- interfaces

Also record key finance totals:

- total open balance
- total invoice amount
- total payment amount

### Step 4: Provision PostgreSQL

Set up fresh PostgreSQL schema through normal Django migrations.

### Step 5: Export Data

Export only the tables/entities that matter.

### Step 6: Import Into PostgreSQL

Load data into PostgreSQL in dependency-safe order.

Recommended entity order:

1. core setup/config tables
2. settings tables
3. routers
4. plans
5. subscribers
6. rate history
7. billing records
8. payments and allocations
9. accounting rows
10. network topology records

### Step 7: Exclude Volatile Runtime Data Where Appropriate

Default exclude candidates:

- OTP records
- notification test noise
- scheduler execution logs
- temporary telemetry cache

### Step 8: Validation

Compare PostgreSQL against the recorded SQLite counts.

Validate:

- row counts
- finance totals
- random sample spot checks
- subscriber to invoice relationships
- invoice to payment allocation relationships

### Step 9: Cutover

Switch app config to PostgreSQL and keep SQLite as backup only.

## 7. Data Validation Checklist

After migration, validate all of the following:

### Subscriber Domain

- total subscriber count matches
- active/suspended/disconnected counts match
- plans are correctly linked
- router associations are correct

### Billing Domain

- invoice count matches
- total invoice amounts are reasonable
- open/partial/paid/overdue counts are acceptable
- billing snapshots still point to correct subscribers

### Payments

- payment count matches
- payment totals match
- allocation totals match invoice payments
- no orphan allocations exist

### Accounting

- income rows match expected billing-linked payments
- expense rows preserved

### Settings

- billing settings loaded correctly
- router settings loaded correctly
- Telegram/SMS settings present

## 8. Rollback Plan

Never migrate without rollback.

### Rollback Requirements

- original SQLite file preserved
- PostgreSQL target can be dropped/reset if needed
- application can be pointed back to SQLite if cutover fails

### Rollback Trigger Conditions

Rollback immediately if:

- row counts are incorrect
- financial totals do not reconcile
- app cannot start against PostgreSQL
- critical relationships are broken

## 9. Staging First Policy

Do not perform the first migration directly into production.

### Required Sequence

1. Test migration in local environment
2. Repeat migration in staging
3. Verify application behavior in staging
4. Only then schedule production cutover

## 10. Production Cutover Workflow

When production data matters, use a cutover window.

### Recommended Sequence

1. Announce maintenance window
2. Stop web writes
3. Stop scheduler
4. Back up SQLite
5. Run final export/import
6. Verify counts and core workflows
7. Update environment to PostgreSQL
8. Start services
9. Smoke test immediately
10. Monitor closely

## 11. Smoke Test Checklist After Cutover

Immediately test:

- login
- dashboard
- subscriber list
- subscriber detail
- router list
- router detail
- billing pages
- record payment flow
- settings save
- portal OTP flow
- diagnostics page

## 12. Migration Risk Areas Specific to ISP Manager

### 12.1 Billing and Payments

High-risk area because:

- invoices are financial records
- payment allocations depend on accurate relationships
- open/partial/paid states must remain consistent

### 12.2 Router and Interface Data

Moderate risk because:

- router records can be recreated
- interface inventory can be re-synced
- cached live telemetry should not be treated as business-critical

### 12.3 Usage Data

Usually lower priority for migration because:

- usage samples are time-series-like
- missing a small amount of historical dev usage is often acceptable
- sampler can rebuild future data after cutover

### 12.4 Notification History

Usually low-value for migration unless required for audit.

### 12.5 OTP Records

Do not preserve expired or transient OTP records.

## 13. Recommended Final Position

For this project, the best migration strategy is:

- `fresh PostgreSQL start` if still pre-production
- `controlled SQLite-to-PostgreSQL migration` only if real business data already exists

## 14. Final Recommendation

If you are still before full production:

- do not spend effort on complex SQLite history migration
- switch now to PostgreSQL
- test there early
- stabilize production on PostgreSQL from the beginning

If you already have meaningful live data:

- migrate only the business-critical records
- validate aggressively
- use staging before production cutover

