import os
import platform
import shutil
from datetime import timedelta
from time import perf_counter

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count, DecimalField, F, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_apscheduler.models import DjangoJob, DjangoJobExecution

from apps.accounting.models import ExpenseRecord, IncomeRecord
from apps.billing.models import BillingSnapshot, Invoice, Payment
from apps.core.models import AuditLog
from apps.data_exchange.models import DataExchangeJob
from apps.notifications.models import Notification
from apps.routers.models import InterfaceTrafficCache, Router
from apps.settings_app.models import (
    BillingSettings,
    RouterSettings,
    SMSSettings,
    SubscriberSettings,
    TelegramSettings,
    UsageSettings,
)
from apps.sms.models import SMSLog
from apps.subscribers.models import Subscriber, SubscriberUsageCutoffSnapshot, SubscriberUsageDaily, SubscriberUsageSample


def _format_bytes(value):
    if value in (None, ''):
        return 'Unknown'
    value = float(value)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    precision = 0 if unit_index == 0 else 1
    return f"{value:.{precision}f} {units[unit_index]}"


def _safe_ratio(numerator, denominator):
    if not denominator:
        return 0
    return round((numerator / denominator) * 100, 1)


def _make_alert(severity, title, detail, href=None):
    return {
        'severity': severity,
        'title': title,
        'detail': detail,
        'href': href,
    }


def _badge_classes(severity):
    mapping = {
        'healthy': 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        'warning': 'bg-amber-50 text-amber-700 ring-amber-200',
        'critical': 'bg-rose-50 text-rose-700 ring-rose-200',
        'info': 'bg-sky-50 text-sky-700 ring-sky-200',
        'disabled': 'bg-slate-100 text-slate-600 ring-slate-200',
        'pending': 'bg-slate-50 text-slate-600 ring-slate-200',
        'stale': 'bg-amber-50 text-amber-700 ring-amber-200',
        'missing': 'bg-rose-50 text-rose-700 ring-rose-200',
    }
    return mapping.get(severity, mapping['info'])


def _severity_rank(severity):
    order = {
        'critical': 3,
        'warning': 2,
        'healthy': 1,
        'info': 1,
        'disabled': 0,
        'pending': 0,
        'stale': 2,
        'missing': 3,
    }
    return order.get(severity, 0)


