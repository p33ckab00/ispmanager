from datetime import date
from django.utils import timezone
from apps.subscribers.models import (
    Subscriber,
    RateHistory,
    SubscriberUsageSample,
    SubscriberUsageDaily,
    SubscriberUsageCutoffSnapshot,
    normalize_phone_digits,
)
from apps.routers import mikrotik


MIKROTIK_FIELDS = ['mt_password', 'mt_profile', 'mac_address', 'ip_address', 'mt_status', 'service_type']

SUBSCRIBER_BILLING_AUDIT_FIELDS = {
    'cutoff_day',
    'billing_effective_from',
    'billing_type',
    'billing_due_days',
    'is_billable',
    'start_date',
    'sms_opt_out',
}

SUBSCRIBER_FIELD_AUDIT_LABELS = {
    'full_name': 'Full name',
    'phone': 'Phone',
    'address': 'Address',
    'email': 'Email',
    'latitude': 'Latitude',
    'longitude': 'Longitude',
    'cutoff_day': 'Cutoff day',
    'billing_effective_from': 'Billing effective from',
    'billing_type': 'Billing type',
    'billing_due_days': 'Billing due offset',
    'is_billable': 'Billable',
    'start_date': 'Start date',
    'notes': 'Notes',
    'sms_opt_out': 'SMS opt-out',
}


def user_has_subscriber_permission(user, permission_codename):
    if not user or not user.is_authenticated:
        return False
    return user.has_perm(f"subscribers.{permission_codename}")


def _format_audit_value(value):
    if value in (None, ''):
        return '-'
    return str(value)


def audit_subscriber_field_changes(before, after, fields, user=None):
    from apps.core.models import AuditLog

    logged = 0
    for field in fields:
        old_value = getattr(before, field, None)
        new_value = getattr(after, field, None)
        if old_value == new_value:
            continue

        label = SUBSCRIBER_FIELD_AUDIT_LABELS.get(field, field.replace('_', ' ').title())
        AuditLog.log(
            'update',
            'subscribers',
            (
                f"{after.username} field changed: {label} "
                f"from '{_format_audit_value(old_value)}' "
                f"to '{_format_audit_value(new_value)}'"
            ),
            user=user,
        )
        logged += 1
    return logged


def get_subscriber_billing_readiness(subscriber, billing_settings=None, reference_date=None):
    """
    Returns setup/readiness state for billing and SMS.
    Billing readiness intentionally does not require a phone number; SMS readiness does.
    """
    from apps.settings_app.models import BillingSettings

    if billing_settings is None:
        billing_settings = BillingSettings.get_settings()

    today = reference_date or date.today()
    billing_issues = []
    sms_issues = []

    if not subscriber.is_billable:
        billing_issues.append('Billing is disabled for this subscriber.')
    if subscriber.status not in ('active', 'suspended'):
        billing_issues.append(f"Subscriber status is {subscriber.get_status_display()}.")

    if subscriber.pk:
        rate = RateHistory.get_effective_rate(subscriber, today)
    else:
        rate = subscriber.effective_rate
    if rate is None:
        billing_issues.append('Missing plan or monthly rate.')

    effective_from = subscriber.billing_effective_from or subscriber.start_date
    if effective_from is None:
        billing_issues.append('Missing service start date or billing effective date.')

    cutoff_day = subscriber.cutoff_day if subscriber.cutoff_day is not None else billing_settings.billing_day
    try:
        cutoff_day = int(cutoff_day)
    except (TypeError, ValueError):
        billing_issues.append('Invalid cutoff day.')
        cutoff_day = None
    else:
        if not 1 <= cutoff_day <= 31:
            billing_issues.append('Cutoff day must be between 1 and 31.')

    if subscriber.billing_type not in ('postpaid', 'prepaid'):
        billing_issues.append('Billing type must be postpaid or prepaid.')

    phone_digits = subscriber.normalized_phone or normalize_phone_digits(subscriber.phone)
    if subscriber.sms_opt_out:
        sms_issues.append('Subscriber opted out of SMS.')
    if not phone_digits:
        sms_issues.append('Missing phone number.')
    elif len(phone_digits) < 10:
        sms_issues.append('Phone number looks incomplete.')
    elif subscriber.pk and Subscriber.objects.filter(
        normalized_phone=phone_digits,
    ).exclude(pk=subscriber.pk).exists():
        sms_issues.append('Phone number is shared with another subscriber.')

    billing_ready = not billing_issues
    sms_ready = billing_ready and not sms_issues

    if billing_ready and sms_ready:
        status = 'ready'
        label = 'Billing and SMS ready'
        badge_classes = 'bg-green-100 text-green-700'
    elif billing_ready:
        status = 'billing_ready_sms_attention'
        label = 'Billing ready, SMS attention'
        badge_classes = 'bg-amber-100 text-amber-700'
    else:
        status = 'needs_setup'
        label = 'Needs billing setup'
        badge_classes = 'bg-red-100 text-red-600'

    return {
        'billing_ready': billing_ready,
        'sms_ready': sms_ready,
        'status': status,
        'label': label,
        'badge_classes': badge_classes,
        'billing_issues': billing_issues,
        'sms_issues': sms_issues,
        'issues': billing_issues + sms_issues,
        'rate': rate,
        'effective_from': effective_from,
        'resolved_cutoff_day': cutoff_day,
    }


