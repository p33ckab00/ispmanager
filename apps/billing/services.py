from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from apps.billing.models import Invoice, Payment, PaymentAllocation, BillingSnapshot, BillingSnapshotItem
from apps.settings_app.models import BillingSettings


# ── Period Calculation ─────────────────────────────────────────────────────────

def get_next_cutoff_period(cutoff_day, reference_date=None):
    """
    Returns (period_start, period_end) for the NEXT service cycle.
    Bills in advance: if cutoff is March 19, period is March 20 - April 19.
    """
    today = reference_date or date.today()
    day = min(cutoff_day, 28)

    if today.day >= day:
        period_start = today.replace(day=day) + timedelta(days=1)
    else:
        if today.month == 1:
            period_start = today.replace(year=today.year - 1, month=12, day=day) + timedelta(days=1)
        else:
            period_start = today.replace(month=today.month - 1, day=day) + timedelta(days=1)

    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1, day=day)
    else:
        period_end = period_start.replace(month=period_start.month + 1, day=day)

    return period_start, period_end


def get_effective_rate_at(subscriber, as_of_date=None):
    """
    Returns the billing rate that was active on as_of_date.
    Source of truth: RateHistory entries, fallback to subscriber fields.
    """
    from apps.subscribers.models import RateHistory
    return RateHistory.get_effective_rate(subscriber, as_of_date)


# ── Invoice Generation ─────────────────────────────────────────────────────────

@transaction.atomic
def generate_invoice_for_subscriber(subscriber, billing_settings=None, reference_date=None):
    if not billing_settings:
        billing_settings = BillingSettings.get_settings()

    if not subscriber.can_generate_billing:
        return None, f"Subscriber {subscriber.username} is {subscriber.status}, billing skipped."

    today = reference_date or date.today()
    rate = get_effective_rate_at(subscriber, today)

    if rate is None:
        return None, f"No rate set for {subscriber.username}."

    cutoff_day = subscriber.cutoff_day or billing_settings.billing_day
    period_start, period_end = get_next_cutoff_period(cutoff_day, today)
    due_date = today + timedelta(days=billing_settings.billing_due_offset_days)

    existing = Invoice.objects.filter(
        subscriber=subscriber,
        period_start=period_start,
    ).first()

    if existing:
        return existing, 'Invoice already exists for this period.'

    invoice = Invoice.objects.create(
        subscriber=subscriber,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        amount=rate,
        rate_snapshot=rate,
    )

    return invoice, None


@transaction.atomic
def generate_invoices_for_all(billing_settings=None):
    from apps.subscribers.models import Subscriber
    if not billing_settings:
        billing_settings = BillingSettings.get_settings()

    subscribers = Subscriber.objects.filter(status__in=['active', 'suspended']).select_related('plan')
    created = 0
    skipped = 0
    errors = []

    for sub in subscribers:
        invoice, msg = generate_invoice_for_subscriber(sub, billing_settings)
        if invoice and msg is None:
            created += 1
        elif msg and 'already exists' in msg:
            skipped += 1
        elif msg:
            errors.append(msg)

    return created, skipped, errors


# ── Payment Allocation ─────────────────────────────────────────────────────────

@transaction.atomic
def record_payment_with_allocation(subscriber, amount, method='cash', reference='',
                                    notes='', recorded_by='admin', paid_at=None):
    """
    Records a payment and allocates oldest-first against open invoices.
    """
    if paid_at is None:
        paid_at = timezone.now()

    payment = Payment.objects.create(
        subscriber=subscriber,
        amount=amount,
        method=method,
        reference=reference,
        notes=notes,
        recorded_by=recorded_by,
        paid_at=paid_at,
    )

    remaining = Decimal(str(amount))
    open_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    ).order_by('period_start', 'created_at')

    for invoice in open_invoices:
        if remaining <= Decimal('0.00'):
            break

        balance = invoice.remaining_balance
        allocate = min(remaining, balance)

        PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount_allocated=allocate,
        )

        invoice.amount_paid += allocate
        remaining -= allocate

        if invoice.amount_paid >= invoice.amount:
            invoice.status = 'paid'
        else:
            invoice.status = 'partial'

        invoice.save(update_fields=['amount_paid', 'status', 'updated_at'])

    return payment, remaining


# ── Billing Snapshot Generation ────────────────────────────────────────────────

