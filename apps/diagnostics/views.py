from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.diagnostics.models import DiagnosticsIncident
from apps.diagnostics.services import (
    acknowledge_incident,
    build_diagnostics_snapshot,
    resolve_incident,
)
from apps.routers import mikrotik
from apps.routers.models import Router


@login_required
def diagnostics_dashboard(request):
    incident_status = request.GET.get('incidents', 'active')
    snapshot = build_diagnostics_snapshot(
        user=request.user,
        incident_status=incident_status,
    )
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
    snapshot = build_diagnostics_snapshot(
        sync_incidents=False,
        incident_status='active',
    )
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
@require_POST
def acknowledge_incident_view(request, pk):
    incident = get_object_or_404(DiagnosticsIncident, pk=pk)
    if incident.status == 'resolved':
        messages.info(request, 'This incident is already resolved.')
    elif incident.status == 'acknowledged':
        messages.info(request, 'This incident was already acknowledged.')
    else:
        acknowledge_incident(incident, user=request.user)
        messages.success(request, f"Incident acknowledged: {incident.title}")
    filter_key = request.POST.get('incident_filter', 'active')
    return redirect(f"/diagnostics/?incidents={filter_key}")


@login_required
@require_POST
def resolve_incident_view(request, pk):
    incident = get_object_or_404(DiagnosticsIncident, pk=pk)
    resolution_note = (request.POST.get('resolution_note') or '').strip() or 'Resolved by operator.'
    if incident.status == 'resolved':
        messages.info(request, 'This incident is already resolved.')
    else:
        result = resolve_incident(incident, user=request.user, resolution_note=resolution_note)
        if result['resolved']:
            messages.success(request, f"{result['message']} ({incident.title})")
        else:
            messages.warning(request, f"{result['message']} Manual guide is shown on the incident card.")
    filter_key = request.POST.get('incident_filter', 'active')
    return redirect(f"/diagnostics/?incidents={filter_key}")


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
