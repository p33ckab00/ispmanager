# Step 05 - billing app

## Status: DONE

---

## Current Workflow Guide

For the current `Settings > Billing > Billing Mode` workflow, use
[`docs/44_billing_mode_workflow_guide.md`](44_billing_mode_workflow_guide.md).
This step document contains earlier scaffold notes and some historical model names.

---

## What Was Built

### New Files

| File | Purpose |
|------|---------|
| apps/billing/models.py | BillingRecord, BillingAmendment, Payment models |
| apps/billing/services.py | generate_bill, generate_all, amend_bill, record_payment, mark_overdue, calculate_prorated |
| apps/billing/forms.py | AmendBillForm, PaymentForm, GenerateBillForm |
| apps/billing/views.py | All billing views + public view + short URL redirect |
| apps/billing/urls.py | All billing routes |
| apps/billing/short_urls.py | /b/<short_code>/ route |
| apps/billing/serializers.py | DRF serializers |
| apps/billing/api_views.py | DRF API views |
| apps/billing/api_urls.py | /api/v1/billing/ routes |
| templates/billing/list.html | Billing table with summary cards |
| templates/billing/detail.html | Bill detail with amendments and payments |
| templates/billing/generate.html | Generate all or single subscriber |
| templates/billing/amend.html | Amend with pro-rated calculator shown |
| templates/billing/record_payment.html | Record cash/GCash/bank payment |
| templates/billing/confirm_waive.html | Waive confirmation |
| templates/billing/public_view.html | Public token-based billing page |

---

## Models

### BillingRecord
- subscriber (FK)
- period_start, period_end, due_date
- amount (current), original_amount (at creation)
- amount_change_type: standard / prorated / fixed
- status: unpaid / paid / overdue / waived
- plan_snapshot: plan name at time of generation
- token (32 hex chars, unique) - full URL key
- short_code (6 alphanumeric chars, unique) - for SMS
- paid_at, paid_amount, payment_reference
- is_overdue property: True if unpaid and past due_date
- get_billing_url(): returns /b/{short_code}/
- get_full_billing_url(): returns /billing/view/{token}/
- token and short_code auto-generated on save if blank

### BillingAmendment
- linked to BillingRecord
- amendment_type: prorated / fixed / discount / penalty
- old_amount, new_amount, reason, amended_by, amended_at

### Payment
- linked to BillingRecord
- amount, method (cash/gcash/bank/maya/other)
- reference, notes, recorded_by, paid_at

---

## URL Routes

| URL | View | Auth |
|-----|------|------|
| /billing/ | billing_list | Required |
| /billing/generate/ | billing_generate | Required |
| /billing/{pk}/ | billing_detail | Required |
| /billing/{pk}/amend/ | billing_amend | Required |
| /billing/{pk}/pay/ | billing_record_payment | Required |
| /billing/{pk}/waive/ | billing_waive | Required |
| /billing/view/{token}/ | billing_public_view | Public |
| /b/{short_code}/ | billing_short_url | Public (redirects to full URL) |

---

## Key Behaviors

### Bill Generation
- get_billing_period() computes current period from billing_day setting
- Checks for existing bill in same period before creating
- Uses subscriber.effective_rate (monthly_rate override first, then plan.monthly_rate)
- Subscribers with no plan and no rate are skipped

### Amendment
- amend_bill() creates BillingAmendment record and updates bill.amount
- Paid bills cannot be amended
- calculate_prorated() = full_amount * (remaining_days / total_days)
- Pro-rated amount shown on amend page for reference

### Overdue
- mark_overdue_bills() called on billing list page load
- Sets status=overdue where status=unpaid and due_date < today

### Short URL
- /b/XXXX/ redirects to /billing/view/{token}/
- Token-based page is fully public (no login)
- Token = 32 hex chars (very hard to guess)
- Short code = 6 alphanumeric (for SMS character savings)

### Payment
- record_payment() sets bill.status=paid, records paid_at, paid_amount
- Supports: cash, GCash, bank transfer, Maya, other
- Reference field for GCash ref numbers etc.

---

## API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | /api/v1/billing/ | List all bills |
| GET | /api/v1/billing/{pk}/ | Bill detail |
| POST | /api/v1/billing/generate/ | Generate all bills |
| POST | /api/v1/billing/{pk}/pay/ | Record payment |
| POST | /api/v1/billing/mark-overdue/ | Mark overdue bills |

---

## Next Step
Step 06: accounting app - income tracking, expense recording, reports
