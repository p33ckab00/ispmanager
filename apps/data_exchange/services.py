import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from apps.accounting.models import ExpenseRecord
from apps.billing.models import Invoice, Payment
from apps.billing.services import record_payment_with_allocation
from apps.subscribers.models import Plan, Subscriber


SUBSCRIBER_IMPORT_HEADERS = [
    'username', 'full_name', 'phone', 'address', 'email',
    'service_type', 'mt_password', 'mt_profile',
    'plan_name', 'monthly_rate', 'cutoff_day',
    'billing_type', 'billing_effective_from', 'billing_due_days',
    'is_billable', 'start_date', 'status', 'notes', 'sms_opt_out',
]

PAYMENT_IMPORT_HEADERS = [
    'subscriber_username', 'amount', 'method', 'reference', 'notes', 'paid_at',
]


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def parse_csv_text(upload):
    content = upload.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    return content, list(reader)


def parse_bool(value, field_name):
    normalized = (value or '').strip().lower()
    if normalized == '':
        return None, None
    if normalized in {'1', 'true', 'yes', 'y', 'on'}:
        return True, None
    if normalized in {'0', 'false', 'no', 'n', 'off'}:
        return False, None
    return None, f"{field_name} must be yes/no, true/false, or 1/0."


def parse_int(value, field_name):
    raw = (value or '').strip()
    if raw == '':
        return None, None
    try:
        return int(raw), None
    except ValueError:
        return None, f"{field_name} must be a whole number."


def parse_decimal(value, field_name):
    raw = (value or '').strip()
    if raw == '':
        return None, None
    try:
        return Decimal(raw), None
    except InvalidOperation:
        return None, f"{field_name} must be a valid decimal number."


def parse_date(value, field_name):
    raw = (value or '').strip()
    if raw == '':
        return None, None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date(), None
    except ValueError:
        return None, f"{field_name} must use YYYY-MM-DD."


def parse_datetime(value, field_name):
    raw = (value or '').strip()
    if raw == '':
        return None, None

    formats = [
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%dT%H:%M:%S',
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone()), None
        except ValueError:
            continue
    return None, f"{field_name} must use YYYY-MM-DD HH:MM or YYYY-MM-DDTHH:MM."


def subscriber_export_rows(queryset):
    rows = []
    for subscriber in queryset:
        rows.append([
            subscriber.username,
            subscriber.full_name,
            subscriber.phone,
            subscriber.address,
            subscriber.email,
            subscriber.service_type,
            subscriber.mt_profile,
            subscriber.plan.name if subscriber.plan else '',
            subscriber.monthly_rate or '',
            subscriber.cutoff_day if subscriber.cutoff_day is not None else '',
            subscriber.billing_type,
            subscriber.billing_effective_from or '',
            subscriber.billing_due_days if subscriber.billing_due_days is not None else '',
            'yes' if subscriber.is_billable else 'no',
            subscriber.start_date or '',
            subscriber.status,
            subscriber.sms_opt_out,
            subscriber.updated_at.isoformat(),
        ])
    return rows


def invoice_export_rows(queryset):
    rows = []
    for invoice in queryset:
        rows.append([
            invoice.invoice_number,
            invoice.subscriber.username,
            invoice.subscriber.display_name,
            invoice.period_start,
            invoice.period_end,
            invoice.due_date,
            invoice.amount,
            invoice.amount_paid,
            invoice.remaining_balance,
            invoice.status,
            invoice.plan_snapshot,
            invoice.rate_snapshot or '',
            invoice.short_code,
            invoice.created_at.isoformat(),
        ])
    return rows


def payment_export_rows(queryset):
    rows = []
    for payment in queryset:
        rows.append([
            payment.subscriber.username,
            payment.subscriber.display_name,
            payment.amount,
            payment.method,
            payment.get_method_display(),
            payment.reference,
            payment.notes,
            payment.paid_at.isoformat(),
            payment.unallocated_amount,
            payment.created_at.isoformat(),
        ])
    return rows


def expense_export_rows(queryset):
    rows = []
    for expense in queryset:
        rows.append([
            expense.date,
            expense.category,
            expense.get_category_display(),
            expense.description,
            expense.vendor,
            expense.reference,
            expense.amount,
            expense.recorded_by,
            expense.created_at.isoformat(),
        ])
    return rows


def subscriber_export_headers():
    return [
        'username', 'full_name', 'phone', 'address', 'email',
        'service_type', 'mt_profile', 'plan_name', 'monthly_rate',
        'cutoff_day', 'billing_type', 'billing_effective_from', 'billing_due_days',
        'is_billable', 'start_date', 'status', 'sms_opt_out', 'updated_at',
    ]


def invoice_export_headers():
    return [
        'invoice_number', 'subscriber_username', 'subscriber_name',
        'period_start', 'period_end', 'due_date',
        'amount', 'amount_paid', 'remaining_balance', 'status',
        'plan_snapshot', 'rate_snapshot', 'short_code', 'created_at',
    ]


def payment_export_headers():
    return [
        'subscriber_username', 'subscriber_name', 'amount', 'method',
        'method_label', 'reference', 'notes', 'paid_at', 'unallocated_amount', 'created_at',
    ]