def _build_job_metadata():
    billing_settings = BillingSettings.get_settings()
    sms_settings = SMSSettings.get_settings()
    router_settings = RouterSettings.get_settings()
    usage_settings = UsageSettings.get_settings()
    subscriber_settings = SubscriberSettings.get_settings()

    sms_schedule = sms_settings.billing_sms_schedule or '08:00'
    router_interval = max(1, router_settings.polling_interval_seconds)
    usage_interval = max(1, usage_settings.sampler_interval_minutes)

    return {
        'mark_overdue': {
            'label': 'Mark Overdue Invoices',
            'group': 'Billing',
            'schedule': 'Daily at 12:05 AM',
            'enabled': True,
            'healthy_within': timedelta(hours=36),
            'note': f'Uses grace period of {billing_settings.grace_period_days} day(s).',
        },
        'auto_suspend_overdue': {
            'label': 'Auto Suspend Overdue Subscribers',
            'group': 'Billing',
            'schedule': 'Every 15 minutes',
            'enabled': billing_settings.enable_auto_disconnect,
            'healthy_within': timedelta(minutes=45),
            'note': (
                'Skips subscribers with active palugit.'
                if billing_settings.enable_auto_disconnect
                else 'Disabled in Billing Settings.'
            ),
        },
        'generate_invoices': {
            'label': 'Auto Generate Invoices',
            'group': 'Billing',
            'schedule': 'Daily at 12:10 AM',
            'enabled': billing_settings.enable_auto_generate,
            'healthy_within': timedelta(hours=36),
            'note': (
                'Uses subscriber billing profiles and backfills safely when missed.'
                if billing_settings.enable_auto_generate
                else 'Disabled in Billing Settings.'
            ),
        },
        'generate_snapshots': {
            'label': 'Generate Billing Snapshots',
            'group': 'Billing',
            'schedule': 'Daily at 12:15 AM',
            'enabled': billing_settings.billing_snapshot_mode != 'manual',
            'healthy_within': timedelta(hours=36),
            'note': f"Snapshot mode: {billing_settings.get_billing_snapshot_mode_display()}.",
        },
        'auto_freeze_drafts': {
            'label': 'Auto-Freeze Draft Snapshots',
            'group': 'Billing',
            'schedule': 'Every hour',
            'enabled': billing_settings.billing_snapshot_mode == 'draft',
            'healthy_within': timedelta(hours=2),
            'note': (
                f"Draft snapshots auto-freeze after {billing_settings.draft_auto_freeze_hours} hour(s)."
                if billing_settings.billing_snapshot_mode == 'draft'
                else 'Only runs when snapshot mode is Draft.'
            ),
        },
        'billing_sms': {
            'label': 'Send Billing SMS',
            'group': 'Messaging',
            'schedule': f'Daily at {sms_schedule}',
            'enabled': sms_settings.enable_billing_sms,
            'healthy_within': timedelta(hours=36),
            'note': (
                f"Targets snapshots due in {sms_settings.billing_sms_days_before_due} day(s)."
                if sms_settings.enable_billing_sms
                else 'Disabled in SMS Settings.'
            ),
        },
        'router_status_check': {
            'label': 'Router Status Check',
            'group': 'Routers',
            'schedule': f'Every {router_interval} second(s)',
            'enabled': True,
            'healthy_within': timedelta(seconds=max(60, router_interval * 4)),
            'note': 'Updates router online/offline status and notifications.',
        },
        'sample_router_traffic': {
            'label': 'Cache Router Interface Traffic',
            'group': 'Routers',
            'schedule': f'Every {router_interval} second(s)',
            'enabled': True,
            'healthy_within': timedelta(seconds=max(60, router_interval * 4)),
            'note': 'Feeds live telemetry cards and interface detail views.',
        },
        'sample_usage': {
            'label': 'Sample Subscriber Usage',
            'group': 'Subscribers',
            'schedule': f'Every {usage_interval} minute(s)',
            'enabled': usage_settings.enabled,
            'healthy_within': timedelta(minutes=max(30, usage_interval * 4)),
            'note': (
                'Creates raw usage samples, daily rollups, and cutoff snapshots.'
                if usage_settings.enabled
                else 'Usage tracking is disabled in Settings.'
            ),
        },
        'auto_archive': {
            'label': 'Auto Archive Subscribers',
            'group': 'Subscribers',
            'schedule': 'Daily at 2:00 AM',
            'enabled': True,
            'healthy_within': timedelta(hours=36),
            'note': f"Archives disconnected or deceased subscribers after {subscriber_settings.archive_after_days} day(s).",
        },
    }


def _get_runtime_health(now):
    disk = shutil.disk_usage(settings.BASE_DIR)
    db_info = {
        'ok': False,
        'engine': connection.settings_dict.get('ENGINE', 'unknown'),
        'name': connection.settings_dict.get('NAME', ''),
        'host': connection.settings_dict.get('HOST', ''),
        'port': connection.settings_dict.get('PORT', ''),
        'vendor': connection.vendor,
        'latency_ms': None,
        'size_bytes': None,
        'size_display': 'Unknown',
        'server_version': '',
        'error': '',
    }

    try:
        started = perf_counter()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
            db_info['latency_ms'] = round((perf_counter() - started) * 1000, 2)
            db_info['ok'] = True
            if connection.vendor == 'postgresql':
                cursor.execute('SELECT current_database(), pg_database_size(current_database()), version()')
                current_name, size_bytes, version = cursor.fetchone()
                db_info['name'] = current_name
                db_info['size_bytes'] = int(size_bytes or 0)
                db_info['size_display'] = _format_bytes(db_info['size_bytes'])
                db_info['server_version'] = version
            else:
                db_name = str(connection.settings_dict.get('NAME', ''))
                if db_name and os.path.exists(db_name):
                    db_info['size_bytes'] = os.path.getsize(db_name)
                    db_info['size_display'] = _format_bytes(db_info['size_bytes'])
    except Exception as exc:
        db_info['error'] = str(exc)

    migration_info = {'pending_count': None, 'error': ''}
    try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        migration_info['pending_count'] = len(plan)
    except Exception as exc:
        migration_info['error'] = str(exc)

    def path_state(path):
        exists = os.path.exists(path)
        return {
            'path': str(path),
            'exists': exists,
            'writable': os.access(path, os.W_OK) if exists else False,
        }

    disable_scheduler = os.environ.get('DISABLE_SCHEDULER') == '1'

    return {
        'generated_at': now,
        'python_version': platform.python_version(),
        'os_info': f"{platform.system()} {platform.release()}",
        'timezone': settings.TIME_ZONE,
        'debug': settings.DEBUG,
        'app_base_url': settings.APP_BASE_URL,
        'allowed_hosts': settings.ALLOWED_HOSTS,
        'disk_total': _format_bytes(disk.total),
        'disk_used': _format_bytes(disk.used),
        'disk_free': _format_bytes(disk.free),
        'disk_used_pct': _safe_ratio(disk.used, disk.total),
        'database': db_info,
        'migrations': migration_info,
        'paths': {
            'static_root': path_state(settings.STATIC_ROOT),
            'media_root': path_state(settings.MEDIA_ROOT),
        },
        'services': {
            'nginx_detected': bool(shutil.which('nginx')),
            'cloudflared_detected': bool(shutil.which('cloudflared')),
            'scheduler_mode': 'Dedicated scheduler service expected' if disable_scheduler else 'Embedded web-process scheduler allowed',
            'disable_scheduler': disable_scheduler,
        },
    }


