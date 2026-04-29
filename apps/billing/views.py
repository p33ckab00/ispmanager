import calendar as calendar_module
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import OperationalError
from django.db.models import Q
from apps.billing.models import AccountCreditAdjustment, Invoice, Payment, BillingSnapshot, BillingSnapshotItem
from apps.billing.forms import PaymentForm, RateChangeForm, RefundCompletionForm
from apps.billing.services import (
    generate_invoices_for_all, generate_invoice_for_subscriber,
    record_payment_with_allocation, generate_snapshot_for_subscriber,
    get_billing_previews, mark_overdue_invoices,
    complete_refund_credit_adjustment,
)
from apps.subscribers.models import Subscriber
from apps.settings_app.models import BillingSettings, SMSSettings
from apps.core.models import AuditLog


SMS_SKIP_LABELS = {
    'billing_sms_disabled': 'SMS disabled',
    'paid_or_credit_covered': 'Paid or credit-covered',
    'sms_opt_out': 'Opted out',
    'missing_phone': 'Missing phone',
    'frozen_snapshot_missing': 'Frozen statement missing',
    'before_sms_window': 'Before SMS window',
    'after_due_date': 'After due date',
    'already_sent_today': 'Already sent today',
    'already_attempted_today': 'Already attempted today',
    'outside_sms_window': 'Outside SMS window',
}
SMS_SKIP_REASONS = set(SMS_SKIP_LABELS.keys())


def _require_billing_perm(request, permission, redirect_to='billing-list'):
    if request.user.has_perm(permission):
        return True
    messages.error(request, 'You do not have permission to perform that billing action.')
    return redirect(redirect_to)


def _queue_events_for_preview(preview, target_date):
    events = []
    if preview['errors']:
        events.append({
            'key': 'attention',
            'label': 'Needs attention',
            'classes': 'bg-red-50 text-red-700',
        })
    if preview['generation_date'] == target_date:
        events.append({
            'key': 'generation',
            'label': 'Generate billing',
            'classes': 'bg-blue-50 text-blue-700',
        })
    if preview['due_date'] == target_date:
        events.append({
            'key': 'due',
            'label': 'Due today',
            'classes': 'bg-orange-50 text-orange-700',
        })
    if target_date in preview['sms'].get('send_dates', []):
        events.append({
            'key': 'sms',
            'label': 'SMS reminder',
            'classes': 'bg-green-50 text-green-700',
        })

    if not events:
        events.append({
            'key': 'upcoming',
            'label': 'Upcoming',
            'classes': 'bg-gray-50 text-gray-500',
        })
    return events


def _queue_action_label(preview, event_keys):
    if preview['errors']:
        return 'Fix setup'
    if 'generation' in event_keys:
        if preview['invoice'] and preview['snapshot']:
            return 'Generated'
        return 'Ready to generate'
    if 'sms' in event_keys:
        if preview['sms']['last_attempt_status'] == 'failed' and not preview['sms']['sent_today']:
            return 'Retry failed SMS'
        if preview['sms']['eligible_today']:
            return 'Ready for SMS'
        return SMS_SKIP_LABELS.get(preview['sms']['skip_reason'], 'Check SMS')
    if 'due' in event_keys:
        if preview['total_due'] <= Decimal('0.00'):
            return 'Settled'
        return 'Collect payment'
    return 'Monitor'


def _billing_queue_rows_for_date(subscribers, billing_settings, sms_settings, target_date):
    rows = []
    for preview in get_billing_previews(
        reference_date=target_date,
        subscribers=subscribers,
        billing_settings=billing_settings,
        sms_settings=sms_settings,
    ):
        events = _queue_events_for_preview(preview, target_date)
        event_keys = {event['key'] for event in events}
        day_has_event = bool(event_keys - {'upcoming'})
        row = dict(preview)
        row.update({
            'events': events,
            'event_keys': event_keys,
            'day_has_event': day_has_event,
            'can_bulk_generate': preview['can_generate'] and 'generation' in event_keys,
            'can_send_sms': preview['sms']['eligible_today'],
            'can_retry_sms': (
                preview['snapshot']
                and 'sms' in event_keys
                and preview['sms']['last_attempt_status'] == 'failed'
                and not preview['sms']['sent_today']
            ),
            'sms_status_label': (
                'Eligible today'
                if preview['sms']['eligible_today']
                else SMS_SKIP_LABELS.get(preview['sms']['skip_reason'], 'Not scheduled')
            ),
            'action_label': _queue_action_label(preview, event_keys),
        })
        rows.append(row)
    return rows


