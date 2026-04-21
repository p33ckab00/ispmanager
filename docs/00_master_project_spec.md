# ISP Manager
Master Product, Architecture, and Implementation Document

## Table of Contents
1. Project Overview
2. Product Requirements
3. System Architecture
4. Core Modules
5. Feature Breakdown
6. User Workflows
7. Data Model and Database Design
8. API Design
9. End-to-End Process Flow
10. Automation and Operational Logic
11. Performance and Scaling
12. Security
13. Edge Cases and Failure Handling
14. Deployment and Infrastructure
15. Implementation Roadmap
16. Acceptance Criteria

---

## 1. Project Overview

### 1.1 Purpose
`ISP Manager` is a unified ISP operations platform for managing subscribers, network devices, service status, billing, collections, accounting, notifications, and subscriber self-service. It is designed to replace fragmented operational workflows spread across spreadsheets, router consoles, chat threads, and manual billing practices.

### 1.2 Problem It Solves
Typical ISPs suffer from disconnected operational systems:
- Subscriber records are inconsistent with router configuration.
- Billing is manually generated and often inaccurate after plan changes.
- Payment posting is detached from invoice balances.
- Suspensions and reconnections are manually enforced.
- Customers rely on support staff just to check bills or account status.
- Network visibility is reactive and not linked to customer records.

`ISP Manager` solves this by making subscriber, router, billing, and collections data converge into one operational source of truth.

### 1.3 Target Users
- `Super Admin`: owns settings, permissions, system policy, and audit oversight.
- `ISP Operator / CSR`: handles subscriber onboarding, updates, billing, payments, and customer support.
- `NOC / Network Engineer`: manages routers, sync jobs, traffic monitoring, and service enforcement.
- `Finance / Accounting Staff`: reviews invoices, payments, income, expenses, and reporting.
- `Subscriber / End User`: accesses portal via OTP to view account and billing information.

### 1.4 Core Value Proposition
- One platform for subscriber operations and finance
- Accurate billing through historical pricing and snapshot logic
- Lower manual work via automation and scheduled jobs
- Faster collections with reminders, short billing links, and portal access
- Operational reliability through auditability, monitoring, and retry-safe workflows

---

## 2. Product Requirements

### 2.1 Product Vision
Build a production-ready ISP back-office and subscriber-facing platform that supports the full service lifecycle from onboarding to provisioning, billing, payment, suspension, reconnection, and monitoring.

### 2.2 Business Objectives
- Reduce billing errors and duplicate invoices
- Improve payment posting speed and financial visibility
- Minimize manual router-side service enforcement
- Lower support volume during billing periods
- Centralize operational records and system policy

### 2.3 Functional Requirements
- Staff authentication and RBAC
- Subscriber CRUD with lifecycle states
- Plan and rate management with historical tracking
- Router registry and connectivity checks
- Router-to-subscriber sync and active session sync
- Interface inventory and traffic snapshots
- Invoice generation and statement snapshots
- Payment recording with automatic allocation
- Overdue detection and suspension/reconnection workflows
- SMS and Telegram notifications
- OTP-secured subscriber portal
- Income and expense tracking
- Centralized singleton settings
- Scheduler and worker-based automation
- Audit logging for sensitive operations

### 2.4 Non-Functional Requirements
- Billing generation must be idempotent
- Payment posting must be transactional
- Public and admin traffic must use TLS
- Secrets must be encrypted at rest
- OTP, login, and public billing endpoints must be rate-limited
- Job execution must be observable with logs, metrics, and failure states
- System must support at least `100,000` subscribers with scaling controls

---

## 3. System Architecture

### 3.1 Architecture Style
`Hybrid modular monolith`

### 3.2 Rationale
A modular monolith is the best fit for the current system because:
- Subscriber, billing, and router workflows are highly transactional and tightly related
- Operational simplicity matters more than distributed complexity
- Clear module boundaries allow later extraction into services if scale requires it
- Asynchronous work can be handled by workers without fragmenting the codebase