# ── Sync ───────────────────────────────────────────────────────────────────────

def sync_ppp_secrets(router):
    try:
        secrets = mikrotik.get_ppp_secrets(router)
    except Exception as e:
        return 0, 0, str(e)

    added = 0
    updated = 0

    for secret in secrets:
        username = secret.get('name', '').strip()
        if not username:
            continue

        service = secret.get('service', 'pppoe')
        profile = secret.get('profile', 'default')
        password = secret.get('password', '')
        existing = Subscriber.objects.filter(username=username).first()

        if existing:
            existing.mt_password = password
            existing.mt_profile = profile
            existing.service_type = service if service in ['pppoe', 'hotspot', 'dhcp'] else 'pppoe'
            existing.router = router
            existing.last_synced = timezone.now()
            existing.save(update_fields=['mt_password', 'mt_profile', 'service_type', 'router', 'last_synced'])
            updated += 1
        else:
            Subscriber.objects.create(
                router=router,
                username=username,
                mt_password=password,
                mt_profile=profile,
                service_type=service if service in ['pppoe', 'hotspot', 'dhcp'] else 'pppoe',
                status='inactive',
                is_billable=False,
                notes='Imported from MikroTik sync. Complete subscriber and billing setup before activation.',
                last_synced=timezone.now(),
            )
            added += 1

    return added, updated, None


def sync_active_sessions(router):
    try:
        sessions = mikrotik.get_ppp_active(router)
    except Exception as e:
        return str(e)

    active_usernames = set()
    for session in sessions:
        username = session.get('name', '').strip()
        if not username:
            continue
        active_usernames.add(username)
        ip = session.get('address', None)
        Subscriber.objects.filter(username=username).update(ip_address=ip, mt_status='online')

    Subscriber.objects.filter(router=router).exclude(username__in=active_usernames).update(mt_status='offline')
    return None


# ── MikroTik PPP Suspend / Reconnect ──────────────────────────────────────────

def suspend_on_mikrotik(subscriber):
    from apps.settings_app.models import SubscriberSettings
    settings = SubscriberSettings.get_settings()

    if not settings.mikrotik_auto_suspend:
        return False, 'MikroTik auto-suspend is disabled in Settings.'

    if not subscriber.router:
        return False, 'No router assigned to subscriber.'

    return set_subscriber_mikrotik_access(subscriber, disabled=True)


def reconnect_on_mikrotik(subscriber):
    from apps.settings_app.models import SubscriberSettings
    settings = SubscriberSettings.get_settings()

    if not settings.mikrotik_auto_reconnect:
        return False, 'MikroTik auto-reconnect is disabled in Settings.'

    if not subscriber.router:
        return False, 'No router assigned to subscriber.'

    return set_subscriber_mikrotik_access(subscriber, disabled=False)


