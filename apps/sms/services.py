from apps.sms.models import SMSLog
from apps.sms.semaphore import send_sms as semaphore_send
from apps.settings_app.models import SMSSettings


def send_billing_sms(snapshot, sent_by='system'):
    settings = SMSSettings.get_settings()
    subscriber = snapshot.subscriber

    if subscriber.sms_opt_out:
        return None, 'Subscriber opted out of SMS.'

    if not subscriber.phone:
        return None, 'No phone number.'

    from apps.core.models import SystemSetup
    setup = SystemSetup.get_setup()
    short_url = f"http://localhost:8000/b/{snapshot.subscriber.invoices.filter(period_start=snapshot.period_start).first().short_code if snapshot.subscriber.invoices.filter(period_start=snapshot.period_start).exists() else ''}/"

    template = settings.billing_sms_template
    message = template.format(
        name=subscriber.display_name,
        amount=snapshot.total_due_amount,
        currency='PHP',
        due_date=snapshot.due_date.strftime('%b %d, %Y'),
        link=short_url,
        previous_balance=snapshot.previous_balance_amount,
        current_charge=snapshot.current_cycle_amount,
    )

    log = SMSLog.objects.create(
        subscriber=subscriber,
        phone=subscriber.phone,
        message=message,
        sms_type='billing',
        status='pending',
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
    from datetime import date, timedelta
    settings = SMSSettings.get_settings()
    days_before = settings.billing_sms_days_before_due
    target_date = date.today() + timedelta(days=days_before)

    from apps.billing.models import BillingSnapshot
    snapshots = BillingSnapshot.objects.filter(
        status='frozen',
        due_date=target_date,
        subscriber__sms_opt_out=False,
    ).exclude(subscriber__phone='').select_related('subscriber')

    results = []
    for snap in snapshots:
        log, err = send_billing_sms(snap, sent_by=sent_by)
        results.append({'snapshot_id': snap.pk, 'ok': err is None, 'error': err})

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