### 3.3 Major Components
- `Web Frontend`: admin dashboard, operator forms, reports, portal pages
- `REST API Layer`: API endpoints for UI, portal, and external integrations
- `Core Module`: auth, RBAC, audit context, shared services
- `Subscribers Module`: plans, subscribers, rate history, OTP, status lifecycle
- `Routers Module`: routers, interfaces, traffic, sync, enforcement
- `Billing Module`: invoices, snapshots, payments, allocations, overdue logic
- `Accounting Module`: income and expenses
- `Notifications Module`: SMS, Telegram, event dispatch
- `Settings Module`: billing, SMS, router, subscriber, usage policy
- `Worker Layer`: scheduled jobs, retries, background tasks
- `PostgreSQL`: source of truth for transactional data
- `Redis`: cache, queue backend, throttling coordination
- `Integrations`: MikroTik API, SMS gateway, Telegram Bot API

### 3.4 Component Interaction
1. Admin or subscriber interacts with UI over `HTTPS`.
2. UI calls backend view or API layer.
3. Backend routes request to domain service.
4. Domain service validates business rules and updates PostgreSQL.
5. Slow or failure-prone tasks are sent to worker queue.
6. Workers call external systems such as routers or SMS providers.
7. Results update system state and emit notifications or metrics.

### 3.5 Data Flow
- Subscriber creation -> subscriber DB row -> optional router provisioning -> notification event
- Router sync -> router API data -> subscriber operational fields update -> monitoring counters refresh
- Billing generation -> subscriber/rate/settings lookup -> invoice rows -> snapshot rows -> reminder queue
- Payment posting -> payment row -> payment allocations -> invoice status updates -> accounting income row
- Portal login -> OTP issue -> SMS dispatch -> OTP verify -> session bind -> invoice/snapshot read model

### 3.6 Protocols
- `HTTPS`: admin UI, portal, REST APIs
- `WebSocket`: optional real-time dashboard updates
- `MikroTik API`: router sync and enforcement
- `REST`: SMS and Telegram integrations
- `Redis protocol`: queue, cache, throttling
- `PostgreSQL`: transactional datastore
- `SNMP`: optional future support for expanded monitoring

---

## 4. Core Modules

### 4.1 Core
Responsibilities:
- Authentication
- Authorization
- Session management
- Audit logging
- Shared middleware
- Error handling
- Global dashboard aggregation

### 4.2 Subscribers
Responsibilities:
- Plan management
- Subscriber records
- Status transitions
- Rate history
- OTP generation and validation
- Portal identity context
- Usage linkage

### 4.3 Routers
Responsibilities:
- Router inventory
- Connection validation
- Interface discovery
- Traffic snapshots
- Active session sync
- Subscriber sync
- Suspension/reconnect enforcement

### 4.4 Billing
Responsibilities:
- Billing period calculation
- Invoice generation
- Statement snapshot generation
- Payment posting
- Allocation logic
- Overdue marking
- Public tokenized billing views

### 4.5 Accounting
Responsibilities:
- Income records from payments
- Manual income
- Manual expense capture
- Finance summaries

### 4.6 Notifications
Responsibilities:
- Event logging
- SMS dispatch
- Telegram dispatch
- Retry management
- Delivery status tracking

### 4.7 Settings
Responsibilities:
- Billing policies
- SMS templates and schedules
- Router polling and timeouts
- Subscriber automation behavior
- Usage retention and sampling policy

---

## 5. Feature Breakdown

### 5.1 Authentication and RBAC
- `Purpose`: secure access and role isolation
- `Inputs`: username, password, optional MFA, requested route
- `Outputs`: session/token, actor identity, permission result
- `Internal Logic`:
  1. Validate credentials
  2. Check account state
  3. Load role mappings
  4. Issue session/token
  5. Enforce route/action authorization
  6. Record auth event