def _billing_queue_summary(rows):
    summary_source = [row for row in rows if row['day_has_event']]
    return {
        'day_events': len(summary_source),
        'generation': sum(1 for row in rows if 'generation' in row['event_keys']),
        'due': sum(1 for row in rows if 'due' in row['event_keys']),
        'sms': sum(1 for row in rows if 'sms' in row['event_keys']),
        'attention': sum(1 for row in rows if 'attention' in row['event_keys']),
        'total_due': sum((row['total_due'] for row in summary_source), Decimal('0.00')),
    }


def _parse_calendar_month(month_value, fallback_date):
    if month_value:
        parsed = None
        if len(month_value) == 7:
            parsed = parse_date(f"{month_value}-01")
        else:
            parsed = parse_date(month_value)
        if parsed:
            return parsed.replace(day=1)
    return fallback_date.replace(day=1)


def _shift_month(month_start, offset):
    absolute_month = month_start.year * 12 + (month_start.month - 1) + offset
    return date(absolute_month // 12, absolute_month % 12 + 1, 1)


def _queue_redirect_url(selected_date, event_filter, billing_type, q):
    params = {
        'date': selected_date.isoformat(),
        'event': event_filter or 'day',
    }
    if billing_type:
        params['billing_type'] = billing_type
    if q:
        params['q'] = q
    return f"/billing/queue/?{urlencode(params)}"


def _run_queue_generation_action(request, selected_date, billing_settings,
                                 sms_settings, event_filter, billing_type, q):
    action = request.POST.get('bulk_action', '')
    selected_ids = request.POST.getlist('subscriber_ids')
    redirect_url = _queue_redirect_url(selected_date, event_filter, billing_type, q)

    if action not in ('generate_invoices', 'generate_snapshots', 'send_sms', 'retry_failed_sms'):
        messages.error(request, 'Unknown billing queue action.')
        return redirect(redirect_url)
    required_permission = {
        'generate_invoices': 'billing.add_invoice',
        'generate_snapshots': 'billing.add_billingsnapshot',
        'send_sms': 'sms.add_smslog',
        'retry_failed_sms': 'sms.add_smslog',
    }[action]
    permission_check = _require_billing_perm(request, required_permission, redirect_url)
    if permission_check is not True:
        return permission_check
    if not selected_ids:
        messages.warning(request, 'Select at least one eligible subscriber.')
        return redirect(redirect_url)

    subscribers = Subscriber.objects.filter(
        pk__in=selected_ids,
        status__in=['active', 'suspended'],
        is_billable=True,
    ).select_related('plan').order_by('username')

    created = 0
    sent = 0
    skipped = 0
    errors = []
    action_label = {
        'generate_invoices': 'invoices',
        'generate_snapshots': 'statements',
        'send_sms': 'billing SMS',
        'retry_failed_sms': 'failed billing SMS retries',
    }[action]

    for subscriber in subscribers:
        preview = get_billing_previews(
            reference_date=selected_date,
            subscribers=[subscriber],
            billing_settings=billing_settings,
            sms_settings=sms_settings,
        )[0]

        if action in ('generate_invoices', 'generate_snapshots') and preview['generation_date'] != selected_date:
            skipped += 1
            continue
        if action in ('generate_invoices', 'generate_snapshots') and preview['errors']:
            errors.append(f"{subscriber.username}: {'; '.join(preview['errors'])}")
            continue

        try:
            if action == 'generate_invoices':
                obj, err = generate_invoice_for_subscriber(
                    subscriber,
                    billing_settings=billing_settings,
                    reference_date=selected_date,
                )
                duplicate_text = 'already exists'
            elif action == 'generate_snapshots':
                obj, err = generate_snapshot_for_subscriber(
                    subscriber,
                    billing_settings=billing_settings,
                    reference_date=selected_date,
                    created_by=request.user.username,
                )
                duplicate_text = 'already exists'
            else:
                if not preview['snapshot']:
                    skipped += 1
                    continue
                if action == 'send_sms' and not preview['sms']['eligible_today']:
                    skipped += 1
                    continue
                if (
                    action == 'retry_failed_sms'
                    and not (
                        preview['sms']['last_attempt_status'] == 'failed'
                        and not preview['sms']['sent_today']
                    )
                ):
                    skipped += 1
                    continue

                from apps.sms.services import send_billing_sms
                obj, err = send_billing_sms(
                    preview['snapshot'],
                    sent_by=request.user.username,
                    enforce_schedule=True,
                    reference_date=selected_date,
                    allow_failed_retry=(action == 'retry_failed_sms'),
                )
                duplicate_text = ''
        except OperationalError as exc:
            errors.append(f"{subscriber.username}: {exc}")
            continue

        if action in ('send_sms', 'retry_failed_sms') and obj and err is None:
            sent += 1
        elif action in ('send_sms', 'retry_failed_sms') and err in SMS_SKIP_REASONS:
            skipped += 1
        elif obj and err is None:
            created += 1
        elif err and duplicate_text in err:
            skipped += 1
        elif err:
            errors.append(f"{subscriber.username}: {err}")

    AuditLog.log(
        'create',
        'billing',
        f"Queue bulk {action_label}: {created} created, {sent} sent, {skipped} skipped, {len(errors)} errors",
        user=request.user,
    )
    if action in ('send_sms', 'retry_failed_sms'):
        messages.success(
            request,
            f"Queue bulk {action_label} complete. Sent: {sent}, Skipped: {skipped}, Errors: {len(errors)}."
        )
    else:
        messages.success(
            request,
            f"Queue bulk {action_label} complete. Created: {created}, Skipped: {skipped}, Errors: {len(errors)}."
        )
    for error in errors[:5]:
        messages.warning(request, error)
    if len(errors) > 5:
        messages.warning(request, f"{len(errors) - 5} more error(s) were not shown.")

    return redirect(redirect_url)


@login_required
def billing_calendar(request):
    today = timezone.localdate()
    month_start = _parse_calendar_month(request.GET.get('month', ''), today)
    previous_month = _shift_month(month_start, -1)
    next_month = _shift_month(month_start, 1)
    billing_type = request.GET.get('billing_type', '')

    billing_settings = BillingSettings.get_settings()
    sms_settings = SMSSettings.get_settings()
    subscribers = Subscriber.objects.filter(
        status__in=['active', 'suspended'],
        is_billable=True,
    ).select_related('plan').order_by('username')
    if billing_type in ('postpaid', 'prepaid'):
        subscribers = subscribers.filter(billing_type=billing_type)

    calendar_days = []
    month_totals = {
        'day_events': 0,
        'generation': 0,
        'due': 0,
        'sms': 0,
        'attention': 0,
        'total_due': Decimal('0.00'),
    }

    month_calendar = calendar_module.Calendar(firstweekday=0)
    for week in month_calendar.monthdatescalendar(month_start.year, month_start.month):
        week_cells = []
        for day in week:
            rows = _billing_queue_rows_for_date(
                subscribers,
                billing_settings,
                sms_settings,
                day,
            )
            summary = _billing_queue_summary(rows)
            if day.month == month_start.month:
                for key in ('day_events', 'generation', 'due', 'sms', 'attention'):
                    month_totals[key] += summary[key]
                month_totals['total_due'] += summary['total_due']

            week_cells.append({
                'date': day,
                'is_current_month': day.month == month_start.month,
                'is_today': day == today,
                'summary': summary,
            })
        calendar_days.append(week_cells)

    return render(request, 'billing/calendar.html', {
        'calendar_days': calendar_days,
        'month_start': month_start,
        'previous_month': previous_month,
        'next_month': next_month,
        'today': today,
        'month_totals': month_totals,
        'billing_type': billing_type,
    })


@login_required
def billing_queue(request):
    today = timezone.localdate()
    selected_date = parse_date(request.GET.get('date', '')) or today
    q = request.GET.get('q', '').strip()
    event_filter = request.GET.get('event', 'day')
    billing_type = request.GET.get('billing_type', '')

    billing_settings = BillingSettings.get_settings()
    sms_settings = SMSSettings.get_settings()
    subscribers = Subscriber.objects.filter(
        status__in=['active', 'suspended'],
        is_billable=True,
    ).select_related('plan').order_by('username')

    if q:
        subscribers = subscribers.filter(
            Q(username__icontains=q)
            | Q(full_name__icontains=q)
            | Q(phone__icontains=q)
        )
    if billing_type in ('postpaid', 'prepaid'):
        subscribers = subscribers.filter(billing_type=billing_type)

    if request.method == 'POST':
        return _run_queue_generation_action(
            request,
            selected_date,
            billing_settings,
            sms_settings,
            event_filter,
            billing_type,
            q,
        )

    rows = _billing_queue_rows_for_date(subscribers, billing_settings, sms_settings, selected_date)
    summary = _billing_queue_summary(rows)
    summary_source = [row for row in rows if row['day_has_event']]

    if event_filter == 'all':
        filtered_rows = rows
    elif event_filter == 'generation':
        filtered_rows = [row for row in rows if 'generation' in row['event_keys']]
    elif event_filter == 'due':
        filtered_rows = [row for row in rows if 'due' in row['event_keys']]
    elif event_filter == 'sms':
        filtered_rows = [row for row in rows if 'sms' in row['event_keys']]
    elif event_filter == 'attention':
        filtered_rows = [row for row in rows if 'attention' in row['event_keys']]
    else:
        event_filter = 'day'
        filtered_rows = summary_source

    paginator = Paginator(filtered_rows, 50)
    page = paginator.get_page(request.GET.get('page', 1))
    from apps.sms.models import SMSLog
    for row in page.object_list:
        if row['snapshot']:
            row['sms_logs'] = list(SMSLog.objects.filter(
                billing_snapshot=row['snapshot'],
                sms_type='billing',
            ).order_by('-created_at')[:3])
        else:
            row['sms_logs'] = []

    return render(request, 'billing/queue.html', {
        'page_obj': page,
        'summary': summary,
        'selected_date': selected_date,
        'previous_date': selected_date - timedelta(days=1),
        'next_date': selected_date + timedelta(days=1),
        'today': today,
        'q': q,
        'event_filter': event_filter,
        'billing_type': billing_type,
        'event_options': [
            ('day', 'Day events'),
            ('generation', 'Generation'),
            ('due', 'Due'),
            ('sms', 'SMS'),
            ('attention', 'Attention'),
            ('all', 'All subscribers'),
        ],
    })


@login_required
def invoice_list(request):
    mark_overdue_invoices()
    qs = Invoice.objects.select_related('subscriber', 'subscriber__plan').all()
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        qs = qs.filter(Q(subscriber__username__icontains=q) | Q(subscriber__full_name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    summary = {
        'open': Invoice.objects.filter(status='open').count(),
        'overdue': Invoice.objects.filter(status='overdue').count(),
        'partial': Invoice.objects.filter(status='partial').count(),
        'paid': Invoice.objects.filter(status='paid').count(),
    }
    return render(request, 'billing/invoice_list.html', {
        'page_obj': page, 'q': q, 'status': status,
        'summary': summary, 'status_choices': Invoice.STATUS_CHOICES,
    })


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    allocations = invoice.allocations.select_related('payment').all()
    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice, 'allocations': allocations,
    })


@login_required
def generate_invoices(request):
    permission_check = _require_billing_perm(request, 'billing.add_invoice', 'invoice-list')
    if permission_check is not True:
        return permission_check

    if request.method == 'POST':
        sub_id = request.POST.get('subscriber_id', '').strip()
        if sub_id:
            try:
                sub = Subscriber.objects.get(pk=sub_id)
                inv, err = generate_invoice_for_subscriber(sub)
                if err and 'already exists' not in err:
                    messages.error(request, f"{sub.username}: {err}")
                else:
                    messages.success(request, f"Invoice generated for {sub.username}.")
                    if inv:
                        return redirect('invoice-detail', pk=inv.pk)
            except Subscriber.DoesNotExist:
                messages.error(request, 'Subscriber not found.')
        else:
            created, skipped, errors = generate_invoices_for_all()
            for e in errors:
                messages.warning(request, e)
            AuditLog.log('create', 'billing', f"Bulk invoices: {created} created, {skipped} skipped", user=request.user)
            messages.success(request, f"Done. Created: {created}, Skipped: {skipped}.")
        return redirect('invoice-list')
    subscribers = Subscriber.objects.filter(status__in=['active', 'suspended']).select_related('plan').order_by('username')
    return render(request, 'billing/generate.html', {'subscribers': subscribers})


@login_required
def record_payment(request, subscriber_pk):
    permission_check = _require_billing_perm(
        request,
        'billing.add_payment',
        f'/subscribers/{subscriber_pk}/',
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=subscriber_pk)
    open_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue']
    ).order_by('period_start')
    open_balance = sum(inv.remaining_balance for inv in open_invoices)

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment, unallocated = record_payment_with_allocation(
                subscriber=subscriber,
                amount=form.cleaned_data['amount'],
                method=form.cleaned_data['method'],
                reference=form.cleaned_data['reference'],
                notes=form.cleaned_data['notes'],
                paid_at=form.cleaned_data['paid_at'],
                recorded_by=request.user.username,
            )
            AuditLog.log('update', 'billing',
                         f"Payment PHP {payment.amount} for {subscriber.username}", user=request.user)
            from apps.notifications.telegram import notify_event
            notify_event('payment_received', 'Payment Received',
                         f"{subscriber.display_name}: PHP {payment.amount} via {payment.get_method_display()}")
            msg = f"Payment of PHP {payment.amount} recorded."
            if unallocated > 0:
                msg += f" PHP {unallocated} unallocated (credit)."
            messages.success(request, msg)
            reconnect_result = getattr(payment, 'auto_reconnect_result', None)
            if reconnect_result:
                if reconnect_result.get('reconnected'):
                    messages.success(request, 'Subscriber auto-reconnected after full payment.')
                    if reconnect_result.get('warning'):
                        messages.warning(request, f"MikroTik reconnect warning: {reconnect_result['warning']}")
                elif reconnect_result.get('error'):
                    messages.warning(request, f"Auto-reconnect did not complete: {reconnect_result['error']}")
            return redirect('subscriber-detail', pk=subscriber_pk)
    else:
        form = PaymentForm(initial={'amount': open_balance})

    return render(request, 'billing/record_payment.html', {
        'subscriber': subscriber,
        'form': form,
        'open_invoices': open_invoices,
    })


