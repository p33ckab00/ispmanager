# Step 04 - subscribers app

## Status: DONE

---

## What Was Built

### New Files

| File | Purpose |
|------|---------|
| apps/subscribers/models.py | Plan, Subscriber, PlanHistory, SubscriberOTP |
| apps/subscribers/services.py | sync_ppp_secrets, sync_active_sessions, record_plan_change |
| apps/subscribers/forms.py | All subscriber + plan forms, OTP forms |
| apps/subscribers/otp.py | generate_otp, create_otp, verify_otp |
| apps/subscribers/views.py | All subscriber, plan, and portal views |
| apps/subscribers/urls.py | All routes |
| apps/subscribers/serializers.py | DRF serializers |
| apps/subscribers/api_views.py | DRF API views |
| apps/subscribers/api_urls.py | /api/v1/subscribers/ routes |
| apps/sms/semaphore.py | Semaphore SMS send function (send_sms, send_bulk_sms) |
| apps/billing/models.py | BillingRecord stub (used by portal dashboard) |
| templates/subscribers/list.html | Searchable paginated subscriber table |
| templates/subscribers/detail.html | Subscriber info, MikroTik info, plan, history |
| templates/subscribers/edit.html | Edit admin-owned fields only |
| templates/subscribers/plan_change.html | Change plan + rate with override and note |
| templates/subscribers/add.html | Manual add form |
| templates/subscribers/plan_list.html | Plan management table |
| templates/subscribers/plan_form.html | Add/edit plan form |
| templates/subscribers/portal_otp_request.html | Client portal: enter phone |
| templates/subscribers/portal_otp_verify.html | Client portal: enter OTP |
| templates/subscribers/portal_dashboard.html | Client portal: account + bills |

---

## Models

### Plan
- name, speed_down_mbps, speed_up_mbps, monthly_rate
- is_active, description

### Subscriber
- MikroTik-owned (updated on sync): username, mt_password, mt_profile, service_type, mac_address, ip_address, mt_status, router, last_synced
- Admin-owned (never overwritten): full_name, phone, address, email, latitude, longitude, plan, monthly_rate, status, notes
- Portal: portal_otp, portal_otp_expires
- effective_rate property: returns monthly_rate if set, else plan.monthly_rate

### PlanHistory
- Tracks every plan or rate change
- Fields: old_plan, new_plan, old_rate, new_rate, change_type, changed_by, note, effective_date
- change_type: plan_change, rate_change, or both
- Latest record is always the active one

### SubscriberOTP
- Linked to subscriber
- code (6 digits), expires_at (+10 minutes), is_used
- Old OTPs invalidated when new one is created

---

## Sync Rules

- Sync key: username (unique)
- MikroTik-owned fields updated on every sync
- Admin-owned fields never touched by sync
- New username not in DB: created with MikroTik fields only, admin fills rest
- Deleted from MikroTik: NOT deleted from DB, status set to offline only
- Active sessions update ip_address and mt_status=online
- Subscribers not in active sessions set to mt_status=offline

---

## Plan Change Rules

- record_plan_change() compares old vs new plan and rate
- If no change detected: returns None, no history written
- change_type auto-detected: plan_change / rate_change / both
- monthly_rate field on subscriber overrides plan.monthly_rate
- Leave monthly_rate blank to follow plan default

---

## Client Portal Flow

1. Client visits /subscribers/portal/
2. Enters phone number
3. OTP generated (6 digits, 10 min expiry)
4. OTP sent via Semaphore SMS (if configured)
5. Client enters OTP at /subscribers/portal/verify/
6. On success: subscriber pk stored in session
7. Portal dashboard shown at /subscribers/portal/dashboard/
8. Shows account info + last 5 bills with pay links

---

## URL Routes

| URL | View | Name |
|-----|------|------|
| /subscribers/ | subscriber_list | subscriber-list |
| /subscribers/add/ | subscriber_add | subscriber-add |
| /subscribers/sync/ | subscriber_sync | subscriber-sync |
| /subscribers/{pk}/ | subscriber_detail | subscriber-detail |
| /subscribers/{pk}/edit/ | subscriber_edit | subscriber-edit |
| /subscribers/{pk}/plan/ | subscriber_plan_change | subscriber-plan-change |
| /subscribers/plans/ | plan_list | plan-list |
| /subscribers/plans/add/ | plan_add | plan-add |
| /subscribers/plans/{pk}/edit/ | plan_edit | plan-edit |
| /subscribers/portal/ | portal_request_otp | portal-request-otp |
| /subscribers/portal/verify/ | portal_verify_otp | portal-verify-otp |
| /subscribers/portal/dashboard/ | portal_dashboard | portal-dashboard |
| /subscribers/portal/logout/ | portal_logout | portal-logout |

---

## Next Step
Step 05: billing app - snapshots, billing link, URL shortener, pro-rated / fixed changes
