from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from apps.subscribers.models import Subscriber, Plan, RateHistory, NetworkNode, SubscriberNode
from apps.subscribers.forms import (
    SubscriberAdminForm, PlanForm, ManualSubscriberForm,
    OTPRequestForm, OTPVerifyForm, StatusChangeForm,
    DeceasedForm, DisconnectForm, RateChangeForm,
)
from apps.subscribers.services import (
    sync_ppp_secrets, sync_active_sessions,
    suspend_subscriber, reconnect_subscriber,
    disconnect_subscriber, mark_deceased, archive_subscriber,
    get_usage_chart_data,
)
from apps.billing.services import apply_rate_change
from apps.subscribers.otp import create_otp, verify_otp
from apps.routers.models import Router
from apps.core.models import AuditLog


# ── Subscriber List ────────────────────────────────────────────────────────────

@login_required
def subscriber_list(request):
    qs = Subscriber.objects.select_related('router', 'plan').all()

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(ip_address__icontains=q)
        )

    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status__in=['archived'])

    service = request.GET.get('service', '')
    if service:
        qs = qs.filter(service_type=service)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'subscribers/list.html', {
        'page_obj': page, 'q': q, 'status': status,
        'service': service, 'total': qs.count(),
    })


# ── Subscriber Detail ──────────────────────────────────────────────────────────

@login_required
def subscriber_detail(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)

    from apps.billing.models import Invoice, BillingSnapshot, Payment
    from apps.billing.services import mark_overdue_invoices
    mark_overdue_invoices()

    invoices = Invoice.objects.filter(subscriber=subscriber).order_by('-period_start')
    snapshots = BillingSnapshot.objects.filter(subscriber=subscriber).order_by('-cutoff_date')
    payments = Payment.objects.filter(subscriber=subscriber).prefetch_related('allocations').order_by('-paid_at')
    rate_history = RateHistory.objects.filter(subscriber=subscriber).order_by('-effective_date')
    latest_snapshot = snapshots.first()

    open_balance = sum(
        inv.remaining_balance for inv in
        invoices.filter(status__in=['open', 'partial', 'overdue'])
    )

    node_assignment = None
    try:
        node_assignment = subscriber.node_assignment
    except Exception:
        pass

    usage_views = [('this_cycle','This Cycle'),('last_7','Last 7 Days'),('last_30','Last 30 Days'),('by_cycle','By Cycle')]
    return render(request, 'subscribers/detail.html', {
        'subscriber': subscriber,
        'invoices': invoices[:10],
        'snapshots': snapshots[:10],
        'payments': payments[:10],
        'rate_history': rate_history[:10],
        'latest_snapshot': latest_snapshot,
        'open_balance': open_balance,
        'node_assignment': node_assignment,
        'nodes': NetworkNode.objects.filter(is_active=True).order_by('name'),
        'usage_views': usage_views,
    })


# ── Edit Admin Fields ──────────────────────────────────────────────────────────

@login_required
def subscriber_edit(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        form = SubscriberAdminForm(request.POST, instance=subscriber)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'subscribers',
                         f"Subscriber info updated: {subscriber.username}", user=request.user)
            messages.success(request, 'Subscriber information updated.')
            return redirect('subscriber-detail', pk=pk)
    else:
        form = SubscriberAdminForm(instance=subscriber)
    return render(request, 'subscribers/edit.html', {'form': form, 'subscriber': subscriber})


# ── Rate / Plan Change ─────────────────────────────────────────────────────────

@login_required
def subscriber_rate_change(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)

    if request.method == 'POST':
        form = RateChangeForm(request.POST)
        if form.is_valid():
            new_plan = form.cleaned_data.get('plan')
            new_rate = form.cleaned_data.get('monthly_rate')
            effective_date = form.cleaned_data['effective_date']
            apply_mode = form.cleaned_data['apply_mode']
            note = form.cleaned_data.get('note', '')

            if not new_rate and new_plan:
                new_rate = new_plan.monthly_rate

            history = apply_rate_change(
                subscriber=subscriber,
                new_plan=new_plan,
                new_rate=new_rate,
                effective_date=effective_date,
                apply_mode=apply_mode,
                note=note,
                changed_by=request.user.username,
            )

            if apply_mode == 'manual':
                invoice_ids = request.POST.getlist('invoice_ids')
                if invoice_ids:
                    from apps.billing.models import Invoice
                    Invoice.objects.filter(
                        pk__in=invoice_ids,
                        subscriber=subscriber,
                        status__in=['open', 'partial'],
                    ).update(amount=new_rate, rate_snapshot=new_rate)

            AuditLog.log('update', 'subscribers',
                         f"Rate changed for {subscriber.username}: PHP {new_rate} from {effective_date}",
                         user=request.user)
            from apps.notifications.telegram import notify_event
            notify_event('plan_change', 'Plan/Rate Changed',
                         f"{subscriber.display_name}: PHP {new_rate} effective {effective_date}")
            messages.success(request, f"Rate updated to PHP {new_rate} effective {effective_date}.")
            return redirect('subscriber-detail', pk=pk)
    else:
        from apps.billing.models import Invoice
        open_invoices = Invoice.objects.filter(
            subscriber=subscriber,
            status__in=['open', 'partial'],
        ).order_by('period_start')
        form = RateChangeForm(initial={
            'plan': subscriber.plan,
            'monthly_rate': subscriber.monthly_rate,
            'effective_date': date.today(),
        })
        return render(request, 'subscribers/rate_change.html', {
            'form': form, 'subscriber': subscriber,
            'open_invoices': open_invoices,
        })

    return redirect('subscriber-detail', pk=pk)


