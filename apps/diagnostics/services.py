import os
import platform
import shutil
import subprocess
from datetime import timedelta
from time import perf_counter

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_apscheduler.models import DjangoJob, DjangoJobExecution

from apps.accounting.models import ExpenseRecord, IncomeRecord
from apps.billing.models import BillingSnapshot, Invoice, Payment
from apps.core.models import AuditLog
from apps.data_exchange.models import DataExchangeJob
from apps.diagnostics.models import (
    DiagnosticsIncident,
    DiagnosticsIncidentEvent,
    DiagnosticsServiceSnapshot,
)
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
from apps.subscribers.models import (
    Subscriber,
    SubscriberUsageCutoffSnapshot,
    SubscriberUsageDaily,
    SubscriberUsageSample,
)

SERVICE_PROBE_MAX_AGE = timedelta(minutes=5)
INCIDENT_FILTERS = ['active', 'acknowledged', 'resolved']


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


def _make_alert(key, severity, title, detail, href=None, source='system', payload=None):
    return {
        'key': key,
        'source': source,
        'severity': severity,
        'title': title,
        'detail': detail,
        'href': href,
        'payload': payload or {},
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
        'unsupported': 'bg-slate-100 text-slate-600 ring-slate-200',
        'unknown': 'bg-slate-50 text-slate-600 ring-slate-200',
        'active': 'bg-rose-50 text-rose-700 ring-rose-200',
        'acknowledged': 'bg-amber-50 text-amber-700 ring-amber-200',
        'resolved': 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        'neutral': 'bg-slate-50 text-slate-600 ring-slate-200',
    }
    return mapping.get(severity, mapping['info'])


def _severity_rank(severity):
    order = {
        'critical': 4,
        'warning': 3,
        'healthy': 2,
        'info': 2,
        'active': 4,
        'acknowledged': 3,
        'resolved': 1,
        'disabled': 1,
        'pending': 1,
        'stale': 3,
        'missing': 4,
        'unsupported': 0,
        'unknown': 0,
        'neutral': 0,
    }
    return order.get(severity, 0)


def _record_incident_event(incident, event_type, message, payload=None, user=None):
    DiagnosticsIncidentEvent.objects.create(
        incident=incident,
        event_type=event_type,
        message=message,
        payload_json=payload or {},
        created_by=user,
    )


def _service_definitions():
    return [
        {'service_name': 'postgresql', 'display_name': 'PostgreSQL', 'optional': False},
        {'service_name': 'nginx', 'display_name': 'Nginx', 'optional': False},
        {'service_name': 'ispmanager-web', 'display_name': 'ISP Manager Web', 'optional': False},
        {'service_name': 'ispmanager-scheduler', 'display_name': 'ISP Manager Scheduler', 'optional': False},
        {'service_name': 'cloudflared', 'display_name': 'Cloudflared Tunnel', 'optional': True},
    ]


def _run_command(args, timeout=8):
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        class Result:
            returncode = 1
            stdout = ''
            stderr = str(exc)
        return Result()