def _get_scheduler_health(now):
    from apps.core.scheduler import get_scheduler

    metadata = _build_job_metadata()
    disable_scheduler = os.environ.get('DISABLE_SCHEDULER') == '1'

    embedded_running = False
    embedded_job_ids = set()
    try:
        scheduler = get_scheduler()
        embedded_running = scheduler.running
        if scheduler.running:
            embedded_job_ids = {job.id for job in scheduler.get_jobs()}
    except Exception:
        scheduler = None

    persisted_jobs = {job.id: job for job in DjangoJob.objects.all()}
    job_rows = []
    healthy_interval_seen = False

    for job_id, meta in metadata.items():
        persisted = persisted_jobs.get(job_id)
        last_run = DjangoJobExecution.objects.filter(job_id=job_id).order_by('-run_time').first()
        last_success = DjangoJobExecution.objects.filter(
            job_id=job_id,
            status=DjangoJobExecution.SUCCESS,
        ).order_by('-run_time').first()
        last_error = DjangoJobExecution.objects.filter(
            job_id=job_id,
            status=DjangoJobExecution.ERROR,
        ).order_by('-run_time').first()

        if not meta['enabled']:
            health = 'disabled'
            detail = meta['note']
        elif persisted is None:
            health = 'missing'
            detail = 'Job is not registered in the persistent job store.'
        elif last_error and (not last_success or last_error.run_time >= last_success.run_time):
            health = 'critical'
            detail = last_error.exception or 'Most recent execution failed.'
        elif last_success and last_success.run_time >= now - meta['healthy_within']:
            health = 'healthy'
            detail = 'Recent successful execution found.'
        elif last_success:
            health = 'stale'
            detail = 'Job has history but no recent successful execution inside the expected window.'
        else:
            health = 'pending'
            detail = 'No successful execution recorded yet.'

        if meta['enabled'] and job_id in {'router_status_check', 'sample_router_traffic', 'sample_usage'} and health == 'healthy':
            healthy_interval_seen = True

        job_rows.append({
            'id': job_id,
            'label': meta['label'],
            'group': meta['group'],
            'schedule': meta['schedule'],
            'enabled': meta['enabled'],
            'note': meta['note'],
            'persisted': persisted is not None,
            'embedded_present': job_id in embedded_job_ids,
            'next_run': persisted.next_run_time if persisted else None,
            'last_run': last_run,
            'last_success': last_success,
            'last_error': last_error,
            'health': health,
            'health_classes': _badge_classes(health),
            'detail': detail,
            'can_run_now': embedded_running and job_id in embedded_job_ids,
        })

    if disable_scheduler:
        expected_mode = 'dedicated-service'
        if healthy_interval_seen:
            service_health = 'healthy'
            service_message = 'Recent persistent job executions indicate that the dedicated scheduler is alive.'
        else:
            service_health = 'critical'
            service_message = 'Dedicated scheduler mode is expected, but recent interval job executions were not found.'
    else:
        expected_mode = 'embedded-web'
        if embedded_running:
            service_health = 'healthy'
            service_message = 'The web process currently has an in-memory scheduler running.'
        elif healthy_interval_seen:
            service_health = 'warning'
            service_message = 'Jobs are still executing recently, but this process does not currently report an embedded scheduler.'
        else:
            service_health = 'critical'
            service_message = 'No embedded scheduler is running and no recent interval job executions were found.'

    failed_jobs = [job for job in job_rows if job['health'] == 'critical']
    stale_jobs = [job for job in job_rows if job['health'] in {'stale', 'missing', 'pending'} and job['enabled']]
    recent_failures = DjangoJobExecution.objects.filter(status=DjangoJobExecution.ERROR).select_related('job').order_by('-run_time')[:10]

    return {
        'expected_mode': expected_mode,
        'embedded_running': embedded_running,
        'embedded_job_count': len(embedded_job_ids),
        'registered_job_count': len(persisted_jobs),
        'service_health': service_health,
        'service_health_classes': _badge_classes(service_health),
        'service_message': service_message,
        'job_rows': job_rows,
        'failed_jobs': failed_jobs,
        'stale_jobs': stale_jobs,
        'recent_failures': recent_failures,
    }


