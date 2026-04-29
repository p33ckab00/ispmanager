from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.utils import timezone

from apps.sms.models import SMSLog
from apps.sms.semaphore import send_sms as semaphore_send
from apps.settings_app.models import SMSSettings


def get_billing_sms_send_dates(due_date, days_before_due, repeat_interval_days,
                               send_after_due=False, after_due_interval_days=2,
                               reference_date=None):
    first_sms_date = due_date - timedelta(days=max(days_before_due, 0))
    repeat_interval_days = max(repeat_interval_days or 1, 1)
    after_due_interval_days = max(after_due_interval_days or 1, 1)

    send_dates = []
    current = first_sms_date
    while current <= due_date:
        send_dates.append(current)
        current += timedelta(days=repeat_interval_days)

    if due_date not in send_dates:
        send_dates.append(due_date)

    if send_after_due and reference_date and reference_date > due_date:
        current = due_date + timedelta(days=after_due_interval_days)
        while current <= reference_date:
            send_dates.append(current)
            current += timedelta(days=after_due_interval_days)
        send_dates.append(current)

    return sorted(set(send_dates))


def get_billing_snapshot_outstanding_amount(snapshot):
    from apps.billing.models import Invoice
    from apps.billing.services import get_account_credit_for_subscriber

    current_invoice = Invoice.objects.filter(
        subscriber=snapshot.subscriber,
        period_start=snapshot.period_start,
    ).first()
    current_balance = (
        current_invoice.remaining_balance
        if current_invoice
        else snapshot.current_cycle_amount
    )
    previous_balance = sum(
        (
            invoice.remaining_balance
            for invoice in Invoice.objects.filter(
                subscriber=snapshot.subscriber,
                status__in=['open', 'partial', 'overdue'],
            ).exclude(period_start=snapshot.period_start)
        ),
        Decimal('0.00'),
    )
    account_credit = get_account_credit_for_subscriber(snapshot.subscriber)
    gross_due = current_balance + previous_balance
    return max(gross_due - min(account_credit, gross_due), Decimal('0.00'))


def get_billing_sms_schedule_state(snapshot=None, subscriber=None, due_date=None,
                                   total_due=None, sms_settings=None,
                                   reference_date=None,
                                   allow_failed_retry=False):
    sms_settings = sms_settings or SMSSettings.get_settings()
    today = reference_date or timezone.localdate()
    subscriber = subscriber or (snapshot.subscriber if snapshot else None)
    due_date = due_date or (snapshot.due_date if snapshot else None)
    total_due = total_due if total_due is not None else (
        get_billing_snapshot_outstanding_amount(snapshot)
        if snapshot
        else Decimal('0.00')
    )

    days_before_due = sms_settings.billing_sms_days_before_due or 0
    repeat_interval_days = sms_settings.billing_sms_repeat_interval_days or 1
    send_after_due = getattr(sms_settings, 'billing_sms_send_after_due', False)
    after_due_interval_days = getattr(sms_settings, 'billing_sms_after_due_interval_days', 2) or 1
    first_sms_date = due_date - timedelta(days=days_before_due) if due_date else None
    send_dates = (
        get_billing_sms_send_dates(
            due_date,
            days_before_due,
            repeat_interval_days,
            send_after_due=send_after_due,
            after_due_interval_days=after_due_interval_days,
            reference_date=today,
        )
        if due_date
        else []
    )
    last_sent_log = None
    last_attempt_log = None
    attempted_today = False
    sent_today = False
    last_attempt_status = ''

    if snapshot and snapshot.pk:
        attempts = SMSLog.objects.filter(
            billing_snapshot=snapshot,
            sms_type='billing',
        )
        last_sent_log = attempts.filter(status='sent').order_by('-created_at').first()
        last_attempt_log = attempts.order_by('-created_at').first()
        attempted_today = attempts.filter(reminder_run_date=today).exists()
        sent_today = attempts.filter(reminder_run_date=today, status='sent').exists()
        last_attempt_status = last_attempt_log.status if last_attempt_log else ''

    next_sms_date = None
    for send_date in send_dates:
        if send_date >= today:
            next_sms_date = send_date
            break

    reminder_stage = 0
    if today in send_dates:
        reminder_stage = send_dates.index(today) + 1

    skip_reason = ''
    if not sms_settings.enable_billing_sms:
        skip_reason = 'billing_sms_disabled'
    elif total_due <= Decimal('0.00'):
        skip_reason = 'paid_or_credit_covered'
    elif subscriber and subscriber.sms_opt_out:
        skip_reason = 'sms_opt_out'
    elif not subscriber or not subscriber.phone:
        skip_reason = 'missing_phone'
    elif not snapshot or snapshot.status != 'frozen':
        skip_reason = 'frozen_snapshot_missing'
    elif due_date and today < first_sms_date:
        skip_reason = 'before_sms_window'
    elif due_date and today > due_date and not send_after_due:
        skip_reason = 'after_due_date'
    elif sent_today:
        skip_reason = 'already_sent_today'
    elif attempted_today and not (allow_failed_retry and last_attempt_status == 'failed'):
        skip_reason = 'already_attempted_today'
    elif today not in send_dates:
        skip_reason = 'outside_sms_window'

    return {
        'enabled': sms_settings.enable_billing_sms,
        'days_before_due': days_before_due,
        'repeat_interval_days': repeat_interval_days,
        'send_after_due': send_after_due,
        'after_due_interval_days': after_due_interval_days,
        'first_sms_date': first_sms_date,
        'next_sms_date': next_sms_date,
        'send_dates': send_dates,
        'eligible_today': skip_reason == '',
        'skip_reason': skip_reason,
        'reminder_stage': reminder_stage,
        'last_sent_at': last_sent_log.created_at if last_sent_log else None,
        'last_attempt_at': last_attempt_log.created_at if last_attempt_log else None,
        'last_attempt_status': last_attempt_status,
        'sent_today': sent_today,
        'attempted_today': attempted_today,
        'total_due': total_due,
    }