- `Edge Cases`: disabled user, concurrent sessions, stale role cache
- `Failure Scenarios`: brute-force attack, session fixation, revoked user still active
- `Dependencies`: auth tables, session store, audit log

### 5.2 Subscriber Management
- `Purpose`: maintain authoritative subscriber records
- `Inputs`: identity, contact data, plan, router assignment, lifecycle actions
- `Outputs`: subscriber row, searchable state, lifecycle status
- `Internal Logic`:
  1. Validate unique username
  2. Persist admin-owned fields
  3. Keep router-owned fields separated
  4. Compute `effective_rate`, `display_name`, `can_generate_billing`
  5. Trigger notifications when relevant
- `Edge Cases`: no phone, no plan but manual rate, disconnected with unpaid invoices
- `Failure Scenarios`: duplicate usernames, invalid state transitions
- `Dependencies`: subscribers tables, notifications, routers

### 5.3 Plan and Rate History
- `Purpose`: preserve pricing changes across billing cycles
- `Inputs`: plan changes, rate overrides, effective date, apply mode
- `Outputs`: updated subscriber pricing state, immutable rate history
- `Internal Logic`:
  1. Compare old and new price state
  2. Insert history row if changed
  3. Update subscriber current plan/rate
  4. Signal billing recalculation where allowed
- `Edge Cases`: backdated changes, plan unchanged but rate changed
- `Failure Scenarios`: historical gap, double application to unpaid invoices
- `Dependencies`: plan table, rate history table, billing rules

### 5.4 Router Inventory and Connectivity
- `Purpose`: maintain known routers and operational reachability
- `Inputs`: host, credentials, port, metadata
- `Outputs`: router status, last seen, connection result
- `Internal Logic`:
  1. Save metadata
  2. Test API handshake
  3. Update status and last seen
  4. Queue sync jobs on success
- `Edge Cases`: wrong host, DNS changes, intermittent timeout
- `Failure Scenarios`: auth failure, port mismatch
- `Dependencies`: router table, settings, MikroTik adapter

### 5.5 Subscriber Sync
- `Purpose`: align DB operational state with router state
- `Inputs`: router secrets, active sessions, usernames, IPs
- `Outputs`: updated subscriber router-owned fields, sync report
- `Internal Logic`:
  1. Pull router-side subscriber identities
  2. Match by username
  3. Create missing technical records if absent
  4. Update router-owned fields only
  5. Update online/offline based on active sessions
- `Edge Cases`: subscriber moved between routers, secret deleted, duplicate names
- `Failure Scenarios`: partial import, stale IP data
- `Dependencies`: router API, subscriber table

### 5.6 Interface Discovery and Traffic Monitoring
- `Purpose`: support NOC operational visibility
- `Inputs`: router interface list and counters
- `Outputs`: interface inventory, time-series traffic snapshots
- `Internal Logic`:
  1. Discover interfaces
  2. Upsert by `(router_id, name)`
  3. Read counters
  4. Convert into rate snapshots
  5. Persist metrics for dashboard
- `Edge Cases`: renamed interfaces, counter reset, dynamic PPP interfaces
- `Failure Scenarios`: invalid counters, sampling gaps
- `Dependencies`: interface tables, worker scheduler

### 5.7 Invoice Generation
- `Purpose`: create receivable ledger rows
- `Inputs`: billing settings, subscriber status, resolved rate, billing period
- `Outputs`: invoice row with invoice number, token, short code
- `Internal Logic`:
  1. Determine target period
  2. Filter billable subscribers
  3. Resolve effective rate
  4. Check existing invoice for same cycle
  5. Create invoice atomically
- `Edge Cases`: mid-cycle activation, no rate, suspended but billable
- `Failure Scenarios`: duplicate invoice, missing due date
- `Dependencies`: invoice table, subscriber table, rate history, billing settings

