from decimal import Decimal
from datetime import date, timedelta
import calendar
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from apps.billing.models import Invoice, Payment, PaymentAllocation, BillingSnapshot, BillingSnapshotItem
from apps.settings_app.models import BillingSettings


# ── Period Calculation ─────────────────────────────────────────────────────────

def get_effective_cutoff_date(cutoff_day, year, month):
    day = max(1, min(int(cutoff_day), 31))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _shift_month(year, month, delta):
    absolute_month = year * 12 + (month - 1) + delta
    return absolute_month // 12, absolute_month % 12 + 1


def get_next_cutoff_period(cutoff_day, reference_date=None):
    """
    Returns (period_start, period_end) for the next advance-billed cycle.
    If the configured cutoff is not present in a month, the month-end date is used.
    """
    today = reference_date or date.today()
    current_cutoff = get_effective_cutoff_date(cutoff_day, today.year, today.month)

    if today >= current_cutoff:
        period_start = current_cutoff + timedelta(days=1)
        end_year, end_month = _shift_month(current_cutoff.year, current_cutoff.month, 1)
        period_end = get_effective_cutoff_date(cutoff_day, end_year, end_month)
    else:
        start_year, start_month = _shift_month(current_cutoff.year, current_cutoff.month, -1)
        previous_cutoff = get_effective_cutoff_date(cutoff_day, start_year, start_month)
        period_start = previous_cutoff + timedelta(days=1)
        period_end = current_cutoff

    return period_start, period_end


def get_current_cutoff_period(cutoff_day, reference_date=None):
    """
    Returns the service cycle containing reference_date.
    Used for postpaid billing where the bill is due at the end of the cycle.
    """
    today = reference_date or date.today()
    current_cutoff = get_effective_cutoff_date(cutoff_day, today.year, today.month)

    if today <= current_cutoff:
        start_year, start_month = _shift_month(current_cutoff.year, current_cutoff.month, -1)
        previous_cutoff = get_effective_cutoff_date(cutoff_day, start_year, start_month)
        return previous_cutoff + timedelta(days=1), current_cutoff

    end_year, end_month = _shift_month(current_cutoff.year, current_cutoff.month, 1)
    next_cutoff = get_effective_cutoff_date(cutoff_day, end_year, end_month)
    return current_cutoff + timedelta(days=1), next_cutoff


def get_effective_rate_at(subscriber, as_of_date=None):
    """
    Returns the billing rate that was active on as_of_date.
    Source of truth: RateHistory entries, fallback to subscriber fields.
    """
    from apps.subscribers.models import RateHistory
    return RateHistory.get_effective_rate(subscriber, as_of_date)


def resolve_cutoff_day(subscriber, billing_settings=None):
    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()
    return subscriber.cutoff_day if subscriber.cutoff_day is not None else billing_settings.billing_day


def resolve_due_offset_days(subscriber, billing_settings=None):
    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()

    if subscriber.billing_due_days is not None:
        return subscriber.billing_due_days
    return billing_settings.billing_due_offset_days or billing_settings.due_days or 0


def get_cutoff_day_queryset_filter(target_day, billing_settings=None, target_date=None):
    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()
    target_date = target_date or date.today()

    effective_cutoff_days = [
        day for day in range(1, 32)
        if get_effective_cutoff_date(day, target_date.year, target_date.month).day == target_day
    ]

    query = Q(cutoff_day__in=effective_cutoff_days)
    default_cutoff = get_effective_cutoff_date(
        billing_settings.billing_day,
        target_date.year,
        target_date.month,
    )
    if default_cutoff.day == target_day:
        query |= Q(cutoff_day__isnull=True)
    return query