def set_subscriber_mikrotik_access(subscriber, disabled=True):
    action = 'suspend' if disabled else 'reconnect'
    service_type = subscriber.service_type or 'pppoe'

    if service_type == 'pppoe':
        return mikrotik.set_ppp_secret_disabled(
            subscriber.router,
            subscriber.username,
            disabled=disabled,
        )
    if service_type == 'hotspot':
        return mikrotik.set_hotspot_user_disabled(
            subscriber.router,
            subscriber.username,
            disabled=disabled,
        )
    if service_type == 'dhcp':
        return mikrotik.set_dhcp_lease_disabled(
            subscriber.router,
            username=subscriber.username,
            mac_address=subscriber.mac_address,
            ip_address=subscriber.ip_address,
            disabled=disabled,
        )
    if service_type == 'static':
        return False, (
            f"Static subscriber auto-{action} is not configured. "
            "Use a DHCP lease, PPPoE, Hotspot account, or add a firewall/address-list policy first."
        )

    return False, f"Unsupported MikroTik service type for auto-{action}: {service_type}."


# ── Subscriber Status Lifecycle ────────────────────────────────────────────────

SERVICEABLE_STATUSES = ('active', 'inactive', 'suspended')
TERMINAL_STATUSES = ('disconnected', 'deceased', 'archived')


def _clear_suspension_hold(subscriber):
    subscriber.suspension_hold_until = None
    subscriber.suspension_hold_reason = ''
    subscriber.suspension_hold_by = ''
    subscriber.suspension_hold_created_at = None


def _status_label(status):
    return dict(Subscriber.STATUS_CHOICES).get(status, status)


def suspend_subscriber(subscriber, suspended_by='admin'):
    old_status = subscriber.status
    ok, err = suspend_on_mikrotik(subscriber)
    subscriber.status = 'suspended'
    _clear_suspension_hold(subscriber)
    subscriber.save(update_fields=[
        'status',
        'suspension_hold_until',
        'suspension_hold_reason',
        'suspension_hold_by',
        'suspension_hold_created_at',
        'updated_at',
    ])

    from apps.core.models import AuditLog
    AuditLog.log(
        'update',
        'subscribers',
        f"{subscriber.username} status {old_status} -> suspended by {suspended_by}",
    )

    from apps.notifications.telegram import notify_event
    notify_event('subscriber_status', f"Subscriber Suspended",
                 f"{subscriber.display_name} ({subscriber.username}) has been suspended.")

    return ok, err


def reconnect_subscriber(subscriber, reconnected_by='admin'):
    old_status = subscriber.status
    ok, err = reconnect_on_mikrotik(subscriber)
    subscriber.status = 'active'
    _clear_suspension_hold(subscriber)
    subscriber.save(update_fields=[
        'status',
        'suspension_hold_until',
        'suspension_hold_reason',
        'suspension_hold_by',
        'suspension_hold_created_at',
        'updated_at',
    ])

    from apps.core.models import AuditLog
    AuditLog.log(
        'update',
        'subscribers',
        f"{subscriber.username} status {old_status} -> active by {reconnected_by}",
    )

    from apps.notifications.telegram import notify_event
    notify_event('subscriber_status', 'Subscriber Reconnected',
                 f"{subscriber.display_name} ({subscriber.username}) has been reconnected.")

    return ok, err


def deactivate_subscriber(subscriber, deactivated_by='admin', reason=''):
    old_status = subscriber.status
    ok, err = suspend_on_mikrotik(subscriber)
    subscriber.status = 'inactive'
    _clear_suspension_hold(subscriber)
    subscriber.save(update_fields=[
        'status',
        'suspension_hold_until',
        'suspension_hold_reason',
        'suspension_hold_by',
        'suspension_hold_created_at',
        'updated_at',
    ])

    from apps.core.models import AuditLog
    note = f": {reason}" if reason else ''
    AuditLog.log(
        'update',
        'subscribers',
        f"{subscriber.username} status {old_status} -> inactive by {deactivated_by}{note}",
    )

    from apps.notifications.telegram import notify_event
    notify_event(
        'subscriber_status',
        'Subscriber Deactivated',
        f"{subscriber.display_name} ({subscriber.username}) has been marked inactive.",
    )

    return ok, err