@transaction.atomic
def generate_snapshot_for_subscriber(subscriber, billing_settings=None,
                                      reference_date=None, created_by='system'):
    if not billing_settings:
        billing_settings = BillingSettings.get_settings()

    if not subscriber.can_generate_billing:
        return None, f"Subscriber {subscriber.username} cannot generate billing."

    today = reference_date or date.today()
    cutoff_day = subscriber.cutoff_day or billing_settings.billing_day
    period_start, period_end = get_next_cutoff_period(cutoff_day, today)
    due_date = today + timedelta(days=billing_settings.billing_due_offset_days)
    rate = get_effective_rate_at(subscriber, today)

    if rate is None:
        return None, f"No rate for {subscriber.username}."

    invoice, _ = generate_invoice_for_subscriber(subscriber, billing_settings, today)

    open_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    ).exclude(
        period_start=period_start,
    ).order_by('period_start')

    previous_balance = sum(inv.remaining_balance for inv in open_invoices)
    credit = Decimal('0.00')
    total_due = rate + previous_balance - credit

    mode = billing_settings.billing_snapshot_mode
    status = 'frozen' if mode == 'auto' else 'draft'

    snapshot = BillingSnapshot.objects.create(
        subscriber=subscriber,
        cutoff_date=today,
        issue_date=today,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        current_cycle_amount=rate,
        previous_balance_amount=previous_balance,
        credit_amount=credit,
        total_due_amount=total_due,
        status=status,
        source='scheduler' if created_by == 'system' else 'manual',
        created_by=created_by,
    )

    if mode == 'auto':
        snapshot.frozen_at = timezone.now()
        snapshot.save(update_fields=['frozen_at'])

    sort = 0
    BillingSnapshotItem.objects.create(
        snapshot=snapshot,
        item_type='current_charge',
        invoice=invoice,
        label=f"Monthly Service - {period_start.strftime('%b %d')} to {period_end.strftime('%b %d, %Y')}",
        period_start=period_start,
        period_end=period_end,
        amount=rate,
        sort_order=sort,
    )

    for inv in open_invoices:
        sort += 1
        BillingSnapshotItem.objects.create(
            snapshot=snapshot,
            item_type='previous_balance',
            invoice=inv,
            label=f"Previous Balance - {inv.invoice_number} ({inv.period_start.strftime('%b %Y')})",
            period_start=inv.period_start,
            period_end=inv.period_end,
            amount=inv.remaining_balance,
            sort_order=sort,
        )

    return snapshot, None


# ── Rate Change Application ────────────────────────────────────────────────────

@transaction.atomic
def apply_rate_change(subscriber, new_plan, new_rate, effective_date,
                       apply_mode, note='', changed_by='admin'):
    from apps.subscribers.models import RateHistory

    old_plan = subscriber.plan
    old_rate = subscriber.monthly_rate

    history = RateHistory.objects.create(
        subscriber=subscriber,
        old_plan=old_plan,
        new_plan=new_plan,
        old_rate=old_rate,
        new_rate=new_rate,
        effective_date=effective_date,
        apply_mode=apply_mode,
        changed_by=changed_by,
        note=note,
    )

    subscriber.plan = new_plan
    subscriber.monthly_rate = new_rate
    subscriber.billing_effective_from = effective_date
    subscriber.save(update_fields=['plan', 'monthly_rate', 'billing_effective_from', 'updated_at'])

    if apply_mode == 'all_unpaid':
        Invoice.objects.filter(
            subscriber=subscriber,
            status__in=['open', 'partial'],
            due_date__gte=effective_date,
        ).update(amount=new_rate, rate_snapshot=new_rate)

    return history


# ── Mark Overdue ───────────────────────────────────────────────────────────────

def mark_overdue_invoices():
    today = date.today()
    count = Invoice.objects.filter(
        status__in=['open', 'partial'],
        due_date__lt=today,
    ).update(status='overdue')
    return count


# ── Void Invoices for Deceased ─────────────────────────────────────────────────

@transaction.atomic
def void_invoices_for_deceased(subscriber, voided_by='admin'):
    updated = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    ).update(
        status='voided',
        void_reason='subscriber_deceased',
        void_note='Auto-voided: subscriber marked deceased',
        voided_at=timezone.now(),
        voided_by=voided_by,
    )
    return updated