### 5.8 Billing Snapshots
- `Purpose`: generate frozen customer-facing statements
- `Inputs`: current invoice, previous balance, credits, issue date, due date
- `Outputs`: snapshot header and line items
- `Internal Logic`:
  1. Gather invoice and prior balance state
  2. Compute total due
  3. Create snapshot items
  4. Freeze immediately or keep as draft based on settings
- `Edge Cases`: partial payment between draft and freeze, negative due from credits
- `Failure Scenarios`: snapshot total differs from ledger state
- `Dependencies`: snapshot tables, invoices, allocations

### 5.9 Payment Recording and Allocation
- `Purpose`: post funds and reduce balances correctly
- `Inputs`: subscriber, amount, method, reference, paid_at
- `Outputs`: payment row, allocation rows, updated invoice states
- `Internal Logic`:
  1. Validate amount and duplicate references
  2. Create payment
  3. Allocate oldest-first to open/partial invoices
  4. Update `amount_paid` and invoice status
  5. Create income record
  6. Emit payment notification
- `Edge Cases`: overpayment, no open invoices, duplicate callback
- `Failure Scenarios`: allocation interruption, double payment post
- `Dependencies`: payments, allocations, invoices, accounting

### 5.10 Overdue and Enforcement
- `Purpose`: protect revenue and standardize collections
- `Inputs`: invoice age, grace period, subscriber status, automation settings
- `Outputs`: overdue invoice flags, suspended subscribers, reconnect actions
- `Internal Logic`:
  1. Find invoices past due plus grace
  2. Mark as overdue
  3. Determine suspension eligibility
  4. Queue router disable action
  5. Reconnect automatically when balance clears if allowed
- `Edge Cases`: payment posted right before job, router offline during suspension
- `Failure Scenarios`: wrongful suspension, failed reconnect
- `Dependencies`: billing, subscribers, router API, settings

### 5.11 Portal OTP Authentication
- `Purpose`: give subscriber secure self-service access
- `Inputs`: phone number, OTP, session
- `Outputs`: authenticated portal session
- `Internal Logic`:
  1. Match phone to subscriber
  2. Generate OTP and expiry
  3. Invalidate prior active OTPs
  4. Dispatch SMS
  5. Verify OTP and bind session to subscriber
- `Edge Cases`: shared phone number, delayed SMS, expired OTP
- `Failure Scenarios`: replay, brute force, provider outage
- `Dependencies`: OTP table, subscriber table, SMS adapter

### 5.12 Notifications
- `Purpose`: centralize system and customer messaging
- `Inputs`: domain events, templates, recipient targets
- `Outputs`: notification records and external sends
- `Internal Logic`:
  1. Accept structured event
  2. Render content
  3. Create pending notification
  4. Send via channel worker
  5. Mark sent or failed with error
- `Edge Cases`: missing template variables, opt-out subscribers
- `Failure Scenarios`: gateway rejection, invalid chat ID
- `Dependencies`: notifications table, SMS settings, Telegram settings

### 5.13 Usage Tracking
- `Purpose`: monitor subscriber bandwidth consumption
- `Inputs`: session counters, sample time, session key
- `Outputs`: raw usage rows and daily rollups
- `Internal Logic`:
  1. Poll counters
  2. Compare to prior sample
  3. Compute deltas
  4. Mark counter resets
  5. Store raw sample
  6. Roll up daily totals nightly
- `Edge Cases`: reconnect counter reset, multiple sessions per subscriber
- `Failure Scenarios`: negative deltas, aggregator drift
- `Dependencies`: usage tables, router session polling

---

## 6. User Workflows

### 6.1 Admin Workflow
- `Trigger`: operator onboards a new subscriber
- `Steps`:
  1. Login to admin dashboard
  2. Create subscriber with identity, contact, router, plan, and start date
  3. Save subscriber
  4. Optionally trigger router provisioning/sync
  5. Generate first invoice if policy requires
  6. Send welcome or portal SMS
