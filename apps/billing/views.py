from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import OperationalError
from apps.billing.models import Invoice, Payment, BillingSnapshot, BillingSnapshotItem
from apps.billing.forms import PaymentForm, RateChangeForm
from apps.billing.services import (
    generate_invoices_for_all, generate_invoice_for_subscriber,
    record_payment_with_allocation, generate_snapshot_for_subscriber,
    mark_overdue_invoices,
)
from apps.subscribers.models import Subscriber
from apps.settings_app.models import BillingSettings
from apps.core.models import AuditLog


@login_required
def invoice_list(request):
    mark_overdue_invoices()
    qs = Invoice.objects.select_related('subscriber', 'subscriber__plan').all()
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        from django.db.models import Q
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
            return redirect('subscriber-detail', pk=subscriber_pk)
    else:
        form = PaymentForm(initial={'amount': open_balance})

    return render(request, 'billing/record_payment.html', {
        'subscriber': subscriber,
        'form': form,
        'open_invoices': open_invoices,
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
    snapshot = get_object_or_404(BillingSnapshot, pk=pk)
    if request.method == 'POST':
        snapshot.freeze(frozen_by=request.user.username)
        AuditLog.log('update', 'billing', f"Snapshot {snapshot.snapshot_number} frozen", user=request.user)
        messages.success(request, f"Snapshot {snapshot.snapshot_number} frozen and issued to client.")
        return redirect('snapshot-detail', pk=pk)
    return render(request, 'billing/confirm_freeze.html', {'snapshot': snapshot})


@login_required
def generate_snapshot(request, subscriber_pk):
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
