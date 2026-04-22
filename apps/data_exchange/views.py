from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.billing.models import Invoice
from apps.core.models import AuditLog
from apps.data_exchange.forms import PaymentImportForm, SubscriberImportForm
from apps.data_exchange.models import DataExchangeJob
from apps.data_exchange.services import (
    apply_payment_import,
    apply_subscriber_import,
    csv_response,
    expense_export_headers,
    expense_export_rows,
    expense_queryset,
    export_file_name,
    invoice_export_headers,
    invoice_export_rows,
    parse_csv_text,
    payment_export_headers,
    payment_export_rows,
    payment_queryset,
    payment_template_response,
    preview_payment_import,
    preview_subscriber_import,
    recent_preview,
    subscriber_export_headers,
    subscriber_export_rows,
    subscriber_template_response,
)
from apps.subscribers.models import Subscriber


def _create_job(request, **kwargs):
    return DataExchangeJob.objects.create(created_by=request.user, **kwargs)


@login_required
def dashboard(request):
    jobs = DataExchangeJob.objects.select_related('created_by').all()[:25]
    selected_job = None
    job_id = request.GET.get('job', '').strip()
    if job_id:
        selected_job = get_object_or_404(DataExchangeJob, pk=job_id)

    return render(request, 'data_exchange/dashboard.html', {
        'subscriber_form': SubscriberImportForm(),
        'payment_form': PaymentImportForm(),
        'jobs': jobs,
        'selected_job': selected_job,
        'selected_job_preview': recent_preview(selected_job.summary_json) if selected_job else None,
    })


def _handle_import(request, dataset, form_class, preview_fn, apply_fn, recorded_by=None):
    if request.method != 'POST':
        return redirect('data-exchange-dashboard')

    form = form_class(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('data-exchange-dashboard')

    upload = form.cleaned_data['file']
    _, rows = parse_csv_text(upload)
    report, operations = preview_fn(rows)
    run_mode = request.POST.get('run_mode', 'dry_run')
    is_dry_run = run_mode != 'apply'

    status = 'completed'
    error_report = '\n'.join(report['errors'])
    if not is_dry_run and report['errors']:
        status = 'failed'
    elif not is_dry_run:
        apply_fn(operations, recorded_by) if recorded_by else apply_fn(operations)

    job = _create_job(
        request,
        job_type='import',
        dataset=dataset,
        status=status,
        file_name=upload.name,
        is_dry_run=is_dry_run,
        total_rows=report['total_rows'],
        created_count=report['created_count'],
        updated_count=report['updated_count'],
        skipped_count=report['skipped_count'],
        error_count=report['error_count'],
        summary_json=report,
        error_report=error_report,
    )

    AuditLog.log(
        'system',
        'data_exchange',
        f"{'Dry run' if is_dry_run else 'Import'} {dataset}: rows={report['total_rows']} errors={report['error_count']}",
        user=request.user,
    )
    if status == 'failed':
        messages.error(request, f"{dataset.title()} import stopped because validation errors were found.")
    elif is_dry_run:
        messages.success(request, f"{dataset.title()} dry run complete. Review the preview before applying.")
    else:
        messages.success(request, f"{dataset.title()} import applied successfully.")
    return redirect(f"{reverse('data-exchange-dashboard')}?job={job.pk}")


@login_required
def import_subscribers(request):
    update_existing = request.POST.get('update_existing') == 'on'

    def preview(rows):
        return preview_subscriber_import(rows, update_existing=update_existing)

    return _handle_import(request, 'subscribers', SubscriberImportForm, preview, apply_subscriber_import)


@login_required
def import_payments(request):
    return _handle_import(
        request,
        'payments',
        PaymentImportForm,
        preview_payment_import,
        apply_payment_import,
        recorded_by=f"import:{request.user.username}",
    )


@login_required
def export_dataset(request, dataset):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    service = request.GET.get('service', '').strip()

    if dataset == 'subscribers':
        queryset = Subscriber.objects.select_related('router', 'plan').all()
        if q:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(username__icontains=q) |
                Q(full_name__icontains=q) |
                Q(phone__icontains=q) |
                Q(ip_address__icontains=q)
            )
        if status:
            queryset = queryset.filter(status=status)
        else:
            queryset = queryset.exclude(status__in=['archived'])
        if service:
            queryset = queryset.filter(service_type=service)
        headers = subscriber_export_headers()
        rows = subscriber_export_rows(queryset)
    elif dataset == 'invoices':
        queryset = Invoice.objects.select_related('subscriber').all()
        if q:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(subscriber__username__icontains=q) |
                Q(subscriber__full_name__icontains=q)
            )
        if status:
            queryset = queryset.filter(status=status)
        headers = invoice_export_headers()
        rows = invoice_export_rows(queryset)
    elif dataset == 'payments':
        queryset = payment_queryset(q=q)
        headers = payment_export_headers()
        rows = payment_export_rows(queryset)
    elif dataset == 'expenses':
        queryset = expense_queryset()
        headers = expense_export_headers()
        rows = expense_export_rows(queryset)
    else:
        raise Http404

    filename = export_file_name(dataset)
    _create_job(
        request,
        job_type='export',
        dataset=dataset,
        status='completed',
        file_name=filename,
        total_rows=len(rows),
        summary_json={'filters': {'q': q, 'status': status, 'service': service}},
    )
    AuditLog.log(
        'system',
        'data_exchange',
        f"Export {dataset}: rows={len(rows)}",
        user=request.user,
    )
    return csv_response(filename, headers, rows)


@login_required
def download_template(request, dataset):
    if dataset == 'subscribers':
        return subscriber_template_response()
    if dataset == 'payments':
        return payment_template_response()
    raise Http404