def _get_router_health(now):
    router_settings = RouterSettings.get_settings()
    router_interval = max(1, router_settings.polling_interval_seconds)
    stale_threshold = now - timedelta(seconds=max(60, router_interval * 4))

    routers = list(Router.objects.filter(is_active=True).order_by('name'))
    total = len(routers)
    online = sum(1 for router in routers if router.status == 'online')
    offline = sum(1 for router in routers if router.status == 'offline')
    unknown = total - online - offline

    stale_online = 0
    router_rows = []
    for router in routers:
        telemetry_count = InterfaceTrafficCache.objects.filter(interface__router=router).count()
        fresh_telemetry_count = InterfaceTrafficCache.objects.filter(
            interface__router=router,
            sampled_at__gte=stale_threshold,
        ).count()
        error_telemetry_count = InterfaceTrafficCache.objects.filter(
            interface__router=router,
        ).exclude(error='').count()
        stale = bool(router.status == 'online' and (not router.last_seen or router.last_seen < stale_threshold))
        if stale:
            stale_online += 1
        router_rows.append({
            'router': router,
            'telemetry_count': telemetry_count,
            'fresh_telemetry_count': fresh_telemetry_count,
            'error_telemetry_count': error_telemetry_count,
            'stale': stale,
        })

    stale_telemetry_count = InterfaceTrafficCache.objects.filter(sampled_at__lt=stale_threshold).count()
    error_telemetry_count = InterfaceTrafficCache.objects.exclude(error='').count()
    routers_without_fresh_telemetry = Router.objects.filter(is_active=True).exclude(
        interfaces__traffic_cache__sampled_at__gte=stale_threshold,
    ).distinct().count()

    return {
        'total': total,
        'online': online,
        'offline': offline,
        'unknown': unknown,
        'stale_online': stale_online,
        'stale_telemetry_count': stale_telemetry_count,
        'error_telemetry_count': error_telemetry_count,
        'routers_without_fresh_telemetry': routers_without_fresh_telemetry,
        'stale_threshold': stale_threshold,
        'router_rows': router_rows,
    }