def _probe_single_service(definition):
    name = definition['service_name']
    optional = definition.get('optional', False)
    linux_supported = platform.system() == 'Linux' and bool(shutil.which('systemctl'))

    if not linux_supported:
        status = 'unsupported'
        detail = 'Linux systemd checks are only available on Ubuntu or other systemd-based Linux hosts.'
        payload = {'optional': optional, 'linux_supported': False}
        return {
            'service_name': name,
            'display_name': definition['display_name'],
            'status': status,
            'is_present': False,
            'is_active': False,
            'is_enabled': False,
            'detail': detail,
            'payload_json': payload,
        }

    result = _run_command([
        'systemctl', 'show', name, '--no-page',
        '--property=LoadState,ActiveState,SubState,UnitFileState,Description,MainPID'
    ])

    parsed = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            parsed[key] = value

    load_state = parsed.get('LoadState', '')
    active_state = parsed.get('ActiveState', '')
    sub_state = parsed.get('SubState', '')
    unit_file_state = parsed.get('UnitFileState', '')
    description = parsed.get('Description', definition['display_name'])
    main_pid = parsed.get('MainPID', '')

    is_present = load_state not in ('', 'not-found')
    is_active = active_state == 'active'
    is_enabled = unit_file_state in {'enabled', 'static', 'indirect', 'generated', 'alias', 'linked'}

    if not is_present:
        status = 'unknown' if optional else 'critical'
        detail = 'Service unit not found on this host.' if not result.stderr else result.stderr.strip()
    elif is_active and is_enabled:
        status = 'healthy'
        detail = f'Active ({sub_state or active_state}).'
    elif is_active:
        status = 'warning'
        detail = f'Active but not enabled at boot (unit file state: {unit_file_state or "unknown"}).'
    elif active_state in {'activating', 'reloading'}:
        status = 'warning'
        detail = f'Service is transitioning: {active_state} ({sub_state}).'
    elif active_state == 'failed':
        status = 'critical'
        detail = 'Service is in failed state.'
    elif active_state == 'inactive':
        status = 'warning' if optional else 'critical'
        detail = 'Service is installed but inactive.'
    else:
        status = 'unknown'
        detail = f'State is {active_state or "unknown"}.'

    payload = {
        'optional': optional,
        'linux_supported': True,
        'load_state': load_state,
        'active_state': active_state,
        'sub_state': sub_state,
        'unit_file_state': unit_file_state,
        'description': description,
        'main_pid': main_pid,
        'stderr': result.stderr.strip(),
    }
    return {
        'service_name': name,
        'display_name': definition['display_name'],
        'status': status,
        'is_present': is_present,
        'is_active': is_active,
        'is_enabled': is_enabled,
        'detail': detail,
        'payload_json': payload,
    }


def probe_service_snapshots(force=False):
    now = timezone.now()
    existing = {
        snapshot.service_name: snapshot
        for snapshot in DiagnosticsServiceSnapshot.objects.all()
    }
    service_defs = _service_definitions()
    if not force:
        expected_names = {item['service_name'] for item in service_defs}
        if set(existing.keys()) == expected_names and not any(
            snapshot.checked_at < now - SERVICE_PROBE_MAX_AGE for snapshot in existing.values()
        ):
            return list(existing.values())

    snapshots = []
    for definition in service_defs:
        data = _probe_single_service(definition)
        snapshot, _ = DiagnosticsServiceSnapshot.objects.update_or_create(
            service_name=data['service_name'],
            defaults={
                'display_name': data['display_name'],
                'status': data['status'],
                'is_present': data['is_present'],
                'is_active': data['is_active'],
                'is_enabled': data['is_enabled'],
                'detail': data['detail'],
                'payload_json': data['payload_json'],
                'checked_at': now,
            },
        )
        snapshots.append(snapshot)
    return snapshots


