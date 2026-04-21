import platform
import shutil
import os
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from apps.routers.models import Router
from apps.routers import mikrotik
from apps.subscribers.models import Subscriber
from apps.billing.models import Invoice
from apps.sms.models import SMSLog


@login_required
def diagnostics_dashboard(request):
    disk = shutil.disk_usage('/')
    disk_used_pct = round((disk.used / disk.total) * 100, 1)

    from django.db import connection
    db_path = connection.settings_dict.get('NAME', '')
    db_size_bytes = os.path.getsize(db_path) if os.path.exists(str(db_path)) else 0
    db_size_kb = round(db_size_bytes / 1024, 1)

    routers = Router.objects.filter(is_active=True)
    router_statuses = []
    for r in routers:
        router_statuses.append({
            'router': r,
            'online': r.status == 'online',
        })

    stats = {
        'total_subscribers': Subscriber.objects.count(),
        'active_subscribers': Subscriber.objects.filter(status='active').count(),
        'online_mt': Subscriber.objects.filter(mt_status='online').count(),
        'open_bills': Invoice.objects.filter(status__in=['open','partial']).count(),
        'overdue_bills': Invoice.objects.filter(status='overdue').count(),
        'sms_sent_today': SMSLog.objects.filter(created_at__date=timezone.now().date()).count(),
    }

    return render(request, 'diagnostics/dashboard.html', {
        'disk_total_gb': round(disk.total / (1024**3), 1),
        'disk_used_gb': round(disk.used / (1024**3), 1),
        'disk_used_pct': disk_used_pct,
        'db_size_kb': db_size_kb,
        'python_version': platform.python_version(),
        'os_info': f"{platform.system()} {platform.release()}",
        'router_statuses': router_statuses,
        'stats': stats,
    })


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
    except Exception as e:
        router.status = 'offline'
        router.save(update_fields=['status'])
        return JsonResponse({'ok': False, 'error': str(e)})


@login_required
def scheduler_status(request):
    from apps.core.scheduler import get_scheduler
    scheduler = get_scheduler()
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time,
            })
    return render(request, 'diagnostics/scheduler.html', {
        'running': scheduler.running,
        'jobs': jobs,
    })


@login_required
def run_job_now(request, job_id):
    from apps.core.scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if job:
        job.modify(next_run_time=__import__('datetime').datetime.now(tz=__import__('pytz').timezone('Asia/Manila')))
        from django.contrib import messages
        messages.success(request, f"Job '{job.name}' triggered.")
    return redirect('scheduler-status')