def _get_billing_health(now):
    billing_settings = BillingSettings.get_settings()
    today = timezone.localdate()

    invoice_counts = {
        status: Invoice.objects.filter(status=status).count()
        for status, _ in Invoice.STATUS_CHOICES
    }
    snapshot_counts = {
        status: BillingSnapshot.objects.filter(status=status).count()
        for status, _ in BillingSnapshot.STATUS_CHOICES
    }

    active_overdue = Subscriber.objects.filter(status='active', invoices__status='overdue').distinct()
    held_overdue = active_overdue.filter(
        suspension_hold_until__isnull=False,
        suspension_hold_until__gt=now,
    )
    suspended_without_overdue = Subscriber.objects.filter(status='suspended').exclude(
        id__in=Invoice.objects.filter(status='overdue').values('subscriber_id')
    )

    zero_amount = Value(0, output_field=DecimalField(max_digits=10, decimal_places=2))
    unallocated_payments = Payment.objects.annotate(
        allocated_amount=Coalesce(Sum('allocations__amount_allocated'), zero_amount)
    ).filter(amount__gt=F('allocated_amount')).count()

    draft_stale_count = 0
    if billing_settings.billing_snapshot_mode == 'draft':
        freeze_cutoff = now - timedelta(hours=billing_settings.draft_auto_freeze_hours)
        draft_stale_count = BillingSnapshot.objects.filter(status='draft', created_at__lte=freeze_cutoff).count()

    return {
        'invoice_counts': invoice_counts,
        'snapshot_counts': snapshot_counts,
        'active_overdue_count': active_overdue.count(),
        'held_overdue_count': held_overdue.count(),
        'palugit_active_count': Subscriber.objects.filter(
            suspension_hold_until__isnull=False,
            suspension_hold_until__gt=now,
        ).count(),
        'palugit_expiring_count': Subscriber.objects.filter(
            suspension_hold_until__isnull=False,
            suspension_hold_until__gt=now,
            suspension_hold_until__lte=now + timedelta(days=2),
        ).count(),
        'suspended_without_overdue_count': suspended_without_overdue.count(),
        'billable_without_rate_count': Subscriber.objects.filter(
            status__in=['active', 'suspended'],
            is_billable=True,
            monthly_rate__isnull=True,
            plan__isnull=True,
        ).count(),
        'payments_without_income_count': Payment.objects.filter(income_record__isnull=True).count(),
        'unallocated_payments_count': unallocated_payments,
        'overdue_non_active_count': Invoice.objects.filter(
            status='overdue',
            subscriber__status__in=['disconnected', 'deceased', 'archived'],
        ).count(),
        'draft_stale_count': draft_stale_count,
        'billing_mode': billing_settings.get_billing_mode_display(),
        'snapshot_mode': billing_settings.get_billing_snapshot_mode_display(),
        'auto_generate_enabled': billing_settings.enable_auto_generate,
        'auto_suspend_enabled': billing_settings.enable_auto_disconnect,
        'grace_period_days': billing_settings.grace_period_days,
        'recent_payments': Payment.objects.select_related('subscriber').order_by('-paid_at')[:5],
        'recent_snapshots': BillingSnapshot.objects.select_related('subscriber').order_by('-created_at')[:5],
        'today': today,
    }


def _get_messaging_health(now):
    today = timezone.localdate()
    sms_settings = SMSSettings.get_settings()
    telegram_settings = TelegramSettings.get_settings()
    today_sms = SMSLog.objects.filter(created_at__date=today)

    return {
        'sms': {
            'configured': bool(sms_settings.semaphore_api_key),
            'billing_enabled': sms_settings.enable_billing_sms,
            'schedule': sms_settings.billing_sms_schedule,
            'today_total': today_sms.count(),
            'today_sent': today_sms.filter(status='sent').count(),
            'today_failed': today_sms.filter(status='failed').count(),
            'pending_total': SMSLog.objects.filter(status='pending').count(),
            'recent_failed': SMSLog.objects.filter(status='failed').select_related('subscriber').order_by('-created_at')[:5],
        },
        'telegram': {
            'configured': bool(telegram_settings.bot_token and telegram_settings.chat_id),
            'enabled': telegram_settings.enable_notifications,
            'failed_last_24h': Notification.objects.filter(
                channel='telegram',
                status='failed',
                created_at__gte=now - timedelta(hours=24),
            ).count(),
            'recent_failed': Notification.objects.filter(status='failed').order_by('-created_at')[:5],
            'pending_total': Notification.objects.filter(status='pending').count(),
        },
    }


def _get_usage_health(now):
    usage_settings = UsageSettings.get_settings()
    active_subscriber_ids = set(
        Subscriber.objects.filter(status__in=['active', 'suspended']).values_list('id', flat=True)
    )
    recent_threshold = now - timedelta(minutes=max(15, usage_settings.sampler_interval_minutes * 3))
    recent_usage_ids = set(
        SubscriberUsageSample.objects.filter(sampled_at__gte=recent_threshold)
        .values_list('subscriber_id', flat=True)
        .distinct()
    )
    covered_ids = active_subscriber_ids & recent_usage_ids

    last_sample = SubscriberUsageSample.objects.order_by('-sampled_at').first()
    last_daily = SubscriberUsageDaily.objects.order_by('-updated_at').first()
    last_cutoff = SubscriberUsageCutoffSnapshot.objects.order_by('-created_at').first()

    return {
        'enabled': usage_settings.enabled,
        'sampler_interval_minutes': usage_settings.sampler_interval_minutes,
        'cutoff_snapshot_enabled': usage_settings.cutoff_snapshot_enabled,
        'raw_retention_days': usage_settings.raw_retention_days,
        'daily_retention_days': usage_settings.daily_retention_days,
        'last_sample': last_sample,
        'last_daily': last_daily,
        'last_cutoff': last_cutoff,
        'today_samples': SubscriberUsageSample.objects.filter(sampled_at__date=timezone.localdate()).count(),
        'resets_last_24h': SubscriberUsageSample.objects.filter(
            sampled_at__gte=now - timedelta(hours=24),
            is_reset=True,
        ).count(),
        'active_subscriber_count': len(active_subscriber_ids),
        'fresh_subscriber_count': len(covered_ids),
        'stale_or_missing_count': max(0, len(active_subscriber_ids) - len(covered_ids)),
        'recent_threshold': recent_threshold,
    }