- `Backend Processing`:
  - Validate uniqueness
  - Save subscriber
  - Insert rate history if commercial terms exist
  - Call router service if enabled
  - Generate billing artifacts if requested
  - Log audit and notifications
- `Expected Result`: subscriber is operationally and commercially ready
- `Possible Errors`: duplicate username, router unreachable, invalid plan/rate

### 6.2 End-User Workflow
- `Trigger`: subscriber wants to check current bill
- `Steps`:
  1. Open portal
  2. Enter registered phone number
  3. Receive OTP
  4. Submit OTP
  5. View account summary and statement
  6. Open public billing link if needed
- `Backend Processing`:
  - Match subscriber by phone
  - Generate/send OTP
  - Verify OTP
  - Bind session
  - Load invoice/snapshot summary
- `Expected Result`: subscriber sees current due amount and account status
- `Possible Errors`: phone not found, OTP expired, SMS failed

### 6.3 System Automated Workflow
- `Trigger`: scheduled billing and collections jobs
- `Steps`:
  1. Load settings and execution date
  2. Acquire job lock
  3. Generate invoices for eligible subscribers
  4. Generate statements
  5. Mark overdue accounts
  6. Queue reminders
  7. Suspend delinquent services if configured
- `Backend Processing`:
  - Idempotent invoice generation
  - Transactional DB writes
  - Async notification dispatch
  - Retry-safe router enforcement
- `Expected Result`: billing cycle advances without manual intervention
- `Possible Errors`: duplicate scheduler run, DB deadlock, router failures, queue backlog

---

## 7. Data Model and Database Design

### 7.1 Main Entities
- `auth_user`
- `auth_group`
- `audit_log`
- `routers_router`
- `routers_routerinterface`
- `routers_interfacetrafficsnapshot`
- `subscribers_plan`
- `subscribers_subscriber`
- `subscribers_ratehistory`
- `subscribers_subscriberotp`
- `subscribers_subscriberusagesample`
- `subscribers_subscriberusagedaily`
- `billing_invoice`
- `billing_payment`
- `billing_paymentallocation`
- `billing_billingsnapshot`
- `billing_billingsnapshotitem`
- `accounting_incomerecord`
- `accounting_expenserecord`
- `notifications_notification`
- `settings_globalsetting`
- `settings_billingsettings`
- `settings_smssettings`
- `settings_telegramsettings`
- `settings_routersettings`
- `settings_subscribersettings`
- `settings_usagesettings`

### 7.2 Key Relationships
- `Router 1:N Subscriber`
- `Router 1:N RouterInterface`
- `RouterInterface 1:N InterfaceTrafficSnapshot`
- `Plan 1:N Subscriber`
- `Subscriber 1:N RateHistory`
- `Subscriber 1:N Invoice`
- `Subscriber 1:N Payment`
- `Payment 1:N PaymentAllocation`
- `Invoice 1:N PaymentAllocation`
- `Subscriber 1:N BillingSnapshot`
- `BillingSnapshot 1:N BillingSnapshotItem`
- `Payment 1:1 IncomeRecord` for billing-linked payments
- `Subscriber 1:N SubscriberOTP`
- `Subscriber 1:N UsageSample`
- `Subscriber 1:N UsageDaily`

### 7.3 Indexing Strategy
- Unique:
  - `subscriber.username`
  - `invoice.invoice_number`
  - `invoice.token`
  - `invoice.short_code`
  - `snapshot.snapshot_number`
  - `routerinterface(router_id, name)`
- Performance:
  - `subscriber(phone)`
  - `subscriber(router_id, status)`
  - `ratehistory(subscriber_id, effective_date desc)`
  - `invoice(subscriber_id, status, due_date)`
  - `payment(subscriber_id, paid_at desc)`
  - `usage_sample(subscriber_id, sampled_at desc)`
  - `notification(status, created_at)`
