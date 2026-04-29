from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from apps.sms.models import SMSLog
from apps.sms.services import send_manual_sms, get_semaphore_balance
from apps.subscribers.models import Subscriber
from apps.core.models import AuditLog


@login_required
def sms_dashboard(request):
    recent = SMSLog.objects.select_related('subscriber', 'billing_snapshot').all()[:10]
    sent_today = SMSLog.objects.filter(
        created_at__date=__import__('datetime').date.today()
    ).count()
    balance_data, balance_err = get_semaphore_balance()
    return render(request, 'sms/dashboard.html', {
        'recent': recent,
        'sent_today': sent_today,
        'balance_data': balance_data,
        'balance_err': balance_err,
    })


@login_required
def sms_log(request):
    qs = SMSLog.objects.select_related('subscriber', 'billing_snapshot').all()
    snapshot_id = request.GET.get('snapshot', '').strip()
    if snapshot_id:
        qs = qs.filter(billing_snapshot_id=snapshot_id)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'sms/log.html', {
        'page_obj': page,
        'snapshot_id': snapshot_id,
    })


@login_required
def sms_send(request):
    if not request.user.has_perm('sms.add_smslog'):
        messages.error(request, 'You do not have permission to send SMS.')
        return redirect('sms-log')

    subscribers = Subscriber.objects.filter(
        status='active', sms_opt_out=False
    ).exclude(phone='').order_by('username')

    if request.method == 'POST':
        mode = request.POST.get('mode', 'single')
        message = request.POST.get('message', '').strip()

        if not message:
            messages.error(request, 'Message cannot be empty.')
            return render(request, 'sms/send.html', {'subscribers': subscribers})

        if mode == 'single':
            sub_id = request.POST.get('subscriber_id', '')
            try:
                sub = Subscriber.objects.get(pk=sub_id)
                log, err = send_manual_sms(sub.phone, message, subscriber=sub, sent_by=request.user.username)
                if err:
                    messages.error(request, f"Failed: {err}")
                else:
                    AuditLog.log('send', 'sms', f"SMS sent to {sub.username}", user=request.user)
                    messages.success(request, f"SMS sent to {sub.display_name} ({sub.phone}).")
            except Subscriber.DoesNotExist:
                messages.error(request, 'Subscriber not found.')
        elif mode == 'bulk':
            sent = failed = 0
            for sub in subscribers:
                log, err = send_manual_sms(
                    sub.phone, message, subscriber=sub,
                    sent_by=request.user.username, sms_type='bulk'
                )
                if err:
                    failed += 1
                else:
                    sent += 1
            AuditLog.log('send', 'sms', f"Bulk SMS: {sent} sent, {failed} failed", user=request.user)
            messages.success(request, f"Bulk done. Sent: {sent}, Failed: {failed}.")

        return redirect('sms-log')

    return render(request, 'sms/send.html', {'subscribers': subscribers})