def resolve_billing_profile(subscriber, billing_settings=None, reference_date=None):
    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()

    today = reference_date or date.today()
    cutoff_day = resolve_cutoff_day(subscriber, billing_settings)
    billing_type = getattr(subscriber, 'billing_type', 'postpaid')
    if billing_type == 'prepaid':
        period_start, period_end = get_next_cutoff_period(cutoff_day, today)
        due_base = period_start
        generation_date = period_start - timedelta(days=1)
    else:
        billing_type = 'postpaid'
        period_start, period_end = get_current_cutoff_period(cutoff_day, today)
        due_base = period_end
        generation_date = period_end

    cutoff_date = period_end
    due_offset = resolve_due_offset_days(subscriber, billing_settings)
    due_date = due_base + timedelta(days=due_offset)
    effective_from = subscriber.billing_effective_from or subscriber.start_date

    return {
        'billing_type': billing_type,
        'cutoff_day': cutoff_day,
        'period_start': period_start,
        'period_end': period_end,
        'cutoff_date': cutoff_date,
        'generation_date': generation_date,
        'due_offset_days': due_offset,
        'due_date': due_date,
        'effective_from': effective_from,
    }


# ── Billing Preview ────────────────────────────────────────────────────────────

def get_account_credit_for_subscriber(subscriber):
    payment_total = Payment.objects.filter(subscriber=subscriber).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    allocated_total = PaymentAllocation.objects.filter(
        payment__subscriber=subscriber
    ).aggregate(
        total=Sum('amount_allocated')
    )['total'] or Decimal('0.00')
    return max(payment_total - allocated_total, Decimal('0.00'))


def _apply_payment_status(invoice):
    if invoice.status in ('voided', 'waived'):
        return
    if invoice.amount_paid >= invoice.amount:
        invoice.status = 'paid'
    elif invoice.amount_paid > Decimal('0.00'):
        invoice.status = 'partial'
    else:
        invoice.status = 'open'


def apply_unallocated_payments_to_invoice(invoice):
    """
    Applies existing unallocated payments to the invoice oldest-first.
    This turns early payments into actual allocations once the invoice exists.
    """
    if invoice.status in ('paid', 'voided', 'waived') or invoice.remaining_balance <= Decimal('0.00'):
        return Decimal('0.00')

    applied = Decimal('0.00')
    payments = Payment.objects.filter(
        subscriber=invoice.subscriber,
    ).order_by('paid_at', 'created_at', 'pk')

    for payment in payments:
        if invoice.remaining_balance <= Decimal('0.00'):
            break
        if PaymentAllocation.objects.filter(payment=payment, invoice=invoice).exists():
            continue

        available = payment.unallocated_amount
        if available <= Decimal('0.00'):
            continue

        allocate = min(available, invoice.remaining_balance)
        if allocate <= Decimal('0.00'):
            continue

        PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount_allocated=allocate,
        )
        invoice.amount_paid += allocate
        applied += allocate
        _apply_payment_status(invoice)
        invoice.save(update_fields=['amount_paid', 'status', 'updated_at'])

    return applied