def _get_service_health(now, force=False):
    snapshots = probe_service_snapshots(force=force)
    critical_count = sum(1 for snapshot in snapshots if snapshot.status == 'critical')
    warning_count = sum(1 for snapshot in snapshots if snapshot.status == 'warning')
    supported = any(snapshot.status != 'unsupported' for snapshot in snapshots)
    latest_check = max((snapshot.checked_at for snapshot in snapshots), default=None)
    rows = []
    for snapshot in snapshots:
        rows.append({
            'snapshot': snapshot,
            'status_classes': _badge_classes(snapshot.status),
            'optional': snapshot.payload_json.get('optional', False),
        })

    return {
        'snapshots': snapshots,
        'rows': rows,
        'critical_count': critical_count,
        'warning_count': warning_count,
        'supported': supported,
        'latest_check': latest_check,
    }


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
        'refresh_diagnostics': {
            'label': 'Refresh Diagnostics State',
            'group': 'Diagnostics',
            'schedule': 'Every 5 minutes',
            'enabled': True,
            'healthy_within': timedelta(minutes=15),
            'note': 'Refreshes persisted diagnostics incidents and Linux service snapshots.',
        },
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
                f"Starts {sms_settings.billing_sms_days_before_due} day(s) before due, repeats every {sms_settings.billing_sms_repeat_interval_days} day(s)"
                + (
                    f", after due every {sms_settings.billing_sms_after_due_interval_days} day(s)."
                    if sms_settings.billing_sms_send_after_due
                    else "."
                )
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
        pass

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

        if meta['enabled'] and job_id in {'router_status_check', 'sample_router_traffic', 'sample_usage', 'refresh_diagnostics'} and health == 'healthy':
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
    services = snapshot['service_health']

    if not runtime['database']['ok']:
        alerts.append(_make_alert(
            'runtime.database.failed',
            'critical',
            'Database check failed',
            runtime['database']['error'] or 'The application could not complete a database round-trip.',
            source='runtime',
        ))
    if runtime['migrations']['pending_count']:
        alerts.append(_make_alert(
            'runtime.migrations.pending',
            'warning',
            'Pending migrations detected',
            f"{runtime['migrations']['pending_count']} migration(s) are unapplied.",
            source='runtime',
            payload={'pending_count': runtime['migrations']['pending_count']},
        ))
    if not runtime['paths']['static_root']['exists']:
        alerts.append(_make_alert(
            'runtime.static_root.missing',
            'warning',
            'Static root is missing',
            f"Expected static root at {runtime['paths']['static_root']['path']}.",
            source='runtime',
        ))
    if scheduler['service_health'] == 'critical':
        alerts.append(_make_alert(
            'scheduler.service.critical',
            'critical',
            'Scheduler automation looks down',
            scheduler['service_message'],
            href='/diagnostics/scheduler/',
            source='scheduler',
        ))
    elif scheduler['service_health'] == 'warning':
        alerts.append(_make_alert(
            'scheduler.service.warning',
            'warning',
            'Scheduler state needs attention',
            scheduler['service_message'],
            href='/diagnostics/scheduler/',
            source='scheduler',
        ))
    if routers['offline'] > 0:
        alerts.append(_make_alert(
            'routers.offline',
            'warning',
            'One or more routers are offline',
            f"{routers['offline']} active router(s) currently report offline state.",
            source='routers',
            payload={'offline': routers['offline']},
        ))
    if routers['stale_telemetry_count'] > 0:
        alerts.append(_make_alert(
            'routers.telemetry.stale',
            'warning',
            'Router telemetry is stale',
            f"{routers['stale_telemetry_count']} interface cache row(s) are older than the expected refresh window.",
            source='routers',
            payload={'stale_telemetry_count': routers['stale_telemetry_count']},
        ))
    if billing['payments_without_income_count'] > 0:
        alerts.append(_make_alert(
            'billing.payments_without_income',
            'critical',
            'Payments without accounting income found',
            f"{billing['payments_without_income_count']} payment(s) are missing linked income records.",
            source='billing',
            payload={'payments_without_income_count': billing['payments_without_income_count']},
        ))
    if billing['billable_without_rate_count'] > 0:
        alerts.append(_make_alert(
            'billing.billable_without_rate',
            'warning',
            'Billable subscribers are missing rates',
            f"{billing['billable_without_rate_count']} subscriber(s) can generate billing but have no effective rate.",
            source='billing',
        ))
    if billing['draft_stale_count'] > 0:
        alerts.append(_make_alert(
            'billing.draft_snapshots.stale',
            'warning',
            'Draft snapshots are waiting too long',
            f"{billing['draft_stale_count']} draft snapshot(s) are older than the auto-freeze threshold.",
            source='billing',
        ))
    if messaging['sms']['today_failed'] > 0:
        alerts.append(_make_alert(
            'messaging.sms.failed_today',
            'warning',
            'SMS failures detected today',
            f"{messaging['sms']['today_failed']} SMS message(s) failed today.",
            source='messaging',
        ))
    if messaging['telegram']['failed_last_24h'] > 0:
        alerts.append(_make_alert(
            'messaging.telegram.failed_last_24h',
            'warning',
            'Telegram delivery failures detected',
            f"{messaging['telegram']['failed_last_24h']} Telegram notification(s) failed in the last 24 hours.",
            source='messaging',
        ))
    if usage['enabled'] and usage['stale_or_missing_count'] > 0:
        alerts.append(_make_alert(
            'usage.samples.stale_or_missing',
            'warning',
            'Subscriber usage data is stale or missing',
            f"{usage['stale_or_missing_count']} active or suspended subscriber(s) do not have fresh usage samples.",
            source='usage',
        ))
    if data_exchange['failed_last_7d'] > 0:
        alerts.append(_make_alert(
            'data_exchange.failed_recently',
            'warning',
            'Recent import/export failures found',
            f"{data_exchange['failed_last_7d']} data exchange job(s) failed in the last 7 days.",
            source='data_exchange',
        ))

    for snapshot_item in services['snapshots']:
        optional = snapshot_item.payload_json.get('optional', False)
        if snapshot_item.status in {'critical', 'warning'} and (not optional or snapshot_item.is_present):
            alerts.append(_make_alert(
                f"service.{snapshot_item.service_name}.{snapshot_item.status}",
                snapshot_item.status,
                f"Linux service needs attention: {snapshot_item.display_name}",
                snapshot_item.detail,
                source='services',
                payload={'service_name': snapshot_item.service_name},
            ))

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