def _get_data_exchange_health(now):
    recent_jobs = DataExchangeJob.objects.select_related('created_by').order_by('-created_at')[:8]
    return {
        'recent_jobs': recent_jobs,
        'failed_last_7d': DataExchangeJob.objects.filter(
            status='failed',
            created_at__gte=now - timedelta(days=7),
        ).count(),
        'dry_runs_last_7d': DataExchangeJob.objects.filter(
            is_dry_run=True,
            created_at__gte=now - timedelta(days=7),
        ).count(),
        'applied_imports_last_7d': DataExchangeJob.objects.filter(
            job_type='import',
            is_dry_run=False,
            status='completed',
            created_at__gte=now - timedelta(days=7),
        ).count(),
    }


def _get_finance_health():
    return {
        'income_count': IncomeRecord.objects.count(),
        'expense_count': ExpenseRecord.objects.count(),
        'recent_income': IncomeRecord.objects.order_by('-created_at')[:5],
        'recent_expenses': ExpenseRecord.objects.order_by('-created_at')[:5],
    }


def _get_recent_activity():
    return {
        'audit_logs': AuditLog.objects.select_related('user').order_by('-created_at')[:8],
    }


def _build_alerts(snapshot):
    alerts = []
    runtime = snapshot['runtime']
    scheduler = snapshot['scheduler']
    routers = snapshot['routers']
    billing = snapshot['billing']
    messaging = snapshot['messaging']
    usage = snapshot['usage']
    data_exchange = snapshot['data_exchange']

    if not runtime['database']['ok']:
        alerts.append(_make_alert('critical', 'Database check failed', runtime['database']['error'] or 'The application could not complete a database round-trip.'))
    if runtime['migrations']['pending_count']:
        alerts.append(_make_alert('warning', 'Pending migrations detected', f"{runtime['migrations']['pending_count']} migration(s) are unapplied."))
    if not runtime['paths']['static_root']['exists']:
        alerts.append(_make_alert('warning', 'Static root is missing', f"Expected static root at {runtime['paths']['static_root']['path']}."))
    if scheduler['service_health'] == 'critical':
        alerts.append(_make_alert('critical', 'Scheduler automation looks down', scheduler['service_message'], href='/diagnostics/scheduler/'))
    elif scheduler['service_health'] == 'warning':
        alerts.append(_make_alert('warning', 'Scheduler state needs attention', scheduler['service_message'], href='/diagnostics/scheduler/'))
    if routers['offline'] > 0:
        alerts.append(_make_alert('warning', 'One or more routers are offline', f"{routers['offline']} active router(s) currently report offline state."))
    if routers['stale_telemetry_count'] > 0:
        alerts.append(_make_alert('warning', 'Router telemetry is stale', f"{routers['stale_telemetry_count']} interface cache row(s) are older than the expected refresh window."))
    if billing['payments_without_income_count'] > 0:
        alerts.append(_make_alert('critical', 'Payments without accounting income found', f"{billing['payments_without_income_count']} payment(s) are missing linked income records."))
    if billing['billable_without_rate_count'] > 0:
        alerts.append(_make_alert('warning', 'Billable subscribers are missing rates', f"{billing['billable_without_rate_count']} subscriber(s) can generate billing but have no effective rate."))
    if billing['draft_stale_count'] > 0:
        alerts.append(_make_alert('warning', 'Draft snapshots are waiting too long', f"{billing['draft_stale_count']} draft snapshot(s) are older than the auto-freeze threshold."))
    if messaging['sms']['today_failed'] > 0:
        alerts.append(_make_alert('warning', 'SMS failures detected today', f"{messaging['sms']['today_failed']} SMS message(s) failed today."))
    if messaging['telegram']['failed_last_24h'] > 0:
        alerts.append(_make_alert('warning', 'Telegram delivery failures detected', f"{messaging['telegram']['failed_last_24h']} Telegram notification(s) failed in the last 24 hours."))
    if usage['enabled'] and usage['stale_or_missing_count'] > 0:
        alerts.append(_make_alert('warning', 'Subscriber usage data is stale or missing', f"{usage['stale_or_missing_count']} active or suspended subscriber(s) do not have fresh usage samples."))
    if data_exchange['failed_last_7d'] > 0:
        alerts.append(_make_alert('warning', 'Recent import/export failures found', f"{data_exchange['failed_last_7d']} data exchange job(s) failed in the last 7 days."))

    alerts.sort(key=lambda item: _severity_rank(item['severity']), reverse=True)
    for alert in alerts:
        alert['classes'] = _badge_classes(alert['severity'])

    if any(alert['severity'] == 'critical' for alert in alerts):
        overall = 'critical'
        summary = 'Critical issues need attention before operators can fully trust automation.'
    elif alerts:
        overall = 'warning'
        summary = 'The system is up, but a few subsystems need operator attention.'
    else:
        overall = 'healthy'
        summary = 'Core services, automation, and business workflows look healthy right now.'

    return alerts, overall, summary