- Partial indexes:
  - open invoices only
  - pending notifications only
  - active subscribers only

### 7.4 Example Records
- Subscriber: `juan123`, `active`, plan `20Mbps Residential`, rate `1299.00`
- Router: `BRAS-01`, host `10.0.0.1`, status `online`
- Invoice: `INV-202604-0007`, amount `1299.00`, status `partial`
- Payment: `500.00`, method `gcash`, reference `GC123456789`

---

## 8. API Design

### 8.1 Authentication
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### 8.2 Routers
- `GET /api/v1/routers`
- `POST /api/v1/routers`
- `GET /api/v1/routers/{id}`
- `PATCH /api/v1/routers/{id}`
- `POST /api/v1/routers/{id}/test-connection`
- `POST /api/v1/routers/{id}/sync-interfaces`
- `POST /api/v1/routers/{id}/sync-subscribers`

### 8.3 Subscribers
- `GET /api/v1/subscribers`
- `POST /api/v1/subscribers`
- `GET /api/v1/subscribers/{id}`
- `PATCH /api/v1/subscribers/{id}`
- `POST /api/v1/subscribers/{id}/plan-change`
- `POST /api/v1/subscribers/{id}/suspend`
- `POST /api/v1/subscribers/{id}/reconnect`
- `POST /api/v1/subscribers/{id}/disconnect`
- `POST /api/v1/subscribers/{id}/archive`

### 8.4 Billing
- `GET /api/v1/billing/invoices`
- `POST /api/v1/billing/invoices/generate`
- `GET /api/v1/billing/invoices/{id}`
- `POST /api/v1/billing/invoices/{id}/void`
- `GET /api/v1/billing/snapshots`
- `POST /api/v1/billing/snapshots/generate`
- `POST /api/v1/billing/payments`
- `GET /api/v1/billing/payments/{id}`
- `POST /api/v1/billing/mark-overdue`

### 8.5 Portal
- `POST /api/v1/portal/request-otp`
- `POST /api/v1/portal/verify-otp`
- `GET /api/v1/portal/me`
- `GET /api/v1/portal/invoices`
- `GET /api/v1/portal/snapshots`
- `GET /billing/public/{token}`

### 8.6 Settings
- `GET/PATCH /api/v1/settings/billing`
- `GET/PATCH /api/v1/settings/router`
- `GET/PATCH /api/v1/settings/sms`
- `GET/PATCH /api/v1/settings/telegram`
- `GET/PATCH /api/v1/settings/subscribers`
- `GET/PATCH /api/v1/settings/usage`

### 8.7 Standard API Error Model
Each error response should include:
- `code`
- `message`
- `details` optional
- `request_id`

Common error codes:
- `AUTHENTICATION_FAILED`
- `AUTHORIZATION_DENIED`
- `VALIDATION_ERROR`
- `RESOURCE_NOT_FOUND`
- `STATE_CONFLICT`
- `INTEGRATION_FAILURE`
- `RATE_LIMITED`
- `INTERNAL_ERROR`

---

## 9. End-to-End Process Flow

### 9.1 Subscriber Lifecycle
1. Operator creates subscriber
2. System saves subscriber and initial pricing state
3. Optional router provisioning/sync runs
4. Billing engine generates invoice on proper cycle
5. Snapshot/statement is created
6. Reminder is sent before due date
7. Subscriber pays partially or fully
8. Payment is allocated oldest-first
9. Invoice status changes to `partial` or `paid`
10. If unpaid after grace period, invoice becomes `overdue`
11. Subscriber may be suspended
12. Router service is disabled if automation is enabled
13. When balance clears, reconnect workflow restores service

### 9.2 Conditional Branches
- If no effective rate exists, subscriber is skipped from billing
- If snapshot mode is `draft`, admin review is required before freeze
- If router is offline during suspension, enforcement becomes pending and retries
- If payment exceeds balance, unallocated remainder is retained for manual resolution or future credit policy

