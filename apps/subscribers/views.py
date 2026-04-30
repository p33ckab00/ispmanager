from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from apps.subscribers.models import Subscriber, Plan, RateHistory, NetworkNode, SubscriberNode
from apps.subscribers.forms import (
    SubscriberAdminForm, PlanForm, ManualSubscriberForm,
    OTPRequestForm, OTPVerifyForm, StatusChangeForm,
    DeceasedForm, DisconnectForm, RateChangeForm, SuspensionHoldForm,
)
from apps.subscribers.services import (
    sync_ppp_secrets, sync_active_sessions,
    SUBSCRIBER_BILLING_AUDIT_FIELDS,
    audit_subscriber_field_changes,
    transition_subscriber_status,
    disconnect_subscriber, mark_deceased, archive_subscriber,
    get_subscriber_billing_readiness, get_usage_chart_data,
)
from apps.nms.services import (
    get_service_attachment,
    get_subscriber_topology_summary,
    has_service_attachment_table,
)
from apps.nms.models import ServiceAttachment
from apps.billing.services import apply_rate_change
from apps.subscribers.otp import create_otp, find_portal_subscriber_by_phone, verify_otp_for_subscriber
from apps.routers.models import Router
from apps.core.models import AuditLog
from apps.sms.services import send_subscriber_billing_sms


def _require_subscriber_perm(request, permission_codename, redirect_to='subscriber-list',
                             subscriber_pk=None):
    permission = f"subscribers.{permission_codename}"
    if request.user.has_perm(permission):
        return True

    messages.error(request, 'You do not have permission to perform that subscriber action.')
    if subscriber_pk:
        return redirect('subscriber-detail', pk=subscriber_pk)
    return redirect(redirect_to)


# ── Subscriber List ────────────────────────────────────────────────────────────

@login_required
def subscriber_list(request):
    qs = Subscriber.objects.select_related('router', 'plan', 'node_assignment__node').all()

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(normalized_phone__icontains=q) |
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
    service_attachment_ready = has_service_attachment_table()
    for subscriber in page.object_list:
        subscriber.topology_summary = get_subscriber_topology_summary(
            subscriber,
            table_ready=service_attachment_ready,
        )
        subscriber.billing_readiness = get_subscriber_billing_readiness(subscriber)

    return render(request, 'subscribers/list.html', {
        'page_obj': page, 'q': q, 'status': status,
        'service': service, 'total': qs.count(),
    })


# ── Subscriber Detail ──────────────────────────────────────────────────────────

@login_required
def subscriber_detail(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)

    from apps.billing.models import AccountCreditAdjustment, Invoice, BillingSnapshot, Payment
    from apps.billing.services import (
        get_account_credit_summary_for_subscriber,
        mark_overdue_invoices,
        resolve_billing_profile,
    )
    mark_overdue_invoices()

    invoices = Invoice.objects.filter(subscriber=subscriber).order_by('-period_start')
    snapshots = BillingSnapshot.objects.filter(subscriber=subscriber).order_by('-cutoff_date')
    payments = Payment.objects.filter(subscriber=subscriber).prefetch_related('allocations').order_by('-paid_at')
    credit_adjustments = AccountCreditAdjustment.objects.filter(subscriber=subscriber)
    credit_summary = get_account_credit_summary_for_subscriber(subscriber)
    rate_history = RateHistory.objects.filter(subscriber=subscriber).order_by('-effective_date')
    latest_snapshot = snapshots.first()
    overdue_invoice_count = invoices.filter(status='overdue').count()

    open_balance = sum(
        inv.remaining_balance for inv in
        invoices.filter(status__in=['open', 'partial', 'overdue'])
    )

    node_assignment = None
    try:
        node_assignment = subscriber.node_assignment
    except Exception:
        pass
    topology_summary = get_subscriber_topology_summary(
        subscriber,
        table_ready=has_service_attachment_table(),
    )

    usage_views = [('this_cycle','This Cycle'),('last_7','Last 7 Days'),('last_30','Last 30 Days'),('by_cycle','By Cycle')]
    billing_profile = resolve_billing_profile(subscriber)
    billing_readiness = get_subscriber_billing_readiness(subscriber)
    return render(request, 'subscribers/detail.html', {
        'subscriber': subscriber,
        'invoices': invoices[:10],
        'snapshots': snapshots[:10],
        'payments': payments[:10],
        'credit_adjustments': credit_adjustments[:10],
        'credit_summary': credit_summary,
        'rate_history': rate_history[:10],
        'latest_snapshot': latest_snapshot,
        'open_balance': open_balance,
        'overdue_invoice_count': overdue_invoice_count,
        'has_active_palugit': subscriber.has_active_suspension_hold,
        'palugit_until': timezone.localtime(subscriber.suspension_hold_until) if subscriber.has_active_suspension_hold else None,
        'node_assignment': node_assignment,
        'topology_summary': topology_summary,
        'nodes': NetworkNode.objects.filter(is_active=True).order_by('name'),
        'usage_views': usage_views,
        'billing_profile': billing_profile,
        'billing_readiness': billing_readiness,
    })