def transition_subscriber_status(subscriber, target_status, changed_by='admin', reason=''):
    """
    Formal non-terminal status transition router.
    Terminal statuses must use disconnect/deceased/archive workflows.
    """
    target_status = (target_status or '').strip()
    current_status = subscriber.status

    if target_status == current_status:
        return True, None

    if current_status in TERMINAL_STATUSES or target_status in TERMINAL_STATUSES:
        return False, (
            f"Use the dedicated workflow for {_status_label(current_status)} "
            f"to {_status_label(target_status)} status changes."
        )

    if target_status not in SERVICEABLE_STATUSES:
        return False, f"Unsupported subscriber status: {target_status}."

    if target_status == 'active':
        return reconnect_subscriber(subscriber, reconnected_by=changed_by)
    if target_status == 'suspended':
        return suspend_subscriber(subscriber, suspended_by=changed_by)
    if target_status == 'inactive':
        return deactivate_subscriber(subscriber, deactivated_by=changed_by, reason=reason)

    return False, f"Unsupported subscriber status: {target_status}."


def disconnect_subscriber(subscriber, reason='', disconnected_by='admin'):
    from apps.billing.services import (
        apply_disconnected_billing_policy,
        apply_disconnected_credit_policy,
    )

    billing_result = apply_disconnected_billing_policy(
        subscriber,
        disconnected_by=disconnected_by,
    )
    credit_result = apply_disconnected_credit_policy(
        subscriber,
        disconnected_by=disconnected_by,
    )
    ok, err = suspend_on_mikrotik(subscriber)
    subscriber.status = 'disconnected'
    subscriber.disconnected_date = date.today()
    subscriber.disconnected_reason = reason
    _clear_suspension_hold(subscriber)
    subscriber.save(update_fields=[
        'status',
        'disconnected_date',
        'disconnected_reason',
        'suspension_hold_until',
        'suspension_hold_reason',
        'suspension_hold_by',
        'suspension_hold_created_at',
        'updated_at',
    ])

    from apps.core.models import AuditLog
    AuditLog.log('update', 'subscribers', f"{subscriber.username} disconnected: {reason}")

    from apps.notifications.telegram import notify_event
    notify_event('subscriber_status', 'Subscriber Disconnected',
                 f"{subscriber.display_name} ({subscriber.username}) has been disconnected. Reason: {reason}")

    return ok, err, billing_result, credit_result


def mark_deceased(subscriber, deceased_date=None, note='', marked_by='admin'):
    from apps.billing.services import void_invoices_for_deceased
    suspend_on_mikrotik(subscriber)
    subscriber.status = 'deceased'
    subscriber.deceased_date = deceased_date or date.today()
    subscriber.deceased_note = note
    _clear_suspension_hold(subscriber)
    subscriber.save(update_fields=[
        'status',
        'deceased_date',
        'deceased_note',
        'suspension_hold_until',
        'suspension_hold_reason',
        'suspension_hold_by',
        'suspension_hold_created_at',
        'updated_at',
    ])
    voided = void_invoices_for_deceased(subscriber, voided_by=marked_by)

    from apps.core.models import AuditLog
    AuditLog.log('update', 'subscribers',
                 f"{subscriber.username} marked deceased. {voided} invoices voided.")

    from apps.notifications.telegram import notify_event
    notify_event('subscriber_status', 'Subscriber Deceased',
                 f"{subscriber.display_name} ({subscriber.username}) marked as deceased. {voided} open invoices voided.")


def archive_subscriber(subscriber):
    subscriber.status = 'archived'
    subscriber.save(update_fields=['status', 'updated_at'])