def get_billing_preview_for_subscriber(subscriber, billing_settings=None,
                                       sms_settings=None, reference_date=None):
    """
    Read-only billing preview for queues/calendars.
    Does not create invoices, snapshots, payments, allocations, or SMS logs.
    """
    from apps.settings_app.models import SMSSettings

    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()
    if sms_settings is None:
        sms_settings = SMSSettings.get_settings()

    today = reference_date or date.today()
    profile = resolve_billing_profile(subscriber, billing_settings, today)
    rate = get_effective_rate_at(subscriber, today)
    from apps.subscribers.services import get_subscriber_billing_readiness
    readiness = get_subscriber_billing_readiness(
        subscriber,
        billing_settings=billing_settings,
        reference_date=today,
    )
    errors = []
    flags = []

    if not readiness['billing_ready']:
        errors.extend(readiness['billing_issues'])
        flags.append('billing_setup_incomplete')
        if not subscriber.can_generate_billing:
            flags.append('not_billable')

    effective_from = profile['effective_from']
    if effective_from and today < effective_from:
        errors.append(f"Billing starts on {effective_from}.")
        flags.append('billing_not_effective')

    if rate is None and 'Missing plan or monthly rate.' not in errors:
        errors.append('No rate set.')
        flags.append('missing_rate')

    current_invoice = Invoice.objects.filter(
        subscriber=subscriber,
        period_start=profile['period_start'],
    ).first()

    snapshot = BillingSnapshot.objects.filter(
        subscriber=subscriber,
        period_start=profile['period_start'],
        cutoff_date=profile['cutoff_date'],
    ).order_by('-created_at').first()

    current_charge = current_invoice.amount if current_invoice else (rate or Decimal('0.00'))
    current_balance = current_invoice.remaining_balance if current_invoice else current_charge

    previous_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    ).exclude(
        period_start=profile['period_start'],
    ).order_by('period_start')

    previous_balance = sum((inv.remaining_balance for inv in previous_invoices), Decimal('0.00'))
    account_credit = get_account_credit_for_subscriber(subscriber)
    gross_due = current_balance + previous_balance
    credit_applied = min(account_credit, gross_due)
    total_due = max(gross_due - credit_applied, Decimal('0.00'))
    remaining_credit = max(account_credit - credit_applied, Decimal('0.00'))

    if current_invoice:
        flags.append('invoice_exists')
    else:
        flags.append('invoice_missing')

    if snapshot:
        flags.append(f'snapshot_{snapshot.status}')
    else:
        flags.append('snapshot_missing')

    if account_credit > Decimal('0.00'):
        flags.append('has_account_credit')
    if total_due == Decimal('0.00') and gross_due > Decimal('0.00'):
        flags.append('credit_covered')

    from apps.sms.services import get_billing_sms_schedule_state
    sms_state = get_billing_sms_schedule_state(
        snapshot=snapshot,
        subscriber=subscriber,
        due_date=profile['due_date'],
        total_due=total_due,
        sms_settings=sms_settings,
        reference_date=today,
    )

    if sms_state['eligible_today']:
        flags.append('sms_eligible_today')
    elif sms_state['skip_reason']:
        flags.append(sms_state['skip_reason'])

    can_generate = not errors
    if can_generate and current_invoice is None:
        flags.append('ready_to_generate_invoice')
    if can_generate and snapshot is None:
        flags.append('ready_to_generate_snapshot')

    return {
        'subscriber': subscriber,
        'can_generate': can_generate,
        'readiness': readiness,
        'errors': errors,
        'flags': flags,
        'profile': profile,
        'billing_type': profile['billing_type'],
        'cutoff_day': profile['cutoff_day'],
        'period_start': profile['period_start'],
        'period_end': profile['period_end'],
        'cutoff_date': profile['cutoff_date'],
        'generation_date': profile['generation_date'],
        'due_date': profile['due_date'],
        'due_offset_days': profile['due_offset_days'],
        'rate': rate,
        'current_charge': current_charge,
        'current_balance': current_balance,
        'previous_balance': previous_balance,
        'account_credit': account_credit,
        'credit_applied': credit_applied,
        'remaining_credit': remaining_credit,
        'total_due': total_due,
        'invoice': current_invoice,
        'invoice_status': current_invoice.status if current_invoice else 'missing',
        'snapshot': snapshot,
        'snapshot_status': snapshot.status if snapshot else 'missing',
        'sms': {
            'enabled': sms_state['enabled'],
            'days_before_due': sms_state['days_before_due'],
            'repeat_interval_days': sms_state['repeat_interval_days'],
            'send_after_due': sms_state['send_after_due'],
            'after_due_interval_days': sms_state['after_due_interval_days'],
            'first_sms_date': sms_state['first_sms_date'],
            'next_sms_date': sms_state['next_sms_date'],
            'send_dates': sms_state['send_dates'],
            'eligible_today': sms_state['eligible_today'],
            'skip_reason': sms_state['skip_reason'],
            'reminder_stage': sms_state['reminder_stage'],
            'last_sent_at': sms_state['last_sent_at'],
            'last_attempt_at': sms_state['last_attempt_at'],
            'last_attempt_status': sms_state['last_attempt_status'],
            'sent_today': sms_state['sent_today'],
            'attempted_today': sms_state['attempted_today'],
        },
    }