---

## 10. Automation and Operational Logic

### 10.1 Scheduled Jobs
- Router heartbeat: every `1-5 minutes`
- Interface traffic sampler: every `1-5 minutes`
- Subscriber sync: every `5-15 minutes`
- Usage sampler: every `5 minutes`
- Daily usage rollup: nightly
- Invoice generation: scheduled billing window
- Snapshot generation: after invoice run
- Draft auto-freeze: hourly
- Reminder dispatch: daily/hourly
- Overdue marker: daily
- Auto-suspension: daily/hourly
- Auto-reconnect check: every `15 minutes`
- OTP cleanup: hourly
- Retention cleanup: daily
- Notification retry: every `5 minutes`

### 10.2 Retry Policy
- Router operations: exponential backoff, max attempts, per-router circuit breaker
- SMS: limited retries for transient provider failures
- Telegram: retry on network failure, not on invalid auth
- Billing jobs: idempotency lock by date and scope
- Payment callbacks: deduplicate by external transaction reference

### 10.3 Rate Limiting
- OTP requests per phone and per IP
- OTP verify attempts per session
- Public billing token requests per IP
- Admin login throttle
- Router polling concurrency cap
- Bulk SMS throughput cap

---

## 11. Performance and Scaling

### 11.1 Expected Load
- Subscribers: `5,000` to `100,000`
- Routers: `10` to `500`
- Staff concurrent users: dozens
- Active sessions: thousands to tens of thousands
- Billing spike: one invoice per billable subscriber per cycle

### 11.2 Primary Bottlenecks
- Router polling and API latency
- Mass invoice generation
- Allocation across large unpaid histories
- Notification spikes around due dates
- Growth of usage and traffic snapshot tables

### 11.3 Scaling Strategy
- Start with vertical scaling
- Add multiple stateless app instances behind a load balancer
- Use dedicated worker pools for billing, sync, and messaging
- Partition or archive large time-series tables
- Add read replicas if heavy reporting requires it

### 11.4 Caching
- Cache settings singletons with explicit invalidation
- Cache dashboard counters and short-lived summaries
- Avoid caching financial write paths
- Use aggregate/materialized reporting strategies if needed

---

## 12. Security

### 12.1 Authentication and Authorization
- Strong password hashing
- Optional MFA for admins
- Role-based access checks on every sensitive action
- Separate portal and staff auth contexts
- Revocable, scoped API tokens for integrations

### 12.2 Data Protection
- Encrypt stored secrets:
  - router passwords
  - SMS API keys
  - Telegram bot token
- Hash OTP values in hardened production implementation
- Mask secrets in logs and UI
- Protect sessions with secure, HTTP-only cookies

### 12.3 Network Security
- Restrict router API access to worker hosts
- Segment app, DB, Redis, and network devices
- Enforce HTTPS publicly
- Add admin IP allowlisting where feasible

### 12.4 Abuse Prevention
- Login and OTP throttling
- CSRF protection
- Public token route throttling
- Duplicate payment detection
- Audit and alerting on repeated failures or anomalous usage

---

## 13. Edge Cases and Failure Handling

### 13.1 Network Failure
- Router unreachable:
  - do not erase prior known state
  - mark router `offline`
  - retry asynchronously
- SMS outage:
  - keep OTP/request state
  - record failed dispatch
  - allow controlled resend

### 13.2 Partial System Failure
- Payment created but allocations fail:
  - wrap in one DB transaction
  - rollback entire operation on failure
- Invoice created but reminder fails:
  - invoice remains valid
  - notification retries separately
- Suspension DB state updated but router action fails:
  - mark enforcement pending
  - retry until success or manual review

### 13.3 Data Inconsistency
- Router shows online while subscriber is disconnected:
  - flag anomaly
  - require operator review or policy-driven correction