# ── Usage Sampling ─────────────────────────────────────────────────────────────

def sample_subscriber_usage(router):
    """
    Called by scheduler every 5 minutes.
    Pulls PPP active sessions and records usage deltas.
    Handles brownout/reset detection.
    """
    from apps.settings_app.models import UsageSettings
    settings = UsageSettings.get_settings()
    if not settings.enabled:
        return 0

    try:
        sessions = mikrotik.get_ppp_active(router, include_stats=True)
    except Exception:
        return 0

    try:
        pppoe_interface_stats = mikrotik.get_pppoe_interface_stats(router)
    except Exception:
        pppoe_interface_stats = {}

    sampled = 0
    for session in sessions:
        username = session.get('name', '').strip()
        if not username:
            continue

        try:
            subscriber = Subscriber.objects.get(username=username)
        except Subscriber.DoesNotExist:
            continue

        iface_stats = pppoe_interface_stats.get(username, {})
        rx_bytes = _parse_counter(
            session,
            'bytes-in',
            'rx-byte',
            'rx-bytes',
            default=_parse_counter(iface_stats, 'rx-byte', 'rx-bytes'),
        )
        tx_bytes = _parse_counter(
            session,
            'bytes-out',
            'tx-byte',
            'tx-bytes',
            default=_parse_counter(iface_stats, 'tx-byte', 'tx-bytes'),
        )
        session_id = session.get('session-id', '') or session.get('.id', '')

        last_sample_qs = SubscriberUsageSample.objects.filter(subscriber=subscriber)
        if session_id:
            last_sample_qs = last_sample_qs.filter(session_key=str(session_id))
        last_sample = last_sample_qs.order_by('-sampled_at').first()

        is_reset = False
        rx_delta = 0
        tx_delta = 0

        if last_sample:
            if session_id and last_sample.session_key and session_id != last_sample.session_key:
                is_reset = True
            elif rx_bytes < last_sample.rx_bytes or tx_bytes < last_sample.tx_bytes:
                is_reset = True

            if is_reset:
                rx_delta = rx_bytes
                tx_delta = tx_bytes
            else:
                rx_delta = max(0, rx_bytes - last_sample.rx_bytes)
                tx_delta = max(0, tx_bytes - last_sample.tx_bytes)
        else:
            rx_delta = rx_bytes
            tx_delta = tx_bytes

        SubscriberUsageSample.objects.create(
            subscriber=subscriber,
            session_key=str(session_id),
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            rx_delta=rx_delta,
            tx_delta=tx_delta,
            uptime_seconds=_parse_counter(session, 'uptime', default=0),
            is_reset=is_reset,
        )

        _update_daily_rollup(subscriber, rx_delta, tx_delta, is_reset)
        sampled += 1

    return sampled


def _parse_counter(payload, *keys, default=0):
    for key in keys:
        value = payload.get(key)
        if value in (None, ''):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _update_daily_rollup(subscriber, rx_delta, tx_delta, is_reset):
    today = date.today()
    rollup, _ = SubscriberUsageDaily.objects.get_or_create(
        subscriber=subscriber,
        date=today,
        defaults={'rx_bytes': 0, 'tx_bytes': 0, 'total_bytes': 0, 'reset_count': 0}
    )
    rollup.rx_bytes += rx_delta
    rollup.tx_bytes += tx_delta
    rollup.total_bytes += (rx_delta + tx_delta)
    if is_reset:
        rollup.reset_count += 1
    rollup.save(update_fields=['rx_bytes', 'tx_bytes', 'total_bytes', 'reset_count', 'updated_at'])