def _sync_incidents(alerts, user=None):
    now = timezone.now()
    active_keys = set()

    for alert in alerts:
        active_keys.add(alert['key'])
        defaults = {
            'source': alert['source'],
            'severity': alert['severity'],
            'title': alert['title'],
            'detail': alert['detail'],
            'status': 'active',
            'first_seen_at': now,
            'last_seen_at': now,
            'current_payload_json': alert.get('payload', {}),
        }
        incident, created = DiagnosticsIncident.objects.get_or_create(
            key=alert['key'],
            defaults=defaults,
        )
        if created:
            _record_incident_event(incident, 'detected', alert['detail'], payload=alert.get('payload', {}), user=user)
            continue

        previous_status = incident.status
        previous_signature = (incident.severity, incident.title, incident.detail, incident.current_payload_json)

        incident.source = alert['source']
        incident.severity = alert['severity']
        incident.title = alert['title']
        incident.detail = alert['detail']
        incident.current_payload_json = alert.get('payload', {})
        incident.last_seen_at = now

        event_type = None
        event_message = None
        if previous_status == 'resolved':
            incident.status = 'active'
            incident.acknowledged_at = None
            incident.acknowledged_by = None
            incident.resolved_at = None
            incident.resolution_note = ''
            event_type = 'reopened'
            event_message = 'Condition reappeared after being resolved.'
        elif previous_signature != (incident.severity, incident.title, incident.detail, incident.current_payload_json):
            event_type = 'updated'
            event_message = incident.detail

        incident.save(update_fields=[
            'source', 'severity', 'title', 'detail', 'current_payload_json',
            'last_seen_at', 'status', 'acknowledged_at', 'acknowledged_by',
            'resolved_at', 'resolution_note', 'updated_at',
        ])
        if event_type:
            _record_incident_event(incident, event_type, event_message, payload=incident.current_payload_json, user=user)

    resolved_qs = DiagnosticsIncident.objects.exclude(status='resolved').exclude(key__in=active_keys)
    for incident in resolved_qs:
        incident.status = 'resolved'
        incident.resolved_at = now
        if not incident.resolution_note:
            incident.resolution_note = 'Condition cleared automatically.'
        incident.save(update_fields=['status', 'resolved_at', 'resolution_note', 'updated_at'])
        _record_incident_event(incident, 'resolved', incident.resolution_note, payload=incident.current_payload_json, user=user)


def acknowledge_incident(incident, user=None):
    if incident.status == 'resolved':
        return incident
    incident.status = 'acknowledged'
    incident.acknowledged_at = timezone.now()
    incident.acknowledged_by = user
    incident.save(update_fields=['status', 'acknowledged_at', 'acknowledged_by', 'updated_at'])
    _record_incident_event(incident, 'acknowledged', 'Incident acknowledged by operator.', payload=incident.current_payload_json, user=user)
    return incident


