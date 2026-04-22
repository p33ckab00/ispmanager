from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.diagnostics.services import build_diagnostics_snapshot
from apps.routers import mikrotik
from apps.routers.models import Router


@login_required
def diagnostics_dashboard(request):
    snapshot = build_diagnostics_snapshot()
    return render(request, 'diagnostics/dashboard.html', snapshot)


@login_required
def router_ping(request, pk):
    router = get_object_or_404(Router, pk=pk)
    try:
        identity = mikrotik.get_system_identity(router)
        resource = mikrotik.get_system_resource(router)
        router.status = 'online'
        router.last_seen = timezone.now()
        router.save(update_fields=['status', 'last_seen'])
        return JsonResponse({
            'ok': True,
            'identity': identity,
            'uptime': resource.get('uptime', ''),
            'cpu_load': resource.get('cpu-load', ''),
            'free_memory': resource.get('free-memory', ''),
            'total_memory': resource.get('total-memory', ''),
            'version': resource.get('version', ''),
        })
    except Exception as exc:
        router.status = 'offline'
        router.save(update_fields=['status'])
        return JsonResponse({'ok': False, 'error': str(exc)})


@login_required
def scheduler_status(request):
    snapshot = build_diagnostics_snapshot()
    scheduler = snapshot['scheduler']
    context = {
        'generated_at': snapshot['generated_at'],
        'overall_health': snapshot['overall_health'],
        'alerts': snapshot['alerts'],
        'expected_mode': scheduler['expected_mode'],
        'embedded_running': scheduler['embedded_running'],
        'service_health': scheduler['service_health'],
        'service_health_classes': scheduler['service_health_classes'],
        'service_message': scheduler['service_message'],
        'jobs': scheduler['job_rows'],
        'failed_jobs': scheduler['failed_jobs'],
        'stale_jobs': scheduler['stale_jobs'],
        'recent_failures': scheduler['recent_failures'],
        'summary_cards': [
            {
                'label': 'Automation Health',
                'value': scheduler['service_health'].title(),
                'meta': scheduler['service_message'],
                'accent': scheduler['service_health_classes'],
            },
            {
                'label': 'Registered Jobs',
                'value': str(scheduler['registered_job_count']),
                'meta': f"{scheduler['embedded_job_count']} loaded in this process",
                'accent': 'bg-sky-50 text-sky-700 ring-sky-200',
            },
            {
                'label': 'Failed Jobs',
                'value': str(len(scheduler['failed_jobs'])),
                'meta': 'Jobs whose latest state is failed',
                'accent': 'bg-rose-50 text-rose-700 ring-rose-200' if scheduler['failed_jobs'] else 'bg-emerald-50 text-emerald-700 ring-emerald-200',
            },
            {
                'label': 'Stale / Pending',
                'value': str(len(scheduler['stale_jobs'])),
                'meta': 'Enabled jobs missing a recent success',
                'accent': 'bg-amber-50 text-amber-700 ring-amber-200' if scheduler['stale_jobs'] else 'bg-emerald-50 text-emerald-700 ring-emerald-200',
            },
        ],
    }
    return render(request, 'diagnostics/scheduler.html', context)


@login_required
def run_job_now(request, job_id):
    from apps.core.scheduler import get_scheduler

    scheduler = get_scheduler()
    if not scheduler.running:
        messages.warning(
            request,
            'Run now is only available when this web process is running the embedded scheduler. '
            'In production, use the dedicated scheduler service and wait for the persisted next run.',
        )
        return redirect('scheduler-status')

    job = scheduler.get_job(job_id)
    if not job:
        messages.warning(request, 'This job is not loaded in the current embedded scheduler process.')
        return redirect('scheduler-status')

    job.modify(next_run_time=datetime.now(tz=ZoneInfo('Asia/Manila')))
    messages.success(request, f"Job '{job.name}' was queued for immediate execution in this process.")
    return redirect('scheduler-status')