- Missing rate history for historical bill:
  - fall back to invoice snapshot data
  - record integrity warning
- Duplicate callback from payment provider:
  - reject via idempotency rule

### 13.4 Recovery Strategy
- PITR-enabled PostgreSQL backups
- Daily reconciliation jobs
- Job locking and idempotency
- Retry queues and dead-letter handling
- Audit logs for repairability of manual actions

---

## 14. Deployment and Infrastructure

### 14.1 Environments
- `Development`
- `Staging`
- `Production`

### 14.2 Required Services
- Application runtime
- PostgreSQL
- Redis
- Reverse proxy
- Background worker
- Scheduler/beat process
- Monitoring stack
- Optional object storage for exports/backups

### 14.3 CI/CD Flow
1. Push branch
2. Run lint, tests, migration checks, and security scan
3. Build deployable artifact/container
4. Deploy to staging
5. Run smoke tests
6. Approve production deployment
7. Apply migrations
8. Run post-deploy health checks
9. Emit deployment notification

### 14.4 Monitoring Stack
- Metrics: Prometheus
- Dashboards: Grafana
- Error Tracking: Sentry
- Logs: Loki or ELK
- Uptime Checks: external monitor
- Queue Monitoring: worker backlog, retry count, dead-letter volume

---

## 15. Implementation Roadmap

### Phase 1: Foundation
- Auth and RBAC
- Audit logging
- Settings singletons
- Base DB schema
- Queue and scheduler infrastructure
- Health checks and observability baseline

Expected output:
- deployable secure foundation with shared operational controls

Dependencies:
- PostgreSQL
- Redis
- secrets management
- CI pipeline

### Phase 2: Core Features
- Subscriber CRUD
- Plan management
- Router registry and connectivity testing
- Subscriber sync
- Invoice generation
- Payment posting and allocation
- Portal OTP
- SMS and Telegram dispatch

Expected output:
- end-to-end operational core from onboarding to payment tracking

Dependencies:
- Phase 1
- MikroTik integration
- SMS provider credentials

### Phase 3: Advanced Features
- Billing snapshots
- Overdue and auto-suspension
- Auto-reconnect
- Usage sampling and rollups
- Interface traffic monitoring
- Accounting dashboards
- Reconciliation jobs

Expected output:
- operational automation, statements, and monitoring maturity

Dependencies:
- stable billing core
- worker tuning
- retention policies

### Phase 4: Optimization
- Dashboard caching
- archive/partition large time-series data
- live updates where valuable
- MFA and security hardening
- scaling and performance tuning
- advanced anomaly detection

Expected output:
- production-hardened and scale-ready platform

Dependencies:
- real traffic metrics
- production error history
- performance profiling results

---

## 16. Acceptance Criteria

### Core Acceptance Criteria
- No duplicate invoice for same subscriber and billing cycle
- Payment posting and allocation are atomic
- Router sync never overwrites admin-owned subscriber fields
- OTP is expiring, single-use, and throttle-protected
- Suspension/reconnect actions are auditable
- Public billing links are opaque and hard to guess
- Scheduled jobs cannot double-run without detection
- Historical financial state remains reconstructable after plan changes

### Operational Acceptance Criteria
- Billing cycle runs successfully for target subscriber count within defined window
- Router polling failures are visible in monitoring
- Notification failures do not block core business transactions
- Overdue processing produces consistent status updates
- Portal shows current statement and recent payments accurately

### Recommended Repo Documentation Split
- `docs/00_product_requirements.md`
- `docs/01_architecture.md`
- `docs/02_data_model.md`
- `docs/03_api_spec.md`
- `docs/04_subscriber_lifecycle.md`
- `docs/05_billing_and_payments.md`
- `docs/06_router_and_monitoring.md`
- `docs/07_notifications_and_portal.md`
- `docs/08_security_and_observability.md`
- `docs/09_implementation_roadmap.md`