def expense_export_headers():
    return [
        'date', 'category', 'category_label', 'description',
        'vendor', 'reference', 'amount', 'recorded_by', 'created_at',
    ]


def subscriber_template_response():
    sample_row = [
        'juan.pppoe', 'Juan Dela Cruz', '09171234567', 'Purok 1, Barangay Sample',
        'juan@example.com', 'pppoe', 'samplepass', 'basic-pppoe',
        'Starter Plan', '999.00', '5', 'postpaid', '2026-04-01', '5',
        'yes', '2026-04-01', 'active', 'Imported from legacy list', 'no',
    ]
    return csv_response('subscriber-import-template.csv', SUBSCRIBER_IMPORT_HEADERS, [sample_row])


def payment_template_response():
    sample_row = [
        'juan.pppoe', '999.00', 'gcash', 'GCASH-20260422-001',
        'Paid at office counter', '2026-04-22 09:30',
    ]
    return csv_response('payment-import-template.csv', PAYMENT_IMPORT_HEADERS, [sample_row])


def preview_subscriber_import(rows, update_existing=True):
    report = {
        'total_rows': len(rows),
        'created_count': 0,
        'updated_count': 0,
        'skipped_count': 0,
        'error_count': 0,
        'preview_rows': [],
        'errors': [],
    }
    operations = []

    usernames = [((row.get('username') or '').strip()) for row in rows if (row.get('username') or '').strip()]
    existing_map = Subscriber.objects.in_bulk(usernames, field_name='username')
    plan_map = {plan.name.lower(): plan for plan in Plan.objects.all()}

    service_choices = {choice[0] for choice in Subscriber.SERVICE_CHOICES}
    status_choices = {choice[0] for choice in Subscriber.STATUS_CHOICES}
    billing_type_choices = {choice[0] for choice in Subscriber.BILLING_TYPE_CHOICES}
    seen_usernames = set()

    for line_number, row in enumerate(rows, start=2):
        username = (row.get('username') or '').strip()
        if not username:
            report['errors'].append(f"Line {line_number}: username is required.")
            continue
        if username in seen_usernames:
            report['errors'].append(f"Line {line_number}: username '{username}' appears more than once in this file.")
            continue
        seen_usernames.add(username)

        existing = existing_map.get(username)
        action = 'update' if existing else 'create'
        if existing and not update_existing:
            report['skipped_count'] += 1
            report['preview_rows'].append({'line': line_number, 'key': username, 'action': 'skip'})
            continue

        attrs = {}
        line_errors = []

        for key in ['full_name', 'phone', 'address', 'email', 'mt_password', 'mt_profile', 'notes']:
            value = (row.get(key) or '').strip()
            if value:
                attrs[key] = value

        email = attrs.get('email')
        if email:
            try:
                validate_email(email)
            except Exception:
                line_errors.append(f"Line {line_number}: email is invalid.")

        service_type = (row.get('service_type') or '').strip()
        if service_type:
            if service_type not in service_choices:
                line_errors.append(f"Line {line_number}: service_type must be one of {', '.join(sorted(service_choices))}.")
            else:
                attrs['service_type'] = service_type

        status = (row.get('status') or '').strip()
        if status:
            if status not in status_choices:
                line_errors.append(f"Line {line_number}: status must be one of {', '.join(sorted(status_choices))}.")
            else:
                attrs['status'] = status

        billing_type = (row.get('billing_type') or '').strip()
        if billing_type:
            if billing_type not in billing_type_choices:
                line_errors.append(f"Line {line_number}: billing_type must be one of {', '.join(sorted(billing_type_choices))}.")
            else:
                attrs['billing_type'] = billing_type

        plan_name = (row.get('plan_name') or '').strip()
        if plan_name:
            plan = plan_map.get(plan_name.lower())
            if not plan:
                line_errors.append(f"Line {line_number}: plan '{plan_name}' was not found.")
            else:
                attrs['plan'] = plan

        monthly_rate, error = parse_decimal(row.get('monthly_rate'), 'monthly_rate')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif monthly_rate is not None:
            attrs['monthly_rate'] = monthly_rate

        cutoff_day, error = parse_int(row.get('cutoff_day'), 'cutoff_day')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif cutoff_day is not None:
            if not 1 <= cutoff_day <= 31:
                line_errors.append(f"Line {line_number}: cutoff_day must be between 1 and 31.")
            else:
                attrs['cutoff_day'] = cutoff_day

        due_days, error = parse_int(row.get('billing_due_days'), 'billing_due_days')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif due_days is not None:
            if due_days < 0:
                line_errors.append(f"Line {line_number}: billing_due_days must be 0 or higher.")
            else:
                attrs['billing_due_days'] = due_days

        billing_effective_from, error = parse_date(row.get('billing_effective_from'), 'billing_effective_from')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif billing_effective_from is not None:
            attrs['billing_effective_from'] = billing_effective_from

        start_date, error = parse_date(row.get('start_date'), 'start_date')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif start_date is not None:
            attrs['start_date'] = start_date

        is_billable, error = parse_bool(row.get('is_billable'), 'is_billable')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif is_billable is not None:
            attrs['is_billable'] = is_billable

        sms_opt_out, error = parse_bool(row.get('sms_opt_out'), 'sms_opt_out')
        if error:
            line_errors.append(f"Line {line_number}: {error}")
        elif sms_opt_out is not None:
            attrs['sms_opt_out'] = sms_opt_out

        if line_errors:
            report['errors'].extend(line_errors)
            continue

        if action == 'create':
            report['created_count'] += 1
        else:
            report['updated_count'] += 1

        report['preview_rows'].append({'line': line_number, 'key': username, 'action': action})
        operations.append({
            'line': line_number,
            'username': username,
            'existing': existing,
            'attrs': attrs,
        })

    report['error_count'] = len(report['errors'])
    report['preview_rows'] = report['preview_rows'][:25]
    report['errors'] = report['errors'][:50]
    return report, operations