@login_required
def complete_refund(request, pk):
    adjustment = get_object_or_404(
        AccountCreditAdjustment.objects.select_related('subscriber', 'expense_record'),
        pk=pk,
    )
    subscriber = adjustment.subscriber
    if not request.user.has_perm('billing.change_accountcreditadjustment'):
        messages.error(request, 'You do not have permission to complete refund adjustments.')
        return redirect('subscriber-detail', pk=subscriber.pk)

    if adjustment.adjustment_type != 'refund_due' or adjustment.status != 'pending':
        messages.error(request, 'Only pending refund-due adjustments can be completed.')
        return redirect('subscriber-detail', pk=subscriber.pk)

    if request.method == 'POST':
        form = RefundCompletionForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['create_expense'] and not request.user.has_perm('accounting.add_expenserecord'):
                messages.error(request, 'You do not have permission to create accounting expense records.')
                return redirect('subscriber-detail', pk=subscriber.pk)
            try:
                completed, expense = complete_refund_credit_adjustment(
                    adjustment,
                    reference=form.cleaned_data['reference'],
                    notes=form.cleaned_data['notes'],
                    completed_by=request.user.username,
                    paid_at=form.cleaned_data['paid_at'],
                    create_expense=form.cleaned_data['create_expense'],
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('subscriber-detail', pk=subscriber.pk)

            AuditLog.log(
                'update',
                'billing',
                f"Refund completed for {subscriber.username}: PHP {completed.amount}",
                user=request.user,
            )
            msg = f"Refund marked paid for {subscriber.display_name}: PHP {completed.amount}."
            if expense:
                msg += ' Accounting expense created.'
            messages.success(request, msg)
            return redirect('subscriber-detail', pk=subscriber.pk)
    else:
        form = RefundCompletionForm(initial={'create_expense': True})

    return render(request, 'billing/refund_complete.html', {
        'form': form,
        'adjustment': adjustment,
        'subscriber': subscriber,
    })


@login_required
def snapshot_list(request):
    qs = BillingSnapshot.objects.select_related('subscriber').all()
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'billing/snapshot_list.html', {
        'page_obj': page, 'status': status,
        'status_choices': BillingSnapshot.STATUS_CHOICES,
    })