def get_billing_previews(reference_date=None, subscribers=None,
                         billing_settings=None, sms_settings=None):
    from apps.subscribers.models import Subscriber

    if subscribers is None:
        subscribers = Subscriber.objects.filter(
            status__in=['active', 'suspended'],
            is_billable=True,
        ).select_related('plan')

    return [
        get_billing_preview_for_subscriber(
            subscriber,
            billing_settings=billing_settings,
            sms_settings=sms_settings,
            reference_date=reference_date,
        )
        for subscriber in subscribers
    ]


def get_billing_snapshot_preparation_date(preview):
    preparation_date = preview['generation_date']
    first_sms_date = preview['sms'].get('first_sms_date')
    if preview['sms'].get('enabled') and first_sms_date:
        preparation_date = min(preparation_date, first_sms_date)
    return preparation_date


def should_prepare_billing_snapshot(preview, reference_date=None):
    today = reference_date or date.today()
    if preview['errors'] or preview['snapshot'] is not None:
        return False
    return today >= get_billing_snapshot_preparation_date(preview)


def generate_due_billing_snapshots(billing_settings=None, sms_settings=None,
                                   reference_date=None):
    from apps.subscribers.models import Subscriber
    from apps.settings_app.models import SMSSettings

    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()
    if sms_settings is None:
        sms_settings = SMSSettings.get_settings()
    if billing_settings.billing_snapshot_mode == 'manual':
        return 0, 0, []

    today = reference_date or date.today()
    subscribers = Subscriber.objects.filter(
        status__in=['active', 'suspended'],
        is_billable=True,
    ).select_related('plan')

    created = 0
    skipped = 0
    errors = []
    for subscriber in subscribers:
        preview = get_billing_preview_for_subscriber(
            subscriber,
            billing_settings=billing_settings,
            sms_settings=sms_settings,
            reference_date=today,
        )
        if not should_prepare_billing_snapshot(preview, today):
            skipped += 1
            continue

        snapshot, err = generate_snapshot_for_subscriber(
            subscriber,
            billing_settings=billing_settings,
            reference_date=today,
        )
        if snapshot and err is None:
            created += 1
        elif err and 'already exists' in err:
            skipped += 1
        elif err:
            errors.append(f"{subscriber.username}: {err}")

    return created, skipped, errors


# ── Invoice Generation ─────────────────────────────────────────────────────────

@transaction.atomic
def generate_invoice_for_subscriber(subscriber, billing_settings=None, reference_date=None):
    if not billing_settings:
        billing_settings = BillingSettings.get_settings()

    if not subscriber.can_generate_billing:
        return None, f"Subscriber {subscriber.username} is {subscriber.status}, billing skipped."

    today = reference_date or date.today()
    from apps.subscribers.services import get_subscriber_billing_readiness
    readiness = get_subscriber_billing_readiness(
        subscriber,
        billing_settings=billing_settings,
        reference_date=today,
    )
    if not readiness['billing_ready']:
        return None, f"Subscriber {subscriber.username} is not billing-ready: {'; '.join(readiness['billing_issues'])}"

    profile = resolve_billing_profile(subscriber, billing_settings, today)
    if profile['effective_from'] and today < profile['effective_from']:
        return None, f"Billing for {subscriber.username} starts on {profile['effective_from']}."

    rate = get_effective_rate_at(subscriber, today)

    if rate is None:
        return None, f"No rate set for {subscriber.username}."

    period_start = profile['period_start']
    period_end = profile['period_end']
    due_date = profile['due_date']

    existing = Invoice.objects.filter(
        subscriber=subscriber,
        period_start=period_start,
    ).first()

    if existing:
        apply_unallocated_payments_to_invoice(existing)
        return existing, 'Invoice already exists for this period.'

    try:
        with transaction.atomic():
            invoice = Invoice.objects.create(
                subscriber=subscriber,
                period_start=period_start,
                period_end=period_end,
                due_date=due_date,
                amount=rate,
                rate_snapshot=rate,
            )
    except IntegrityError:
        invoice = Invoice.objects.get(
            subscriber=subscriber,
            period_start=period_start,
        )
        apply_unallocated_payments_to_invoice(invoice)
        return invoice, 'Invoice already exists for this period.'
    apply_unallocated_payments_to_invoice(invoice)

    return invoice, None