def send_billing_sms(snapshot, sent_by='system', enforce_schedule=False,
                     reference_date=None, allow_failed_retry=False):
    sms_settings = SMSSettings.get_settings()
    subscriber = snapshot.subscriber
    today = reference_date or timezone.localdate()

    state = get_billing_sms_schedule_state(
        snapshot=snapshot,
        sms_settings=sms_settings,
        reference_date=today,
        allow_failed_retry=allow_failed_retry,
    )

    if enforce_schedule and not state['eligible_today']:
        return None, state['skip_reason']

    if subscriber.sms_opt_out:
        return None, 'Subscriber opted out of SMS.'

    if not subscriber.phone:
        return None, 'No phone number.'

    from apps.core.models import SystemSetup
    setup = SystemSetup.get_setup()
    invoice = snapshot.subscriber.invoices.filter(period_start=snapshot.period_start).first()
    short_code = invoice.short_code if invoice else ''
    app_base_url = django_settings.APP_BASE_URL
    short_url = f"{app_base_url}/b/{short_code}/" if short_code else app_base_url

    template = sms_settings.billing_sms_template
    message = template.format(
        name=subscriber.display_name,
        amount=state['total_due'],
        currency='PHP',
        due_date=snapshot.due_date.strftime('%b %d, %Y'),
        link=short_url,
        previous_balance=snapshot.previous_balance_amount,
        current_charge=snapshot.current_cycle_amount,
    )

    log = SMSLog.objects.create(
        subscriber=subscriber,
        billing_snapshot=snapshot,
        phone=subscriber.phone,
        message=message,
        sms_type='billing',
        status='pending',
        reminder_stage=state['reminder_stage'],
        reminder_run_date=today,
        billing_due_date=snapshot.due_date,
        sent_by=sent_by,
    )

    try:
        semaphore_send(subscriber.phone, message)
        log.status = 'sent'
        log.save(update_fields=['status'])
        return log, None
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        log.save(update_fields=['status', 'error_message'])
        return log, str(e)


def send_manual_sms(phone, message, subscriber=None, sent_by='admin', sms_type='manual'):
    if subscriber and subscriber.sms_opt_out:
        return None, 'Subscriber opted out of SMS.'

    log = SMSLog.objects.create(
        subscriber=subscriber,
        phone=phone,
        message=message,
        sms_type=sms_type,
        status='pending',
        sent_by=sent_by,
    )
    try:
        semaphore_send(phone, message)
        log.status = 'sent'
        log.save(update_fields=['status'])
        return log, None
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        log.save(update_fields=['status', 'error_message'])
        return log, str(e)


def send_bulk_billing_sms(sent_by='system'):
    sms_settings = SMSSettings.get_settings()
    today = timezone.localdate()
    latest_due_date = today + timedelta(days=sms_settings.billing_sms_days_before_due or 0)

    from apps.billing.models import BillingSnapshot
    snapshots = BillingSnapshot.objects.filter(
        status='frozen',
        due_date__lte=latest_due_date,
        subscriber__sms_opt_out=False,
    ).exclude(subscriber__phone='').select_related('subscriber')
    if not sms_settings.billing_sms_send_after_due:
        snapshots = snapshots.filter(due_date__gte=today)

    results = []
    for snap in snapshots:
        log, err = send_billing_sms(
            snap,
            sent_by=sent_by,
            enforce_schedule=True,
            reference_date=today,
        )
        skipped = err in {
            'billing_sms_disabled',
            'paid_or_credit_covered',
            'sms_opt_out',
            'missing_phone',
            'frozen_snapshot_missing',
            'before_sms_window',
            'after_due_date',
            'already_sent_today',
            'already_attempted_today',
            'outside_sms_window',
        }
        results.append({
            'snapshot_id': snap.pk,
            'ok': err is None,
            'skipped': skipped,
            'error': err,
        })

    return results


def send_subscriber_billing_sms(subscriber, sent_by='system'):
    from apps.billing.models import BillingSnapshot
    from apps.billing.services import generate_snapshot_for_subscriber

    snapshot = BillingSnapshot.objects.filter(
        subscriber=subscriber,
        status__in=['frozen', 'issued'],
    ).order_by('-cutoff_date', '-created_at').first()

    if snapshot is None:
        snapshot = BillingSnapshot.objects.filter(
            subscriber=subscriber
        ).order_by('-cutoff_date', '-created_at').first()

    if snapshot is None:
        snapshot, err = generate_snapshot_for_subscriber(subscriber, created_by=sent_by)
        if err:
            return None, err, None

    log, err = send_billing_sms(snapshot, sent_by=sent_by)
    return log, err, snapshot


def get_semaphore_balance():
    from apps.settings_app.models import SMSSettings
    import requests
    settings = SMSSettings.get_settings()
    if not settings.semaphore_api_key:
        return None, 'No API key configured.'
    try:
        resp = requests.get(
            f"https://api.semaphore.co/api/v4/account?apikey={settings.semaphore_api_key}",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return data, None
        return None, f"API error: {resp.status_code}"
    except Exception as e:
        return None, str(e)
