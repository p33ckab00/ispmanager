import json
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from apps.core.models import SystemSetup, AuditLog
from apps.core.forms import FirstRunForm


def setup_wizard(request):
    setup = SystemSetup.get_setup()
    if setup.is_configured:
        return redirect('/dashboard/')

    if request.method == 'POST':
        form = FirstRunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_superuser(
                username=data['admin_username'],
                email=data['admin_email'],
                password=data['admin_password'],
            )
            setup.isp_name = data['isp_name']
            setup.isp_address = data['isp_address']
            setup.isp_phone = data['isp_phone']
            setup.isp_email = data['isp_email']
            setup.is_configured = True
            setup.configured_by = user
            setup.save()
            AuditLog.log('system', 'core', f"First-run setup completed. ISP: {data['isp_name']}", user=user)
            login(request, user)
            messages.success(request, 'Setup complete. Welcome to ISP Manager.')
            return redirect('/dashboard/')
    else:
        form = FirstRunForm()
    return render(request, 'core/setup.html', {'form': form})


def login_view(request):
    setup = SystemSetup.get_setup()
    if not setup.is_configured:
        return redirect('/setup/')
    if request.user.is_authenticated:
        return redirect('/dashboard/')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            AuditLog.log('login', 'core', f"User {username} logged in", user=user)
            return redirect('/dashboard/')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'core/login.html')


def logout_view(request):
    if request.user.is_authenticated:
        AuditLog.log('logout', 'core', f"User {request.user.username} logged out", user=request.user)
    logout(request)
    return redirect('/')


@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')


@login_required
def dashboard_stats(request):
    from apps.subscribers.models import Subscriber
    from apps.billing.models import Invoice
    from apps.routers.models import Router
    from apps.sms.models import SMSLog
    from django.utils import timezone

    data = {
        'total_subscribers': Subscriber.objects.count(),
        'active_subscribers': Subscriber.objects.filter(status='active').count(),
        'online_sessions': Subscriber.objects.filter(mt_status='online').count(),
        'open_bills': Invoice.objects.filter(status__in=['open','partial']).count(),
        'overdue_bills': Invoice.objects.filter(status='overdue').count(),
        'routers_online': Router.objects.filter(status='online', is_active=True).count(),
        'routers_total': Router.objects.filter(is_active=True).count(),
        'sms_today': SMSLog.objects.filter(
            created_at__date=timezone.now().date()
        ).count(),
    }
    return JsonResponse(data)