def create_cutoff_usage_snapshots(reference_date=None):
    from apps.settings_app.models import UsageSettings, BillingSettings
    from apps.billing.services import get_next_cutoff_period, get_cutoff_day_queryset_filter, resolve_cutoff_day
    from datetime import timedelta

    settings = UsageSettings.get_settings()
    if not settings.cutoff_snapshot_enabled:
        return 0

    today = reference_date or date.today()
    created = 0
    billing_settings = BillingSettings.get_settings()

    subscribers = Subscriber.objects.filter(
        status__in=['active', 'suspended'],
        is_billable=True,
    ).filter(get_cutoff_day_queryset_filter(today.day, billing_settings, today))

    for subscriber in subscribers:
        if SubscriberUsageCutoffSnapshot.objects.filter(
            subscriber=subscriber,
            cutoff_date=today,
        ).exists():
            continue

        cutoff_day = resolve_cutoff_day(subscriber, billing_settings)
        usage_period_start, usage_period_end = get_next_cutoff_period(
            cutoff_day,
            today - timedelta(days=1),
        )

        rollups = SubscriberUsageDaily.objects.filter(
            subscriber=subscriber,
            date__gte=usage_period_start,
            date__lte=usage_period_end,
        )
        rx_total = sum(item.rx_bytes for item in rollups)
        tx_total = sum(item.tx_bytes for item in rollups)

        SubscriberUsageCutoffSnapshot.objects.create(
            subscriber=subscriber,
            cutoff_date=today,
            period_start=usage_period_start,
            period_end=usage_period_end,
            rx_bytes=rx_total,
            tx_bytes=tx_total,
            total_bytes=rx_total + tx_total,
        )
        created += 1

    return created


def purge_old_usage_samples():
    from datetime import timedelta
    from apps.settings_app.models import UsageSettings
    settings = UsageSettings.get_settings()
    cutoff = timezone.now() - timedelta(days=settings.raw_retention_days)
    deleted, _ = SubscriberUsageSample.objects.filter(sampled_at__lt=cutoff).delete()
    return deleted


def get_usage_chart_data(subscriber, view='this_cycle'):
    from datetime import timedelta
    from apps.billing.services import resolve_billing_profile

    today = date.today()
    labels = []
    rx_data = []
    tx_data = []

    if view == 'this_cycle':
        profile = resolve_billing_profile(subscriber, reference_date=today)
        start = profile['period_start']

        current = start
        while current <= today:
            labels.append(current.strftime('%b %d'))
            daily = SubscriberUsageDaily.objects.filter(subscriber=subscriber, date=current).first()
            rx_data.append(round((daily.rx_bytes if daily else 0) / (1024**3), 3))
            tx_data.append(round((daily.tx_bytes if daily else 0) / (1024**3), 3))
            current += timedelta(days=1)

    elif view == 'last_7':
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            labels.append(d.strftime('%b %d'))
            daily = SubscriberUsageDaily.objects.filter(subscriber=subscriber, date=d).first()
            rx_data.append(round((daily.rx_bytes if daily else 0) / (1024**3), 3))
            tx_data.append(round((daily.tx_bytes if daily else 0) / (1024**3), 3))

    elif view == 'last_30':
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            labels.append(d.strftime('%b %d'))
            daily = SubscriberUsageDaily.objects.filter(subscriber=subscriber, date=d).first()
            rx_data.append(round((daily.rx_bytes if daily else 0) / (1024**3), 3))
            tx_data.append(round((daily.tx_bytes if daily else 0) / (1024**3), 3))

    elif view == 'by_cycle':
        snapshots = subscriber.usage_cutoff_snapshots.order_by('-cutoff_date')[:12]
        for snap in snapshots:
            labels.append(snap.cutoff_date.strftime('%b %Y'))
            rx_data.append(round(snap.rx_bytes / (1024**3), 3))
            tx_data.append(round(snap.tx_bytes / (1024**3), 3))
        labels.reverse()
        rx_data.reverse()
        tx_data.reverse()

    cumulative = []
    running = 0
    for rx, tx in zip(rx_data, tx_data):
        running += rx + tx
        cumulative.append(round(running, 3))

    has_data = any(value > 0 for value in rx_data + tx_data)
    return {
        'labels': labels,
        'rx': rx_data,
        'tx': tx_data,
        'cumulative': cumulative,
        'has_data': has_data,
    }