# ── Status Actions ─────────────────────────────────────────────────────────────

@login_required
def subscriber_suspend(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        ok, err = suspend_subscriber(subscriber, suspended_by=request.user.username)
        if err and not ok:
            messages.warning(request, f"Status updated but MikroTik error: {err}")
        else:
            messages.success(request, f"{subscriber.display_name} suspended.")
    return redirect('subscriber-detail', pk=pk)


@login_required
def subscriber_reconnect(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        ok, err = reconnect_subscriber(subscriber, reconnected_by=request.user.username)
        if err and not ok:
            messages.warning(request, f"Status updated but MikroTik error: {err}")
        else:
            messages.success(request, f"{subscriber.display_name} reconnected.")
    return redirect('subscriber-detail', pk=pk)


@login_required
def subscriber_disconnect(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        form = DisconnectForm(request.POST)
        if form.is_valid():
            disconnect_subscriber(
                subscriber,
                reason=form.cleaned_data['reason'],
                disconnected_by=request.user.username,
            )
            messages.success(request, f"{subscriber.display_name} marked as disconnected.")
            return redirect('subscriber-detail', pk=pk)
    else:
        form = DisconnectForm()
    return render(request, 'subscribers/confirm_disconnect.html', {
        'subscriber': subscriber, 'form': form,
    })


@login_required
def subscriber_deceased(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        form = DeceasedForm(request.POST)
        if form.is_valid():
            mark_deceased(
                subscriber,
                deceased_date=form.cleaned_data['deceased_date'],
                note=form.cleaned_data['note'],
                marked_by=request.user.username,
            )
            messages.success(request, f"{subscriber.display_name} marked as deceased. Open invoices voided.")
            return redirect('subscriber-detail', pk=pk)
    else:
        form = DeceasedForm(initial={'deceased_date': date.today()})
    return render(request, 'subscribers/confirm_deceased.html', {
        'subscriber': subscriber, 'form': form,
    })


@login_required
def subscriber_archive(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        archive_subscriber(subscriber)
        messages.success(request, f"{subscriber.display_name} archived.")
        return redirect('subscriber-list')
    return render(request, 'subscribers/confirm_archive.html', {'subscriber': subscriber})


# ── Usage Chart Data API ───────────────────────────────────────────────────────

@login_required
def subscriber_usage_chart(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    view = request.GET.get('view', 'this_cycle')
    data = get_usage_chart_data(subscriber, view)
    return JsonResponse(data)


# ── Node Assignment ────────────────────────────────────────────────────────────

@login_required
def subscriber_assign_node(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        node_id = request.POST.get('node_id')
        port_label = request.POST.get('port_label', '')
        if node_id:
            node = get_object_or_404(NetworkNode, pk=node_id)
            SubscriberNode.objects.update_or_create(
                subscriber=subscriber,
                defaults={'node': node, 'port_label': port_label}
            )
            messages.success(request, f"Assigned to {node.name}.")
        else:
            SubscriberNode.objects.filter(subscriber=subscriber).delete()
            messages.success(request, 'Node assignment removed.')
    return redirect('subscriber-detail', pk=pk)


# ── Sync ──────────────────────────────────────────────────────────────────────

@login_required
def subscriber_sync(request):
    routers = Router.objects.filter(is_active=True, status='online')
    if not routers.exists():
        messages.error(request, 'No online routers. Add and sync a router first.')
        return redirect('subscriber-list')

    total_added = 0
    total_updated = 0
    for router in routers:
        added, updated, err = sync_ppp_secrets(router)
        if err:
            messages.error(request, f"{router.name}: {err}")
        else:
            total_added += added
            total_updated += updated
            sync_active_sessions(router)

    AuditLog.log('sync', 'subscribers',
                 f"Sync done. Added: {total_added}, Updated: {total_updated}", user=request.user)
    messages.success(request, f"Sync complete. New: {total_added}, Updated: {total_updated}.")
    return redirect('subscriber-list')


# ── Plans ─────────────────────────────────────────────────────────────────────

@login_required
def plan_list(request):
    plans = Plan.objects.all()
    return render(request, 'subscribers/plan_list.html', {'plans': plans})


@login_required
def plan_add(request):
    if request.method == 'POST':
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            AuditLog.log('create', 'subscribers', f"Plan added: {plan.name}", user=request.user)
            messages.success(request, f"Plan '{plan.name}' added.")
            return redirect('plan-list')
    else:
        form = PlanForm()
    return render(request, 'subscribers/plan_form.html', {'form': form, 'title': 'Add Plan'})


@login_required
def plan_edit(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    if request.method == 'POST':
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'subscribers', f"Plan updated: {plan.name}", user=request.user)
            messages.success(request, 'Plan updated.')
            return redirect('plan-list')
    else:
        form = PlanForm(instance=plan)
    return render(request, 'subscribers/plan_form.html', {'form': form, 'title': 'Edit Plan', 'plan': plan})


# ── Manual Add ────────────────────────────────────────────────────────────────

@login_required
def subscriber_add(request):
    if request.method == 'POST':
        form = ManualSubscriberForm(request.POST)
        if form.is_valid():
            subscriber = form.save()
            AuditLog.log('create', 'subscribers',
                         f"Subscriber manually added: {subscriber.username}", user=request.user)
            from apps.notifications.telegram import notify_event
            notify_event('new_subscriber', 'New Subscriber Added',
                         f"{subscriber.display_name} ({subscriber.username}) added manually.")
            messages.success(request, f"Subscriber '{subscriber.username}' added.")
            return redirect('subscriber-detail', pk=subscriber.pk)
    else:
        form = ManualSubscriberForm()
    return render(request, 'subscribers/add.html', {'form': form})


# ── Client Portal ─────────────────────────────────────────────────────────────

def portal_request_otp(request):
    if request.method == 'POST':
        form = OTPRequestForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            try:
                subscriber = Subscriber.objects.get(phone=phone)
            except Subscriber.DoesNotExist:
                messages.error(request, 'No account found with this phone number.')
                return render(request, 'subscribers/portal_otp_request.html', {'form': form})

            if subscriber.status in ('deceased', 'archived'):
                messages.error(request, 'This account is no longer active.')
                return render(request, 'subscribers/portal_otp_request.html', {'form': form})

            otp = create_otp(subscriber)
            try:
                from apps.sms.semaphore import send_sms
                send_sms(phone, f"Your ISP Manager login code is: {otp.code}. Valid for 10 minutes.")
            except Exception:
                pass

            request.session['portal_phone'] = phone
            messages.success(request, 'OTP sent to your phone.')
            return redirect('portal-verify-otp')
    else:
        form = OTPRequestForm()
    return render(request, 'subscribers/portal_otp_request.html', {'form': form})


def portal_verify_otp(request):
    phone = request.session.get('portal_phone', '')
    if not phone:
        return redirect('portal-request-otp')

    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            subscriber, error = verify_otp(phone, form.cleaned_data['code'])
            if subscriber:
                request.session['portal_subscriber_id'] = subscriber.pk
                request.session.pop('portal_phone', None)
                return redirect('portal-dashboard')
            else:
                messages.error(request, error)
    else:
        form = OTPVerifyForm(initial={'phone': phone})
    return render(request, 'subscribers/portal_otp_verify.html', {'form': form, 'phone': phone})


def portal_dashboard(request):
    subscriber_id = request.session.get('portal_subscriber_id')
    if not subscriber_id:
        return redirect('portal-request-otp')

    subscriber = get_object_or_404(Subscriber, pk=subscriber_id)

    from apps.billing.models import Invoice, BillingSnapshot, Payment
    latest_snapshot = subscriber.billing_snapshots.filter(
        status__in=['frozen', 'issued']
    ).order_by('-cutoff_date').first()

    invoices = subscriber.invoices.all().order_by('-period_start')[:5]
    snapshots = subscriber.billing_snapshots.filter(
        status__in=['frozen', 'issued']
    ).order_by('-cutoff_date')[:12]
    payments = subscriber.payments.all().order_by('-paid_at')[:10]

    usage_today = subscriber.usage_daily.filter(date=date.today()).first()
    usage_data = get_usage_chart_data(subscriber, 'this_cycle')
    usage_rx_today = usage_today.rx_gb if usage_today else 0
    usage_tx_today = usage_today.tx_gb if usage_today else 0

    return render(request, 'subscribers/portal_dashboard.html', {
        'subscriber': subscriber,
        'latest_snapshot': latest_snapshot,
        'invoices': invoices,
        'snapshots': snapshots,
        'payments': payments,
        'usage_today': usage_today,
        'usage_data': usage_data,
        'usage_rx_today': usage_rx_today,
        'usage_tx_today': usage_tx_today,
    })


def portal_logout(request):
    request.session.pop('portal_subscriber_id', None)
    request.session.pop('portal_phone', None)
    return redirect('portal-request-otp')