@login_required
def subscriber_send_billing_sms(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method != 'POST':
        return redirect('subscriber-detail', pk=pk)
    if not request.user.has_perm('sms.add_smslog'):
        messages.error(request, 'You do not have permission to send billing SMS.')
        return redirect('subscriber-detail', pk=pk)

    log, err, snapshot = send_subscriber_billing_sms(
        subscriber=subscriber,
        sent_by=request.user.username,
    )
    if err:
        messages.error(request, f"Billing SMS failed: {err}")
        return redirect('subscriber-detail', pk=pk)

    AuditLog.log(
        'send',
        'sms',
        f"Billing SMS sent to {subscriber.username} using snapshot {snapshot.snapshot_number}",
        user=request.user,
    )
    messages.success(
        request,
        f"Billing SMS sent to {subscriber.display_name} for {snapshot.snapshot_number}."
    )
    return redirect('subscriber-detail', pk=pk)


# ── Edit Admin Fields ──────────────────────────────────────────────────────────

@login_required
def subscriber_edit(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk)
    permission_check = _require_subscriber_perm(
        request,
        'change_subscriber',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    if request.method == 'POST':
        old_status = subscriber.status
        form = SubscriberAdminForm(request.POST, instance=subscriber)
        if form.is_valid():
            target_status = form.cleaned_data['status']
            changed_fields = [field for field in form.changed_data if field != 'status']
            billing_changed = bool(SUBSCRIBER_BILLING_AUDIT_FIELDS.intersection(changed_fields))
            if billing_changed and not request.user.has_perm('subscribers.manage_subscriber_billing'):
                messages.error(request, 'You do not have permission to change subscriber billing fields.')
                return redirect('subscriber-detail', pk=pk)
            if target_status != old_status and not request.user.has_perm('subscribers.manage_subscriber_lifecycle'):
                messages.error(request, 'You do not have permission to change subscriber lifecycle status.')
                return redirect('subscriber-detail', pk=pk)

            before = Subscriber.objects.get(pk=pk)
            updated_subscriber = form.save(commit=False)
            updated_subscriber.status = old_status
            updated_subscriber.save()
            audit_count = audit_subscriber_field_changes(
                before,
                updated_subscriber,
                changed_fields,
                user=request.user,
            )

            AuditLog.log('update', 'subscribers',
                         f"Subscriber info updated: {subscriber.username} ({audit_count} field change(s))", user=request.user)
            if target_status != old_status:
                ok, err = transition_subscriber_status(
                    updated_subscriber,
                    target_status,
                    changed_by=request.user.username,
                    reason='Profile edit',
                )
                updated_subscriber.refresh_from_db()
                if err and updated_subscriber.status == target_status:
                    messages.warning(request, f"Information saved and status updated, but MikroTik warning: {err}")
                elif err:
                    messages.error(request, f"Information saved, but status was not changed: {err}")
                else:
                    messages.success(
                        request,
                        f"Subscriber information updated. Status changed to {updated_subscriber.get_status_display()}."
                    )
                    return redirect('subscriber-detail', pk=pk)
            else:
                messages.success(request, 'Subscriber information updated.')
            return redirect('subscriber-detail', pk=pk)
    else:
        form = SubscriberAdminForm(instance=subscriber)
    return render(request, 'subscribers/edit.html', {'form': form, 'subscriber': subscriber})


# ── Rate / Plan Change ─────────────────────────────────────────────────────────

@login_required
def subscriber_rate_change(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_billing',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        ok, err = transition_subscriber_status(
            subscriber,
            'suspended',
            changed_by=request.user.username,
        )
        subscriber.refresh_from_db()
        if err and subscriber.status == 'suspended':
            messages.warning(request, f"Status updated but MikroTik error: {err}")
        elif err:
            messages.error(request, err)
        else:
            messages.success(request, f"{subscriber.display_name} suspended.")
    return redirect('subscriber-detail', pk=pk)


@login_required
def subscriber_reconnect(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        old_status = subscriber.status
        ok, err = transition_subscriber_status(
            subscriber,
            'active',
            changed_by=request.user.username,
        )
        subscriber.refresh_from_db()
        if err and subscriber.status == 'active':
            messages.warning(request, f"Status updated but MikroTik error: {err}")
        elif err:
            messages.error(request, err)
        else:
            action = 'activated' if old_status == 'inactive' else 'reconnected'
            messages.success(request, f"{subscriber.display_name} {action}.")
    return redirect('subscriber-detail', pk=pk)


@login_required
def subscriber_palugit(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    if subscriber.status in ['disconnected', 'deceased', 'archived']:
        messages.error(request, 'Palugit is only available for serviceable subscriber accounts.')
        return redirect('subscriber-detail', pk=pk)

    initial = {}
    if subscriber.has_active_suspension_hold:
        initial = {
            'suspension_hold_until': timezone.localtime(subscriber.suspension_hold_until).strftime('%Y-%m-%dT%H:%M'),
            'suspension_hold_reason': subscriber.suspension_hold_reason,
        }

    if request.method == 'POST':
        form = SuspensionHoldForm(request.POST)
        if form.is_valid():
            subscriber.suspension_hold_until = form.cleaned_data['suspension_hold_until']
            subscriber.suspension_hold_reason = form.cleaned_data['suspension_hold_reason']
            subscriber.suspension_hold_by = request.user.username
            subscriber.suspension_hold_created_at = timezone.now()
            subscriber.save(update_fields=[
                'suspension_hold_until',
                'suspension_hold_reason',
                'suspension_hold_by',
                'suspension_hold_created_at',
                'updated_at',
            ])
            AuditLog.log(
                'update',
                'subscribers',
                f"Palugit set for {subscriber.username} until {subscriber.suspension_hold_until}",
                user=request.user,
            )
            messages.success(
                request,
                f"Palugit saved for {subscriber.display_name} until {timezone.localtime(subscriber.suspension_hold_until).strftime('%b %d, %Y %I:%M %p')}.",
            )
            return redirect('subscriber-detail', pk=pk)
    else:
        form = SuspensionHoldForm(initial=initial)

    return render(request, 'subscribers/palugit_form.html', {
        'subscriber': subscriber,
        'form': form,
        'has_active_palugit': subscriber.has_active_suspension_hold,
        'palugit_until': timezone.localtime(subscriber.suspension_hold_until) if subscriber.has_active_suspension_hold else None,
    })


@login_required
def subscriber_palugit_remove(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        subscriber.suspension_hold_until = None
        subscriber.suspension_hold_reason = ''
        subscriber.suspension_hold_by = ''
        subscriber.suspension_hold_created_at = None
        subscriber.save(update_fields=[
            'suspension_hold_until',
            'suspension_hold_reason',
            'suspension_hold_by',
            'suspension_hold_created_at',
            'updated_at',
        ])
        AuditLog.log('update', 'subscribers', f"Palugit removed for {subscriber.username}", user=request.user)
        messages.success(request, f"Palugit removed for {subscriber.display_name}.")
    return redirect('subscriber-detail', pk=pk)


@login_required
def subscriber_disconnect(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    from apps.settings_app.models import SubscriberSettings
    from apps.billing.services import get_account_credit_for_subscriber
    subscriber_settings = SubscriberSettings.get_settings()
    account_credit = get_account_credit_for_subscriber(subscriber)
    if request.method == 'POST':
        form = DisconnectForm(request.POST)
        if form.is_valid():
            ok, err, billing_result, credit_result = disconnect_subscriber(
                subscriber,
                reason=form.cleaned_data['reason'],
                disconnected_by=request.user.username,
            )
            messages.success(request, f"{subscriber.display_name} marked as disconnected.")
            if err:
                messages.warning(request, f"MikroTik disconnect warning: {err}")
            if billing_result.get('message'):
                messages.info(request, billing_result['message'])
            for billing_error in billing_result.get('errors', [])[:3]:
                messages.warning(request, billing_error)
            if credit_result.get('message'):
                messages.info(request, credit_result['message'])
            for credit_error in credit_result.get('errors', [])[:3]:
                messages.warning(request, credit_error)
            return redirect('subscriber-detail', pk=pk)
    else:
        form = DisconnectForm()
    return render(request, 'subscribers/confirm_disconnect.html', {
        'subscriber': subscriber,
        'form': form,
        'subscriber_settings': subscriber_settings,
        'account_credit': account_credit,
    })


@login_required
def subscriber_deceased(request, pk):
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(
        request,
        'manage_subscriber_lifecycle',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(
        request,
        'change_subscriber',
        subscriber_pk=pk,
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=pk)
    if request.method == 'POST':
        if get_service_attachment(subscriber):
            messages.warning(
                request,
                'This subscriber already has an active Premium NMS mapping. Reassign it inside the NMS workspace instead.',
            )
            return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)

        node_id = request.POST.get('node_id')
        port_label = (request.POST.get('port_label', '') or '').strip()
        if node_id:
            node = get_object_or_404(NetworkNode, pk=node_id)
            SubscriberNode.objects.update_or_create(
                subscriber=subscriber,
                defaults={'node': node, 'port_label': port_label[:50]}
            )
            if has_service_attachment_table():
                attachment, created = ServiceAttachment.objects.update_or_create(
                    subscriber=subscriber,
                    defaults={
                        'node': node,
                        'endpoint': None,
                        'endpoint_label': port_label[:80],
                        'status': 'active',
                        'assigned_by': request.user.username,
                    },
                )
                AuditLog.log(
                    'create' if created else 'update',
                    'nms',
                    f"Subscriber assignment mirrored to Premium NMS for {subscriber.username}: {node.name}",
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Assigned to {node.name}. Premium NMS mapping is now active.",
                )
            else:
                messages.success(request, f"Assigned to {node.name}.")
        else:
            SubscriberNode.objects.filter(subscriber=subscriber).delete()
            messages.success(request, 'Node assignment removed.')
    return redirect('subscriber-detail', pk=pk)


# ── Sync ──────────────────────────────────────────────────────────────────────

@login_required
def subscriber_sync(request):
    permission_check = _require_subscriber_perm(request, 'import_subscribers')
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(request, 'add_plan')
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(request, 'change_plan')
    if permission_check is not True:
        return permission_check

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
    permission_check = _require_subscriber_perm(request, 'add_subscriber')
    if permission_check is not True:
        return permission_check

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
            subscriber, error, normalized_phone = find_portal_subscriber_by_phone(phone)
            if error:
                messages.error(request, error)
                return render(request, 'subscribers/portal_otp_request.html', {'form': form})

            if subscriber.status in ('deceased', 'archived'):
                messages.error(request, 'This account is no longer active.')
                return render(request, 'subscribers/portal_otp_request.html', {'form': form})

            otp = create_otp(subscriber)
            try:
                from apps.sms.semaphore import send_sms
                send_sms(subscriber.phone, f"Your ISP Manager login code is: {otp.code}. Valid for 10 minutes.")
            except Exception as e:
                messages.error(request, f"OTP created but SMS delivery failed: {e}")
                return render(request, 'subscribers/portal_otp_request.html', {'form': form})

            request.session['portal_phone'] = subscriber.phone
            request.session['portal_normalized_phone'] = normalized_phone
            request.session['portal_otp_subscriber_id'] = subscriber.pk
            messages.success(request, 'OTP sent to your phone.')
            return redirect('portal-verify-otp')
    else:
        form = OTPRequestForm()
    return render(request, 'subscribers/portal_otp_request.html', {'form': form})


def portal_verify_otp(request):
    phone = request.session.get('portal_phone', '')
    subscriber_id = request.session.get('portal_otp_subscriber_id')
    if not phone or not subscriber_id:
        return redirect('portal-request-otp')

    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            subscriber, error = verify_otp_for_subscriber(subscriber_id, form.cleaned_data['code'])
            if subscriber:
                request.session['portal_subscriber_id'] = subscriber.pk
                request.session.pop('portal_phone', None)
                request.session.pop('portal_normalized_phone', None)
                request.session.pop('portal_otp_subscriber_id', None)
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
    request.session.pop('portal_normalized_phone', None)
    request.session.pop('portal_otp_subscriber_id', None)
    return redirect('portal-request-otp')