@login_required
def snapshot_detail(request, pk):
    snapshot = get_object_or_404(BillingSnapshot, pk=pk)
    items = snapshot.items.all()
    return render(request, 'billing/snapshot_detail.html', {'snapshot': snapshot, 'items': items})


@login_required
def snapshot_freeze(request, pk):
    permission_check = _require_billing_perm(request, 'billing.change_billingsnapshot', 'snapshot-list')
    if permission_check is not True:
        return permission_check

    snapshot = get_object_or_404(BillingSnapshot, pk=pk)
    if request.method == 'POST':
        snapshot.freeze(frozen_by=request.user.username)
        AuditLog.log('update', 'billing', f"Snapshot {snapshot.snapshot_number} frozen", user=request.user)
        messages.success(request, f"Snapshot {snapshot.snapshot_number} frozen and issued to client.")
        return redirect('snapshot-detail', pk=pk)
    return render(request, 'billing/confirm_freeze.html', {'snapshot': snapshot})


@login_required
def generate_snapshot(request, subscriber_pk):
    permission_check = _require_billing_perm(
        request,
        'billing.add_billingsnapshot',
        f'/subscribers/{subscriber_pk}/',
    )
    if permission_check is not True:
        return permission_check

    subscriber = get_object_or_404(Subscriber, pk=subscriber_pk)
    if request.method == 'POST':
        try:
            snapshot, err = generate_snapshot_for_subscriber(subscriber, created_by=request.user.username)
        except OperationalError as exc:
            if 'database is locked' in str(exc).lower():
                messages.error(
                    request,
                    'Snapshot generation is temporarily busy because another database operation is still running. '
                    'Please wait a few seconds and try again.'
                )
                return redirect('subscriber-detail', pk=subscriber_pk)
            raise
        if err and 'already exists' in err and snapshot:
            messages.info(request, err)
            return redirect('snapshot-detail', pk=snapshot.pk)
        if err:
            messages.error(request, err)
        else:
            AuditLog.log('create', 'billing', f"Snapshot generated for {subscriber.username}", user=request.user)
            messages.success(request, f"Snapshot {snapshot.snapshot_number} created.")
            return redirect('snapshot-detail', pk=snapshot.pk)
    return redirect('subscriber-detail', pk=subscriber_pk)