def apply_subscriber_import(operations):
    with transaction.atomic():
        for operation in operations:
            subscriber = operation['existing']
            attrs = operation['attrs']
            if subscriber is None:
                subscriber = Subscriber(username=operation['username'])
            for key, value in attrs.items():
                setattr(subscriber, key, value)
            subscriber.save()


def preview_payment_import(rows):
    report = {
        'total_rows': len(rows),
        'created_count': 0,
        'updated_count': 0,
        'skipped_count': 0,
        'error_count': 0,
        'preview_rows': [],
        'errors': [],
    }
    operations = []

    usernames = sorted({
        (row.get('subscriber_username') or '').strip()
        for row in rows
        if (row.get('subscriber_username') or '').strip()
    })
    subscriber_map = Subscriber.objects.in_bulk(usernames, field_name='username')
    method_choices = {choice[0] for choice in Payment.METHOD_CHOICES}
    seen_rows = set()

    for line_number, row in enumerate(rows, start=2):
        username = (row.get('subscriber_username') or '').strip()
        if not username:
            report['errors'].append(f"Line {line_number}: subscriber_username is required.")
            continue

        subscriber = subscriber_map.get(username)
        if not subscriber:
            report['errors'].append(f"Line {line_number}: subscriber '{username}' was not found.")
            continue

        amount, error = parse_decimal(row.get('amount'), 'amount')
        if error:
            report['errors'].append(f"Line {line_number}: {error}")
            continue
        if amount is None or amount <= 0:
            report['errors'].append(f"Line {line_number}: amount must be greater than zero.")
            continue

        method = (row.get('method') or 'cash').strip().lower()
        if method not in method_choices:
            report['errors'].append(f"Line {line_number}: method must be one of {', '.join(sorted(method_choices))}.")
            continue

        paid_at, error = parse_datetime(row.get('paid_at'), 'paid_at')
        if error:
            report['errors'].append(f"Line {line_number}: {error}")
            continue
        if paid_at is None:
            paid_at = timezone.now()

        reference = (row.get('reference') or '').strip()
        notes = (row.get('notes') or '').strip()
        file_signature = (username, str(amount), method, reference, paid_at.isoformat())
        if file_signature in seen_rows:
            report['skipped_count'] += 1
            report['preview_rows'].append({'line': line_number, 'key': username, 'action': 'skip-duplicate-file'})
            continue
        seen_rows.add(file_signature)

        duplicate = Payment.objects.filter(
            subscriber=subscriber,
            amount=amount,
            method=method,
            reference=reference,
            paid_at=paid_at,
        ).exists()
        if duplicate:
            report['skipped_count'] += 1
            report['preview_rows'].append({'line': line_number, 'key': username, 'action': 'skip-duplicate'})
            continue

        report['created_count'] += 1
        report['preview_rows'].append({'line': line_number, 'key': username, 'action': 'create'})
        operations.append({
            'subscriber': subscriber,
            'amount': amount,
            'method': method,
            'reference': reference,
            'notes': notes,
            'paid_at': paid_at,
        })

    report['error_count'] = len(report['errors'])
    report['preview_rows'] = report['preview_rows'][:25]
    report['errors'] = report['errors'][:50]
    return report, operations


def apply_payment_import(operations, recorded_by):
    with transaction.atomic():
        for operation in operations:
            record_payment_with_allocation(
                subscriber=operation['subscriber'],
                amount=operation['amount'],
                method=operation['method'],
                reference=operation['reference'],
                notes=operation['notes'],
                paid_at=operation['paid_at'],
                recorded_by=recorded_by,
            )


def recent_preview(summary_json):
    return {
        'preview_rows': summary_json.get('preview_rows', []),
        'errors': summary_json.get('errors', []),
    }


def export_file_name(dataset):
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    return f'{dataset}-{stamp}.csv'


def expense_queryset():
    return ExpenseRecord.objects.all().order_by('-date', '-created_at')


def payment_queryset(q=''):
    queryset = Payment.objects.select_related('subscriber').all().order_by('-paid_at')
    q = (q or '').strip()
    if q:
        from django.db.models import Q
        queryset = queryset.filter(
            Q(subscriber__username__icontains=q) |
            Q(subscriber__full_name__icontains=q)
        )
    return queryset
