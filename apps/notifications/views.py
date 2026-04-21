from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from apps.notifications.models import Notification
from apps.notifications.telegram import send_telegram


@login_required
def notification_list(request):
    qs = Notification.objects.all()
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'notifications/list.html', {'page_obj': page})


@login_required
def telegram_test(request):
    if request.method == 'POST':
        ok, err = send_telegram('ISP Manager: Telegram test message. Connection working.')
        if ok:
            messages.success(request, 'Test message sent to Telegram.')
        else:
            messages.error(request, f"Failed: {err}")
        return redirect('notification-list')
    return render(request, 'notifications/telegram_test.html')