def billing_public_view(request, token):
    invoice = get_object_or_404(Invoice, token=token)
    return render(request, 'billing/public_view.html', {
        'invoice': invoice, 'subscriber': invoice.subscriber,
    })


def billing_short_url(request, short_code):
    invoice = get_object_or_404(Invoice, short_code=short_code)
    return redirect(invoice.get_full_billing_url())


def snapshot_pdf(request, pk, disposition='inline'):
    snapshot = get_object_or_404(BillingSnapshot, pk=pk)
    items = snapshot.items.all()

    if not request.user.is_authenticated:
        subscriber_id = request.session.get('portal_subscriber_id')
        if not subscriber_id or subscriber_id != snapshot.subscriber_id:
            from django.http import Http404
            raise Http404

    from apps.core.models import SystemSetup
    setup = SystemSetup.get_setup()

    html = render_to_string('billing/pdf_template.html', {
        'snapshot': snapshot,
        'items': items,
        'subscriber': snapshot.subscriber,
        'isp_name': setup.isp_name or 'ISP Manager',
        'isp_phone': setup.isp_phone,
        'isp_email': setup.isp_email,
    }, request=request)

    try:
        from io import BytesIO
        from xhtml2pdf import pisa
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(html.encode('utf-8'), dest=pdf_buffer, encoding='utf-8')
        if pisa_status.err:
            raise Exception(f"PDF generation failed: {pisa_status.err}")
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        fname = f"billing-{snapshot.snapshot_number}.pdf"
        cd = 'inline' if disposition == 'inline' else f'attachment; filename="{fname}"'
        response['Content-Disposition'] = cd
        return response
    except Exception as e:
        # PDF lib not available - serve as styled HTML
        response = HttpResponse(html, content_type='text/html')
        if disposition == 'attachment':
            response['Content-Disposition'] = f'attachment; filename="billing-{snapshot.snapshot_number}.html"'
        return response


def snapshot_pdf_inline(request, pk):
    return snapshot_pdf(request, pk, disposition='inline')


def snapshot_pdf_download(request, pk):
    return snapshot_pdf(request, pk, disposition='attachment')