def build_diagnostics_snapshot():
    now = timezone.now()
    snapshot = {
        'generated_at': now,
        'runtime': _get_runtime_health(now),
        'scheduler': _get_scheduler_health(now),
        'routers': _get_router_health(now),
        'billing': _get_billing_health(now),
        'messaging': _get_messaging_health(now),
        'usage': _get_usage_health(now),
        'data_exchange': _get_data_exchange_health(now),
        'finance': _get_finance_health(),
        'recent_activity': _get_recent_activity(),
    }
    alerts, overall, summary = _build_alerts(snapshot)
    snapshot['alerts'] = alerts
    snapshot['overall_health'] = overall
    snapshot['overall_health_classes'] = _badge_classes(overall)
    snapshot['overall_summary'] = summary
    snapshot['overview_cards'] = [
        {
            'label': 'Overall Health',
            'value': overall.title(),
            'meta': f"{len(alerts)} active alert(s)",
            'accent': snapshot['overall_health_classes'],
        },
        {
            'label': 'Automation',
            'value': snapshot['scheduler']['service_health'].title(),
            'meta': f"{len(snapshot['scheduler']['failed_jobs'])} failed job(s), {len(snapshot['scheduler']['stale_jobs'])} stale/pending job(s)",
            'accent': snapshot['scheduler']['service_health_classes'],
        },
        {
            'label': 'Routers',
            'value': f"{snapshot['routers']['online']}/{snapshot['routers']['total']}",
            'meta': f"{snapshot['routers']['offline']} offline, {snapshot['routers']['stale_telemetry_count']} stale telemetry row(s)",
            'accent': _badge_classes('warning' if snapshot['routers']['offline'] or snapshot['routers']['stale_telemetry_count'] else 'healthy'),
        },
        {
            'label': 'Billing',
            'value': str(snapshot['billing']['invoice_counts']['overdue']),
            'meta': f"overdue invoice(s), {snapshot['billing']['palugit_active_count']} active palugit hold(s)",
            'accent': _badge_classes('warning' if snapshot['billing']['invoice_counts']['overdue'] else 'healthy'),
        },
        {
            'label': 'Messaging',
            'value': str(snapshot['messaging']['sms']['today_sent']),
            'meta': f"SMS sent today, {snapshot['messaging']['sms']['today_failed']} failed", 
            'accent': _badge_classes('warning' if snapshot['messaging']['sms']['today_failed'] else 'healthy'),
        },
        {
            'label': 'Usage Freshness',
            'value': f"{snapshot['usage']['fresh_subscriber_count']}/{snapshot['usage']['active_subscriber_count']}",
            'meta': 'subscribers with fresh samples',
            'accent': _badge_classes('warning' if snapshot['usage']['stale_or_missing_count'] else 'healthy'),
        },
    ]
    return snapshot