def resolve_incident(incident, user=None, resolution_note='Resolved by operator.'):
    incident.status = 'resolved'
    incident.resolved_at = timezone.now()
    incident.resolution_note = resolution_note
    incident.save(update_fields=['status', 'resolved_at', 'resolution_note', 'updated_at'])
    _record_incident_event(incident, 'manually_resolved', resolution_note, payload=incident.current_payload_json, user=user)
    return incident


def _get_incident_health(filter_status='active'):
    if filter_status not in INCIDENT_FILTERS:
        filter_status = 'active'

    incident_counts = {
        status: DiagnosticsIncident.objects.filter(status=status).count()
        for status in INCIDENT_FILTERS
    }
    incident_rows = DiagnosticsIncident.objects.select_related('acknowledged_by').filter(status=filter_status).order_by(
        '-last_seen_at' if filter_status != 'resolved' else '-resolved_at', '-first_seen_at'
    )[:20]
    rows = []
    for incident in incident_rows:
        rows.append({
            'incident': incident,
            'severity_classes': _badge_classes(incident.severity),
            'status_classes': _badge_classes(incident.status if incident.status != 'active' else 'critical'),
            'can_acknowledge': incident.status == 'active',
            'can_resolve': incident.status in {'active', 'acknowledged'},
        })

    event_rows = []
    recent_events = DiagnosticsIncidentEvent.objects.select_related('incident', 'created_by').order_by('-created_at')[:10]
    for event in recent_events:
        event_rows.append({
            'event': event,
            'type_classes': _badge_classes(
                'critical' if event.event_type in {'detected', 'reopened'} else
                'warning' if event.event_type == 'acknowledged' else
                'healthy'
            ),
        })

    filter_rows = []
    for status in INCIDENT_FILTERS:
        filter_rows.append({
            'key': status,
            'label': status.replace('_', ' ').title(),
            'count': incident_counts[status],
            'active': status == filter_status,
            'classes': _badge_classes(status if status != 'active' else 'critical'),
        })

    return {
        'current_filter': filter_status,
        'rows': rows,
        'recent_events': event_rows,
        'active_count': incident_counts['active'],
        'acknowledged_count': incident_counts['acknowledged'],
        'resolved_count': incident_counts['resolved'],
        'resolved_today_count': DiagnosticsIncident.objects.filter(
            status='resolved',
            resolved_at__date=timezone.localdate(),
        ).count(),
        'filters': filter_rows,
    }


def build_diagnostics_snapshot(sync_incidents=True, user=None, incident_status='active', force_service_probe=False):
    now = timezone.now()
    snapshot = {
        'generated_at': now,
        'runtime': _get_runtime_health(now),
        'scheduler': _get_scheduler_health(now),
        'service_health': _get_service_health(now, force=force_service_probe),
        'routers': _get_router_health(now),
        'billing': _get_billing_health(now),
        'messaging': _get_messaging_health(now),
        'usage': _get_usage_health(now),
        'data_exchange': _get_data_exchange_health(now),
        'finance': _get_finance_health(),
        'recent_activity': _get_recent_activity(),
    }
    alerts, overall, summary = _build_alerts(snapshot)
    if sync_incidents:
        _sync_incidents(alerts, user=user)
    snapshot['alerts'] = alerts
    snapshot['overall_health'] = overall
    snapshot['overall_health_classes'] = _badge_classes(overall)
    snapshot['overall_summary'] = summary
    snapshot['incidents'] = _get_incident_health(filter_status=incident_status)
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
            'label': 'Incidents',
            'value': str(snapshot['incidents']['active_count']),
            'meta': f"{snapshot['incidents']['acknowledged_count']} acknowledged, {snapshot['incidents']['resolved_today_count']} resolved today",
            'accent': _badge_classes('critical' if snapshot['incidents']['active_count'] else 'healthy'),
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
        {
            'label': 'Linux Services',
            'value': str(snapshot['service_health']['critical_count']),
            'meta': f"{snapshot['service_health']['warning_count']} warning service(s)",
            'accent': _badge_classes('critical' if snapshot['service_health']['critical_count'] else ('warning' if snapshot['service_health']['warning_count'] else 'healthy')),
        },
    ]
    return snapshot