@transaction.atomic
def generate_invoices_for_all(billing_settings=None):
    from apps.subscribers.models import Subscriber
    if not billing_settings:
        billing_settings = BillingSettings.get_settings()

    subscribers = Subscriber.objects.filter(
        status__in=['active', 'suspended'],
        is_billable=True,
    ).select_related('plan')
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
    Records a payment, mirrors it into accounting income, and allocates
    oldest-first against open invoices.
    """
    from apps.accounting.services import ensure_income_record_for_payment

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
    ensure_income_record_for_payment(payment)

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
    from apps.subscribers.services import get_subscriber_billing_readiness
    readiness = get_subscriber_billing_readiness(
        subscriber,
        billing_settings=billing_settings,
        reference_date=today,
    )
    if not readiness['billing_ready']:
        return None, f"Subscriber {subscriber.username} is not billing-ready: {'; '.join(readiness['billing_issues'])}"

    profile = resolve_billing_profile(subscriber, billing_settings, today)
    if profile['effective_from'] and today < profile['effective_from']:
        return None, f"Billing for {subscriber.username} starts on {profile['effective_from']}."

    period_start = profile['period_start']
    period_end = profile['period_end']
    due_date = profile['due_date']
    rate = get_effective_rate_at(subscriber, today)

    if rate is None:
        return None, f"No rate for {subscriber.username}."

    existing_snapshot = BillingSnapshot.objects.filter(
        subscriber=subscriber,
        period_start=period_start,
    ).first()
    if existing_snapshot:
        return existing_snapshot, 'Snapshot already exists for this period.'

    invoice, _ = generate_invoice_for_subscriber(subscriber, billing_settings, today)
    preview = get_billing_preview_for_subscriber(
        subscriber,
        billing_settings=billing_settings,
        reference_date=today,
    )

    open_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    ).exclude(
        period_start=period_start,
    ).order_by('period_start')

    current_charge = preview['current_charge']
    previous_balance = preview['previous_balance']
    total_due = preview['total_due']
    credit = max(current_charge + previous_balance - total_due, Decimal('0.00'))

    mode = billing_settings.billing_snapshot_mode
    status = 'frozen' if mode == 'auto' else 'draft'

    try:
        with transaction.atomic():
            snapshot = BillingSnapshot.objects.create(
                subscriber=subscriber,
                cutoff_date=profile['cutoff_date'],
                issue_date=today,
                due_date=profile['due_date'],
                period_start=profile['period_start'],
                period_end=profile['period_end'],
                current_cycle_amount=current_charge,
                previous_balance_amount=previous_balance,
                credit_amount=credit,
                total_due_amount=total_due,
                status=status,
                source='scheduler' if created_by == 'system' else 'manual',
                created_by=created_by,
            )
    except IntegrityError:
        snapshot = BillingSnapshot.objects.get(
            subscriber=subscriber,
            period_start=period_start,
        )
        return snapshot, 'Snapshot already exists for this period.'

    if mode == 'auto':
        snapshot.frozen_at = timezone.now()
        snapshot.save(update_fields=['frozen_at'])

    sort = 0
    BillingSnapshotItem.objects.create(
        snapshot=snapshot,
        item_type='current_charge',
        invoice=invoice,
        label=f"Monthly Service - {profile['period_start'].strftime('%b %d')} to {profile['period_end'].strftime('%b %d, %Y')}",
        period_start=profile['period_start'],
        period_end=profile['period_end'],
        amount=current_charge,
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

    if credit > Decimal('0.00'):
        sort += 1
        BillingSnapshotItem.objects.create(
            snapshot=snapshot,
            item_type='credit',
            invoice=invoice,
            label='Payments / Credits Applied',
            amount=credit,
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
    settings = BillingSettings.get_settings()
    today = date.today()
    cutoff = today - timedelta(days=settings.grace_period_days)
    count = Invoice.objects.filter(
        status__in=['open', 'partial'],
        due_date__lt=cutoff,
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
