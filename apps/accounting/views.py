from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.urls import reverse
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode

from apps.accounting.models import (
    AccountingEntity,
    AccountingPeriod,
    AccountingReportArchive,
    AccountingReportPreset,
    AccountingSettings,
    AccountingSourcePosting,
    AlphanumericTaxCode,
    APVendor,
    APVendorBill,
    APVendorBillAttachment,
    APVendorPayment,
    ChartOfAccount,
    CutoverBalanceSchedule,
    CutoverPlan,
    CutoverReconciliationSnapshot,
    CustomerWithholdingTaxClaim,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    OpeningBalanceImport,
    WithholdingTaxClass,
)
from apps.accounting.forms import (
    AccountingReportPresetForm,
    AccountingSetupForm,
    APVendorBillAttachmentForm,
    APVendorBillForm,
    APVendorBillVoidForm,
    APVendorForm,
    APVendorPaymentForm,
    APVendorPaymentSettlementForm,
    APVendorPaymentVoidForm,
    CutoverBalanceScheduleForm,
    CutoverBalanceScheduleLineForm,
    CutoverPlanForm,
    ExpenseForm,
    IncomeForm,
    JournalEntryHeaderForm,
    OpeningBalanceImportForm,
    OpeningBalanceLineForm,
    WithholdingTaxClassForm,
)
from apps.accounting.report_exports import report_export_response
from apps.accounting.services import (
    build_cutover_readiness,
    build_cutover_balance_schedule_reconciliation,
    build_cutover_balance_schedule_summary,
    approve_cutover_plan,
    build_ap_aging_report,
    build_ar_aging_report,
    build_balance_sheet_report,
    build_cash_flow_report,
    build_changes_in_equity_report,
    build_period_close_preview,
    build_period_reopen_preview,
    create_accounting_foundation,
    close_accounting_period,
    create_ap_vendor_bill_draft,
    create_ap_vendor_bill_attachment,
    create_ap_vendor_bill_void_draft,
    clear_ap_vendor_payment_settlement,
    create_ap_vendor_payment_draft,
    create_ap_vendor_payment_void_draft,
    create_cutover_balance_schedule,
    create_cutover_plan,
    build_general_ledger_report,
    build_income_statement_report,
    build_tax_ledger_report,
    build_trial_balance_report,
    create_manual_journal_entry,
    create_opening_balance_journal,
    generate_cutover_reconciliation_snapshot,
    get_active_cutover_plan,
    refresh_cutover_balance_schedule,
    get_latest_cutover_reconciliation_snapshot,
    mark_accounting_live,
    mark_cutover_ready,
    match_ap_vendor_payment_settlement,
    post_journal_entry,
    refresh_opening_balance_totals,
    refresh_ap_vendor_bill_status,
    refresh_ap_vendor_payment_status,
    reopen_accounting_period,
    retry_source_posting,
    sync_payments_to_income,
    get_monthly_summary,
    get_totals,
    validate_cutover_balance_schedule,
    validate_opening_balance_import,
)
from apps.core.models import AuditLog


def _active_entity():
    return AccountingEntity.objects.filter(is_active=True).first()


def _entity_settings(entity):
    if not entity:
        return None
    try:
        return entity.settings
    except AccountingSettings.DoesNotExist:
        return None


def _accounting_context():
    entity = _active_entity()
    settings_obj = _entity_settings(entity)
    today = date.today()
    open_period = None
    if entity:
        open_period = AccountingPeriod.objects.filter(
            entity=entity,
            start_date__lte=today,
            end_date__gte=today,
        ).first()
    return {
        'accounting_entity': entity,
        'accounting_settings': settings_obj,
        'account_count': ChartOfAccount.objects.filter(entity=entity).count() if entity else 0,
        'period_count': AccountingPeriod.objects.filter(entity=entity).count() if entity else 0,
        'draft_journal_count': JournalEntry.objects.filter(entity=entity, status='draft').count() if entity else 0,
        'source_draft_count': AccountingSourcePosting.objects.filter(entity=entity, status='draft').count() if entity else 0,
        'source_blocked_count': AccountingSourcePosting.objects.filter(Q(entity=entity) | Q(entity__isnull=True), status='blocked').count() if entity else 0,
        'ap_vendor_bill_count': APVendorBill.objects.filter(entity=entity).exclude(status='voided').count() if entity else 0,
        'withholding_class_count': WithholdingTaxClass.objects.filter(entity=entity, is_active=True).count() if entity else 0,
        'withholding_pending_count': CustomerWithholdingTaxClaim.objects.filter(
            Q(entity=entity) | Q(entity__isnull=True),
            status__in=['customer_claimed', 'pending_2307'],
        ).count() if entity else 0,
        'active_cutover_plan': get_active_cutover_plan(entity) if entity else None,
        'open_period': open_period,
    }


def _require_accounting_perm(request, permission, redirect_to='accounting-dashboard'):
    if request.user.has_perm(permission):
        return True
    messages.error(request, 'You do not have permission to perform that accounting action.')
    return redirect(redirect_to)


def _require_entity(request):
    entity = _active_entity()
    if entity:
        return entity
    messages.info(request, 'Set up Accounting v2 before opening this workspace.')
    return redirect('accounting-setup')


def _money(value):
    if value in (None, ''):
        return Decimal('0.00')
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ValidationError('Line amounts must be valid numbers.')


def _parse_report_date(value, fallback=None):
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _cutover_is_locked(plan):
    return bool(plan and plan.status in ('approved', 'live'))


RANGE_PRESET_CHOICES = [
    ('', 'Manual dates'),
    ('current_month', 'Current month'),
    ('previous_month', 'Previous month'),
    ('year_to_date', 'Year to date'),
    ('current_year', 'Current year'),
    ('previous_year', 'Previous year'),
]

AS_OF_PRESET_CHOICES = [
    ('', 'Manual date'),
    ('today', 'Today'),
    ('current_month_end', 'Current month end'),
    ('previous_month_end', 'Previous month end'),
    ('current_year_end', 'Current year end'),
    ('previous_year_end', 'Previous year end'),
]

REPORT_PRESET_ROUTES = {
    'trial_balance': 'accounting-trial-balance',
    'general_ledger': 'accounting-general-ledger',
    'income_statement': 'accounting-income-statement',
    'balance_sheet': 'accounting-balance-sheet',
    'cash_flow': 'accounting-cash-flow',
    'changes_in_equity': 'accounting-changes-in-equity',
    'ar_aging': 'accounting-ar-aging',
    'ap_aging': 'accounting-ap-aging',
    'tax_ledger': 'accounting-tax-ledger',
}

REPORT_PRESET_ALLOWED_PARAMS = {
    'trial_balance': {'period', 'include_zero'},
    'general_ledger': {'preset', 'start', 'end', 'account', 'include_zero'},
    'income_statement': {'preset', 'start', 'end'},
    'balance_sheet': {'as_of_preset', 'as_of'},
    'cash_flow': {'preset', 'start', 'end'},
    'changes_in_equity': {'preset', 'start', 'end'},
    'ar_aging': {'as_of_preset', 'as_of'},
    'ap_aging': {'as_of_preset', 'as_of'},
    'tax_ledger': {'preset', 'start', 'end'},
}


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _month_start(value):
    return value.replace(day=1)


def _month_end(value):
    return _add_months(_month_start(value), 1) - timedelta(days=1)


def _report_date_range(request, default_start, default_end):
    today = date.today()
    preset = request.GET.get('preset', '')
    if preset == 'current_month':
        return _month_start(today), _month_end(today), preset
    if preset == 'previous_month':
        previous_month = _add_months(_month_start(today), -1)
        return previous_month, _month_end(previous_month), preset
    if preset == 'year_to_date':
        return today.replace(month=1, day=1), today, preset
    if preset == 'current_year':
        return today.replace(month=1, day=1), today.replace(month=12, day=31), preset
    if preset == 'previous_year':
        previous_year = today.year - 1
        return date(previous_year, 1, 1), date(previous_year, 12, 31), preset
    return (
        _parse_report_date(request.GET.get('start'), default_start),
        _parse_report_date(request.GET.get('end'), default_end),
        '',
    )


def _report_as_of_date(request, fallback):
    today = date.today()
    preset = request.GET.get('as_of_preset', '')
    if preset == 'today':
        return today, preset
    if preset == 'current_month_end':
        return _month_end(today), preset
    if preset == 'previous_month_end':
        previous_month = _add_months(_month_start(today), -1)
        return _month_end(previous_month), preset
    if preset == 'current_year_end':
        return date(today.year, 12, 31), preset
    if preset == 'previous_year_end':
        return date(today.year - 1, 12, 31), preset
    return _parse_report_date(request.GET.get('as_of'), fallback), ''


def _include_zero(request):
    return request.GET.get('include_zero') in ('1', 'true', 'yes', 'on')


def _report_query(request, **updates):
    query = request.GET.copy()
    for key, value in updates.items():
        if value in (None, ''):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


def _report_export_queries(request):
    return {
        'export_query': _report_query(request, format='csv'),
        'xlsx_query': _report_query(request, format='xlsx'),
        'pdf_query': _report_query(request, format='pdf'),
        'manifest_query': _report_query(request, format='manifest'),
    }


def _saved_report_preset_parameters(report_key, raw_parameters):
    allowed = REPORT_PRESET_ALLOWED_PARAMS.get(report_key, set())
    parameters = {}
    for key, value in raw_parameters.items():
        if key not in allowed or value in (None, ''):
            continue
        if key == 'include_zero':
            if value in ('1', 'true', 'yes', 'on'):
                parameters[key] = '1'
            continue
        parameters[key] = str(value)
    return parameters


def _saved_report_preset_context(request, entity, report_key):
    current_parameters = _saved_report_preset_parameters(report_key, request.GET)
    return {
        'saved_report_presets': AccountingReportPreset.objects.filter(
            entity=entity,
            user=request.user,
            report_key=report_key,
        ),
        'saved_report_preset_report_key': report_key,
        'saved_report_preset_query_string': urlencode(current_parameters),
    }


def _trial_balance_csv_rows(report):
    return [
        [
            row['account'].code,
            row['account'].name,
            row['account'].get_account_type_display(),
            row['debit'],
            row['credit'],
            row['balance'],
        ]
        for row in report['rows']
    ] + [[
        '',
        'Total',
        '',
        report['total_debit'],
        report['total_credit'],
        'Balanced' if report['is_balanced'] else 'Out of balance',
    ]]


def _general_ledger_csv_rows(report):
    rows = []
    for section in report['sections']:
        account = section['account']
        rows.append([
            account.code,
            account.name,
            '',
            'Opening Balance',
            '',
            '',
            '',
            section['opening_balance'],
        ])
        for item in section['lines']:
            journal_entry = item['journal_entry']
            rows.append([
                account.code,
                account.name,
                journal_entry.entry_date,
                journal_entry.entry_number,
                item['line'].description or journal_entry.description,
                item['debit'],
                item['credit'],
                item['running_balance'],
            ])
        rows.append([
            account.code,
            account.name,
            '',
            'Closing Balance',
            '',
            '',
            '',
            section['closing_balance'],
        ])
    return rows


def _income_statement_csv_rows(report):
    labels = {
        'revenue': 'Revenue',
        'direct_cost': 'Direct Costs',
        'expense': 'Operating Expenses',
        'other_income': 'Other Income',
        'other_expense': 'Other Expenses',
    }
    rows = []
    for key in ('revenue', 'direct_cost', 'expense', 'other_income', 'other_expense'):
        for row in report['sections'][key]:
            rows.append([
                labels[key],
                row['account'].code,
                row['account'].name,
                row['balance'],
            ])
        rows.append([labels[key], '', 'Total', report['totals'][key]])
    rows.extend([
        ['Summary', '', 'Gross Profit', report['gross_profit']],
        ['Summary', '', 'Operating Income', report['operating_income']],
        ['Summary', '', 'Net Income', report['net_income']],
    ])
    return rows


def _balance_sheet_csv_rows(report):
    labels = {
        'asset': 'Assets',
        'liability': 'Liabilities',
        'equity': 'Equity',
    }
    rows = []
    for key in ('asset', 'liability', 'equity'):
        for row in report['sections'][key]:
            account = row.get('account')
            rows.append([
                labels[key],
                account.code if account else '',
                account.name if account else row.get('label', ''),
                row['balance'],
            ])
        rows.append([labels[key], '', 'Total', report['totals'][key]])
    rows.extend([
        ['Summary', '', 'Total Liabilities And Equity', report['total_liabilities_equity']],
        ['Summary', '', 'Difference', report['difference']],
        ['Summary', '', 'Balanced', 'yes' if report['is_balanced'] else 'no'],
    ])
    return rows


def _cash_flow_csv_rows(report):
    labels = {
        'operating': 'Operating Activities',
        'investing': 'Investing Activities',
        'financing': 'Financing Activities',
    }
    rows = []
    for key in ('operating', 'investing', 'financing'):
        for row in report['sections'][key]:
            rows.append([
                labels[key],
                row['entry_date'],
                row['entry_number'],
                row['description'],
                row['counterparty'],
                row['amount'],
            ])
        rows.append([labels[key], '', '', 'Total', '', report['totals'][key]])
    rows.extend([
        ['Summary', '', '', 'Opening Cash And Cash Equivalents', '', report['opening_cash']],
        ['Summary', '', '', 'Net Cash Change', '', report['net_cash_change']],
        ['Summary', '', '', 'Closing Cash And Cash Equivalents', '', report['closing_cash']],
        ['Summary', '', '', 'Difference', '', report['difference']],
    ])
    return rows


def _changes_in_equity_csv_rows(report):
    rows = [
        [
            'Equity Account',
            row['account'].code,
            row['account'].name,
            row['opening_balance'],
            row['movement'],
            row['ending_balance'],
        ]
        for row in report['rows']
    ]
    rows.extend([
        ['Summary', '', 'Prior Unclosed Earnings', report['prior_unclosed_earnings'], '', ''],
        ['Summary', '', 'Period Net Income', '', report['period_net_income'], ''],
        ['Summary', '', 'Closing Entry Transfer', '', report['closing_entry_adjustment'], ''],
        ['Summary', '', 'Opening Equity', report['opening_equity'], '', ''],
        ['Summary', '', 'Ending Equity', '', '', report['ending_equity']],
        ['Summary', '', 'Balance Sheet Equity', '', '', report['balance_sheet_equity']],
        ['Summary', '', 'Difference', '', '', report['difference']],
    ])
    return rows


def _ar_aging_csv_rows(report):
    rows = []
    for row in report['rows']:
        rows.append([
            row['subscriber'].username,
            row['subscriber'].display_name,
            row['invoice_number'],
            row['due_date'],
            row['status'],
            row['days_overdue'],
            row['bucket_label'],
            row['balance'],
        ])
    rows.extend([
        ['Summary', '', 'Current', '', '', '', '', report['totals']['current']],
        ['Summary', '', '1-30 Days', '', '', '', '', report['totals']['1_30']],
        ['Summary', '', '31-60 Days', '', '', '', '', report['totals']['31_60']],
        ['Summary', '', '61-90 Days', '', '', '', '', report['totals']['61_90']],
        ['Summary', '', 'Over 90 Days', '', '', '', '', report['totals']['over_90']],
        ['Summary', '', 'Total', '', '', '', '', report['total']],
        ['Summary', '', 'GL AR Control', '', '', '', '', report['control_balance']],
        ['Summary', '', 'Difference', '', '', '', '', report['control_difference']],
    ])
    return rows


def _ap_aging_csv_rows(report):
    rows = []
    for row in report['rows']:
        rows.append([
            row['vendor_name'],
            row['reference'],
            row['document_date'] or '',
            row['due_date'],
            row['account'].code,
            row['account'].name,
            row['days_overdue'],
            row['bucket_label'],
            row['amount'],
            row['source'],
        ])
    rows.extend([
        ['Summary', 'Current', '', '', '', '', '', '', report['totals']['current'], ''],
        ['Summary', '1-30 Days', '', '', '', '', '', '', report['totals']['1_30'], ''],
        ['Summary', '31-60 Days', '', '', '', '', '', '', report['totals']['31_60'], ''],
        ['Summary', '61-90 Days', '', '', '', '', '', '', report['totals']['61_90'], ''],
        ['Summary', 'Over 90 Days', '', '', '', '', '', '', report['totals']['over_90'], ''],
        ['Summary', 'Total', '', '', '', '', '', '', report['total'], ''],
        ['Summary', 'GL AP Control', '', '', '', '', '', '', report['control_balance'], ''],
        ['Summary', 'Difference', '', '', '', '', '', '', report['control_difference'], ''],
    ])
    return rows


def _tax_ledger_csv_rows(report):
    rows = []
    for row in report['rows']:
        rows.append([
            'Tax Account',
            row['account'].code,
            row['account'].name,
            row['opening_balance'],
            row['debit'],
            row['credit'],
            row['movement'],
            row['ending_balance'],
        ])
    rows.extend([
        ['Summary', '', 'Input VAT', '', '', '', '', report['input_vat']],
        ['Summary', '', 'Output VAT', '', '', '', '', report['output_vat']],
        ['Summary', '', 'VAT Due Estimate', '', '', '', '', report['vat_due_estimate']],
        ['Summary', '', 'VAT Payable', '', '', '', '', report['vat_payable']],
        ['Summary', '', 'VAT Difference', '', '', '', '', report['vat_difference']],
        ['Summary', '', 'Creditable Withholding Tax Receivable', '', '', '', '', report['cwt_receivable']],
        ['Summary', '', 'Percentage Tax Payable', '', '', '', '', report['percentage_tax_payable']],
    ])
    for claim in report['claim_rows']:
        rows.append([
            '2307 Claim',
            claim['atc'],
            claim['payor_name'] or claim['subscriber'].display_name,
            claim['claim_date'],
            claim['gross_amount'],
            claim['tax_withheld'],
            claim['status'],
            '',
        ])
    return rows


@login_required
def accounting_dashboard(request):
    year = int(request.GET.get('year', date.today().year))
    months = get_monthly_summary(year)
    totals = get_totals(year)
    ctx = {
        'months': months,
        'totals': totals,
        'year': year,
    }
    ctx.update(_accounting_context())
    return render(request, 'accounting/dashboard.html', ctx)


@login_required
def accounting_setup(request):
    permission_check = _require_accounting_perm(request, 'accounting.manage_accounting_setup')
    if permission_check is not True:
        return permission_check

    current_year = date.today().year
    if request.method == 'POST':
        form = AccountingSetupForm(request.POST)
        if form.is_valid():
            result = create_accounting_foundation(
                entity_name=form.cleaned_data['name'],
                legal_name=form.cleaned_data['legal_name'],
                tin=form.cleaned_data['tin'],
                registered_address=form.cleaned_data['registered_address'],
                template_key=form.cleaned_data['template_key'],
                fiscal_year=form.cleaned_data['fiscal_year'],
            )
            AuditLog.log(
                'update',
                'accounting',
                f"Accounting v2 foundation seeded for {result['entity']}",
                user=request.user,
            )
            messages.success(request, 'Accounting v2 foundation is ready.')
            return redirect('accounting-dashboard')
    else:
        entity = _active_entity()
        initial = {'fiscal_year': current_year}
        if entity:
            settings_obj = _entity_settings(entity)
            initial.update({
                'name': entity.name,
                'legal_name': entity.legal_name,
                'tin': entity.tin,
                'registered_address': entity.registered_address,
                'template_key': getattr(settings_obj, 'current_template_key', '') or 'isp_non_vat_sole_prop',
            })
        form = AccountingSetupForm(initial=initial)

    return render(request, 'accounting/setup.html', {'form': form})


@login_required
def chart_list(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    qs = ChartOfAccount.objects.filter(entity=entity).order_by('code')
    return render(request, 'accounting/chart_list.html', {
        'entity': entity,
        'accounts': qs,
    })


@login_required
def period_list(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    return render(request, 'accounting/period_list.html', {
        'entity': entity,
        'periods': (
            AccountingPeriod.objects
            .filter(entity=entity)
            .select_related('closing_journal_entry', 'closed_by')
            .order_by('start_date')
        ),
    })


@login_required
def period_close(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_accounting_periods',
        'accounting-period-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    period = get_object_or_404(
        AccountingPeriod.objects.select_related('closing_journal_entry', 'closed_by'),
        entity=entity,
        pk=pk,
    )
    preview = build_period_close_preview(period)

    if request.method == 'POST':
        try:
            result = close_accounting_period(period, closed_by=request.user)
            closed_period = result['period']
            closing_journal = result['closing_journal']
            AuditLog.log('update', 'accounting', f"Period closed: {closed_period.name}", user=request.user)
            if closing_journal:
                messages.success(
                    request,
                    f"Period closed and closing journal {closing_journal.entry_number} posted.",
                )
                return redirect('accounting-journal-detail', pk=closing_journal.pk)
            messages.success(request, 'Period closed. No closing journal was needed because there was no temporary account activity.')
            return redirect('accounting-period-list')
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
            preview = build_period_close_preview(period)

    return render(request, 'accounting/period_close.html', {
        'entity': entity,
        'period': period,
        'preview': preview,
    })


@login_required
def period_reopen(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_accounting_periods',
        'accounting-period-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    period = get_object_or_404(
        AccountingPeriod.objects.select_related('closing_journal_entry', 'closed_by'),
        entity=entity,
        pk=pk,
    )
    preview = build_period_reopen_preview(period)

    if request.method == 'POST':
        try:
            result = reopen_accounting_period(period, reopened_by=request.user)
            reopened_period = result['period']
            reversal_journal = result['reversal_journal']
            AuditLog.log('update', 'accounting', f"Period reopened: {reopened_period.name}", user=request.user)
            if reversal_journal:
                messages.success(
                    request,
                    f"Period reopened and reversal journal {reversal_journal.entry_number} posted.",
                )
                return redirect('accounting-journal-detail', pk=reversal_journal.pk)
            messages.success(request, 'Period reopened.')
            return redirect('accounting-period-list')
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
            preview = build_period_reopen_preview(period)

    return render(request, 'accounting/period_reopen.html', {
        'entity': entity,
        'period': period,
        'preview': preview,
    })


@login_required
def report_archive_list(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    qs = (
        AccountingReportArchive.objects
        .filter(entity=entity)
        .select_related('generated_by')
        .order_by('-generated_at', '-created_at')
    )
    report_name = request.GET.get('report_name', '').strip()
    export_format = request.GET.get('format', '').strip()
    if report_name:
        qs = qs.filter(report_name=report_name)
    if export_format:
        qs = qs.filter(export_format=export_format)
    paginator = Paginator(qs, 30)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/report_archive_list.html', {
        'entity': entity,
        'page_obj': page,
        'selected_report_name': report_name,
        'selected_format': export_format,
        'report_names': (
            AccountingReportArchive.objects
            .filter(entity=entity)
            .order_by('report_name')
            .values_list('report_name', flat=True)
            .distinct()
        ),
        'format_choices': AccountingReportArchive.FORMAT_CHOICES,
    })


@login_required
def report_archive_download(request, pk):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    archive = get_object_or_404(AccountingReportArchive, entity=entity, pk=pk)
    if not archive.archive_file:
        messages.error(request, 'This archived export predates binary file storage.')
        return redirect('accounting-report-archive-list')
    return FileResponse(
        archive.archive_file.open('rb'),
        as_attachment=True,
        filename=archive.filename,
        content_type=archive.content_type,
    )


@login_required
def report_archive_package_download(request, pk):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    archive = get_object_or_404(AccountingReportArchive, entity=entity, pk=pk)
    if not archive.package_file:
        messages.error(request, 'This archived export predates package storage.')
        return redirect('accounting-report-archive-list')
    return FileResponse(
        archive.package_file.open('rb'),
        as_attachment=True,
        filename=f'{archive.filename}.zip',
        content_type='application/zip',
    )


@login_required
def report_preset_save(request, report_key):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    route_name = REPORT_PRESET_ROUTES.get(report_key)
    if not route_name:
        return redirect('accounting-dashboard')
    if request.method != 'POST':
        return redirect(route_name)
    form = AccountingReportPresetForm(request.POST)
    raw_parameters = dict(parse_qsl(request.POST.get('query_string', ''), keep_blank_values=True))
    parameters = _saved_report_preset_parameters(report_key, raw_parameters)
    if form.is_valid():
        preset, created = AccountingReportPreset.objects.update_or_create(
            entity=entity,
            user=request.user,
            report_key=report_key,
            name=form.cleaned_data['name'],
            defaults={'parameters': parameters},
        )
        AuditLog.log(
            'create' if created else 'update',
            'accounting',
            f"Report preset saved: {report_key} / {preset.name}",
            user=request.user,
        )
        messages.success(request, 'Report preset saved.')
    else:
        messages.error(request, form.errors.get('name', ['Preset name is required.'])[0])
    url = reverse(route_name)
    return redirect(f'{url}?{urlencode(parameters)}' if parameters else url)


@login_required
def report_preset_apply(request, pk):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    preset = get_object_or_404(
        AccountingReportPreset,
        entity=entity,
        user=request.user,
        pk=pk,
    )
    route_name = REPORT_PRESET_ROUTES.get(preset.report_key)
    if not route_name:
        return redirect('accounting-dashboard')
    parameters = _saved_report_preset_parameters(preset.report_key, preset.parameters)
    url = reverse(route_name)
    return redirect(f'{url}?{urlencode(parameters)}' if parameters else url)


@login_required
def report_preset_delete(request, pk):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    preset = get_object_or_404(
        AccountingReportPreset,
        entity=entity,
        user=request.user,
        pk=pk,
    )
    route_name = REPORT_PRESET_ROUTES.get(preset.report_key, 'accounting-dashboard')
    if request.method == 'POST':
        AuditLog.log('delete', 'accounting', f"Report preset deleted: {preset.report_key} / {preset.name}", user=request.user)
        preset.delete()
        messages.success(request, 'Report preset deleted.')
    return redirect(route_name)


@login_required
def journal_list(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    qs = JournalEntry.objects.filter(entity=entity).select_related('period').order_by('-entry_date', '-created_at')
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/journal_list.html', {
        'entity': entity,
        'page_obj': page,
    })


def _collect_journal_lines(request, entity):
    account_ids = request.POST.getlist('line_account')
    descriptions = request.POST.getlist('line_description')
    debits = request.POST.getlist('line_debit')
    credits = request.POST.getlist('line_credit')
    lines = []
    for index, account_id in enumerate(account_ids):
        debit = _money(debits[index] if index < len(debits) else '')
        credit = _money(credits[index] if index < len(credits) else '')
        description = descriptions[index] if index < len(descriptions) else ''
        if not account_id and debit == 0 and credit == 0 and not description:
            continue
        if not account_id:
            raise ValidationError('Each journal line with an amount needs an account.')
        account = ChartOfAccount.objects.get(entity=entity, pk=account_id)
        lines.append({
            'account': account,
            'description': description,
            'debit': debit,
            'credit': credit,
        })
    if len(lines) < 2:
        raise ValidationError('A manual journal needs at least two lines.')
    return lines


@login_required
def journal_add(request):
    permission_check = _require_accounting_perm(request, 'accounting.add_journalentry')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    accounts = ChartOfAccount.objects.filter(entity=entity, is_active=True).order_by('code')

    if request.method == 'POST':
        form = JournalEntryHeaderForm(request.POST)
        if form.is_valid():
            try:
                journal_entry = create_manual_journal_entry(
                    entity,
                    form.cleaned_data['entry_date'],
                    form.cleaned_data['description'],
                    _collect_journal_lines(request, entity),
                    reference=form.cleaned_data['reference'],
                    created_by=request.user,
                )
                AuditLog.log('create', 'accounting', f"Journal draft created: {journal_entry.entry_number}", user=request.user)
                messages.success(request, 'Draft journal entry created.')
                return redirect('accounting-journal-detail', pk=journal_entry.pk)
            except (ValidationError, ChartOfAccount.DoesNotExist) as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = JournalEntryHeaderForm(initial={'entry_date': date.today()})

    return render(request, 'accounting/journal_form.html', {
        'entity': entity,
        'form': form,
        'accounts': accounts,
        'line_range': range(6),
    })


@login_required
def journal_detail(request, pk):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    journal_entry = get_object_or_404(
        JournalEntry.objects.select_related('period', 'posted_by', 'created_by'),
        entity=entity,
        pk=pk,
    )
    return render(request, 'accounting/journal_detail.html', {
        'entity': entity,
        'journal_entry': journal_entry,
        'lines': journal_entry.lines.select_related('account'),
        'totals': journal_entry.totals(),
    })


@login_required
def journal_post(request, pk):
    permission_check = _require_accounting_perm(request, 'accounting.post_journalentry', 'accounting-journal-list')
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-journal-detail', pk=pk)
    journal_entry = get_object_or_404(JournalEntry, pk=pk)
    try:
        posted = post_journal_entry(journal_entry, posted_by=request.user)
        AuditLog.log('update', 'accounting', f"Journal posted: {posted.entry_number}", user=request.user)
        messages.success(request, 'Journal entry posted.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-journal-detail', pk=pk)


@login_required
def trial_balance(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    period_id = request.GET.get('period')
    include_zero = _include_zero(request)
    periods = AccountingPeriod.objects.filter(entity=entity).order_by('-start_date')
    period = periods.filter(pk=period_id).first() if period_id else periods.first()
    report = build_trial_balance_report(
        entity,
        start_date=period.start_date if period else None,
        end_date=period.end_date if period else None,
        include_zero=include_zero,
    )
    label = period.name.lower().replace(' ', '-') if period else 'all-periods'
    headers = ['account_code', 'account_name', 'account_type', 'debit', 'credit', 'balance']
    export_response = report_export_response(
        request,
        f'accounting-trial-balance-{label}',
        'Trial Balance',
        headers,
        _trial_balance_csv_rows(report),
        {
            'period': period.name if period else 'All periods',
            'start_date': period.start_date if period else None,
            'end_date': period.end_date if period else None,
            'include_zero': include_zero,
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response

    return render(request, 'accounting/trial_balance.html', {
        'entity': entity,
        'periods': periods,
        'period': period,
        'report': report,
        'rows': report['rows'],
        'total_debit': report['total_debit'],
        'total_credit': report['total_credit'],
        'is_balanced': report['is_balanced'],
        'include_zero': include_zero,
        **_saved_report_preset_context(request, entity, 'trial_balance'),
        **_report_export_queries(request),
    })


@login_required
def general_ledger(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    today = date.today()
    start_date, end_date, selected_preset = _report_date_range(
        request,
        today.replace(month=1, day=1),
        today,
    )
    account_id = request.GET.get('account')
    include_zero = _include_zero(request)
    accounts = ChartOfAccount.objects.filter(entity=entity, is_active=True).order_by('code')
    selected_account = accounts.filter(pk=account_id).first() if account_id else None
    report = build_general_ledger_report(
        entity,
        start_date=start_date,
        end_date=end_date,
        account=selected_account,
        include_zero=include_zero,
    )
    label = selected_account.code if selected_account else 'all-accounts'
    headers = ['account_code', 'account_name', 'date', 'entry_number', 'description', 'debit', 'credit', 'running_balance']
    export_response = report_export_response(
        request,
        f'accounting-general-ledger-{label}-{start_date}-{end_date}',
        'General Ledger',
        headers,
        _general_ledger_csv_rows(report),
        {
            'start_date': start_date,
            'end_date': end_date,
            'preset': selected_preset or 'manual',
            'account': str(selected_account) if selected_account else 'All accounts with activity',
            'include_zero': include_zero,
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/general_ledger.html', {
        'entity': entity,
        'accounts': accounts,
        'selected_account': selected_account,
        'start_date': start_date,
        'end_date': end_date,
        'report': report,
        'include_zero': include_zero,
        'preset_choices': RANGE_PRESET_CHOICES,
        'selected_preset': selected_preset,
        **_saved_report_preset_context(request, entity, 'general_ledger'),
        **_report_export_queries(request),
    })


@login_required
def income_statement(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    today = date.today()
    start_date, end_date, selected_preset = _report_date_range(
        request,
        today.replace(month=1, day=1),
        today,
    )
    report = build_income_statement_report(entity, start_date=start_date, end_date=end_date)
    headers = ['section', 'account_code', 'account_name', 'amount']
    export_response = report_export_response(
        request,
        f'accounting-income-statement-{start_date}-{end_date}',
        'Income Statement',
        headers,
        _income_statement_csv_rows(report),
        {
            'start_date': start_date,
            'end_date': end_date,
            'preset': selected_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/income_statement.html', {
        'entity': entity,
        'start_date': start_date,
        'end_date': end_date,
        'report': report,
        'preset_choices': RANGE_PRESET_CHOICES,
        'selected_preset': selected_preset,
        **_saved_report_preset_context(request, entity, 'income_statement'),
        **_report_export_queries(request),
    })


@login_required
def balance_sheet(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    as_of_date, selected_as_of_preset = _report_as_of_date(request, date.today())
    report = build_balance_sheet_report(entity, as_of_date=as_of_date)
    headers = ['section', 'account_code', 'account_name', 'balance']
    export_response = report_export_response(
        request,
        f'accounting-balance-sheet-{as_of_date}',
        'Balance Sheet',
        headers,
        _balance_sheet_csv_rows(report),
        {
            'as_of_date': as_of_date,
            'preset': selected_as_of_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/balance_sheet.html', {
        'entity': entity,
        'as_of_date': as_of_date,
        'report': report,
        'as_of_preset_choices': AS_OF_PRESET_CHOICES,
        'selected_as_of_preset': selected_as_of_preset,
        **_saved_report_preset_context(request, entity, 'balance_sheet'),
        **_report_export_queries(request),
    })


@login_required
def cash_flow(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    today = date.today()
    start_date, end_date, selected_preset = _report_date_range(
        request,
        today.replace(month=1, day=1),
        today,
    )
    report = build_cash_flow_report(entity, start_date=start_date, end_date=end_date)
    headers = ['section', 'date', 'entry_number', 'description', 'counterparty', 'amount']
    export_response = report_export_response(
        request,
        f'accounting-cash-flow-{start_date}-{end_date}',
        'Cash Flow',
        headers,
        _cash_flow_csv_rows(report),
        {
            'start_date': start_date,
            'end_date': end_date,
            'preset': selected_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/cash_flow.html', {
        'entity': entity,
        'start_date': start_date,
        'end_date': end_date,
        'report': report,
        'preset_choices': RANGE_PRESET_CHOICES,
        'selected_preset': selected_preset,
        'activity_sections': [
            {
                'key': 'operating',
                'label': 'Operating Activities',
                'rows': report['sections']['operating'],
                'total': report['totals']['operating'],
            },
            {
                'key': 'investing',
                'label': 'Investing Activities',
                'rows': report['sections']['investing'],
                'total': report['totals']['investing'],
            },
            {
                'key': 'financing',
                'label': 'Financing Activities',
                'rows': report['sections']['financing'],
                'total': report['totals']['financing'],
            },
        ],
        **_saved_report_preset_context(request, entity, 'cash_flow'),
        **_report_export_queries(request),
    })


@login_required
def changes_in_equity(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    today = date.today()
    start_date, end_date, selected_preset = _report_date_range(
        request,
        today.replace(month=1, day=1),
        today,
    )
    report = build_changes_in_equity_report(entity, start_date=start_date, end_date=end_date)
    headers = ['section', 'account_code', 'account_name', 'opening_balance', 'movement', 'ending_balance']
    export_response = report_export_response(
        request,
        f'accounting-changes-in-equity-{start_date}-{end_date}',
        'Changes in Equity',
        headers,
        _changes_in_equity_csv_rows(report),
        {
            'start_date': start_date,
            'end_date': end_date,
            'preset': selected_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/changes_in_equity.html', {
        'entity': entity,
        'start_date': start_date,
        'end_date': end_date,
        'report': report,
        'preset_choices': RANGE_PRESET_CHOICES,
        'selected_preset': selected_preset,
        **_saved_report_preset_context(request, entity, 'changes_in_equity'),
        **_report_export_queries(request),
    })


@login_required
def ar_aging(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    as_of_date, selected_as_of_preset = _report_as_of_date(request, date.today())
    report = build_ar_aging_report(entity, as_of_date=as_of_date)
    headers = ['subscriber_username', 'subscriber_name', 'invoice_number', 'due_date', 'status', 'days_overdue', 'bucket', 'balance']
    export_response = report_export_response(
        request,
        f'accounting-ar-aging-{as_of_date}',
        'AR Aging',
        headers,
        _ar_aging_csv_rows(report),
        {
            'as_of_date': as_of_date,
            'preset': selected_as_of_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/ar_aging.html', {
        'entity': entity,
        'as_of_date': as_of_date,
        'report': report,
        'as_of_preset_choices': AS_OF_PRESET_CHOICES,
        'selected_as_of_preset': selected_as_of_preset,
        **_saved_report_preset_context(request, entity, 'ar_aging'),
        **_report_export_queries(request),
    })


@login_required
def ap_vendor_bill_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_apvendorbill')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    bills = (
        APVendorBill.objects
        .filter(entity=entity)
        .select_related('expense_account', 'ap_account', 'journal_entry', 'void_journal_entry')
        .order_by('-document_date', '-created_at')
    )
    paginator = Paginator(bills, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    for bill in page.object_list:
        refresh_ap_vendor_bill_status(bill)
    return render(request, 'accounting/ap_vendor_bill_list.html', {
        'entity': entity,
        'page_obj': page,
    })


@login_required
def ap_vendor_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_apvendor')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    vendors = (
        APVendor.objects
        .filter(entity=entity)
        .select_related('default_expense_account', 'default_ap_account')
        .order_by('name', 'code')
    )
    paginator = Paginator(vendors, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/ap_vendor_list.html', {
        'entity': entity,
        'page_obj': page,
    })


@login_required
def ap_vendor_add(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendor',
        'accounting-ap-vendor-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    if request.method == 'POST':
        form = APVendorForm(request.POST, entity=entity)
        if form.is_valid():
            vendor = form.save(commit=False)
            vendor.entity = entity
            try:
                vendor.full_clean()
                vendor.save()
                AuditLog.log('create', 'accounting', f"AP vendor created: {vendor.code}", user=request.user)
                messages.success(request, 'AP vendor created.')
                return redirect('accounting-ap-vendor-list')
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        default_ap = ChartOfAccount.objects.filter(entity=entity, code='2000').first()
        form = APVendorForm(entity=entity, initial={'default_ap_account': default_ap, 'is_active': True})
    return render(request, 'accounting/ap_vendor_form.html', {
        'entity': entity,
        'form': form,
        'is_edit': False,
    })


@login_required
def ap_vendor_edit(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendor',
        'accounting-ap-vendor-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    vendor = get_object_or_404(APVendor, entity=entity, pk=pk)
    if request.method == 'POST':
        form = APVendorForm(request.POST, entity=entity, instance=vendor)
        if form.is_valid():
            try:
                vendor = form.save(commit=False)
                vendor.full_clean()
                vendor.save()
                AuditLog.log('update', 'accounting', f"AP vendor updated: {vendor.code}", user=request.user)
                messages.success(request, 'AP vendor updated.')
                return redirect('accounting-ap-vendor-list')
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = APVendorForm(entity=entity, instance=vendor)
    return render(request, 'accounting/ap_vendor_form.html', {
        'entity': entity,
        'form': form,
        'vendor': vendor,
        'is_edit': True,
    })


@login_required
def ap_vendor_bill_add(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    if request.method == 'POST':
        form = APVendorBillForm(request.POST, entity=entity)
        if form.is_valid():
            try:
                bill = create_ap_vendor_bill_draft(
                    entity,
                    form.cleaned_data['vendor_name'],
                    form.cleaned_data['bill_number'],
                    form.cleaned_data['document_date'],
                    form.cleaned_data['due_date'],
                    form.cleaned_data['expense_account'],
                    form.cleaned_data['ap_account'],
                    form.cleaned_data['amount'],
                    vendor=form.cleaned_data['vendor'],
                    tax_treatment=form.cleaned_data['tax_treatment'],
                    base_amount=form.cleaned_data['base_amount'],
                    input_vat_amount=form.cleaned_data['input_vat_amount'],
                    notes=form.cleaned_data['notes'],
                    created_by=request.user,
                )
                AuditLog.log('create', 'accounting', f"AP vendor bill draft created: {bill.bill_number}", user=request.user)
                messages.success(request, f"AP vendor bill created with draft journal {bill.journal_entry.entry_number}.")
                return redirect('accounting-ap-vendor-bill-detail', pk=bill.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        initial = {'document_date': date.today(), 'due_date': date.today()}
        selected_vendor = APVendor.objects.filter(
            entity=entity,
            is_active=True,
            pk=request.GET.get('vendor'),
        ).first()
        if selected_vendor:
            initial.update({
                'vendor': selected_vendor,
                'vendor_name': selected_vendor.display_name,
                'tax_treatment': selected_vendor.tax_classification if selected_vendor.tax_classification != 'unknown' else 'non_vat',
                'expense_account': selected_vendor.default_expense_account,
                'ap_account': selected_vendor.default_ap_account,
            })
        default_ap = ChartOfAccount.objects.filter(entity=entity, code='2000').first()
        if default_ap and not initial.get('ap_account'):
            initial['ap_account'] = default_ap
        form = APVendorBillForm(entity=entity, initial=initial)
    return render(request, 'accounting/ap_vendor_bill_form.html', {
        'entity': entity,
        'form': form,
    })


@login_required
def ap_vendor_bill_detail(request, pk):
    permission_check = _require_accounting_perm(request, 'accounting.view_apvendorbill')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    bill = get_object_or_404(
        APVendorBill.objects.select_related('vendor', 'expense_account', 'ap_account', 'journal_entry', 'void_journal_entry'),
        entity=entity,
        pk=pk,
    )
    refresh_ap_vendor_bill_status(bill)
    payments = (
        bill.payments
        .select_related('cash_account', 'journal_entry', 'void_journal_entry', 'matched_by')
        .order_by('-payment_date', '-created_at')
    )
    for payment in payments:
        refresh_ap_vendor_payment_status(payment)
    attachments = bill.attachments.select_related('uploaded_by').order_by('-uploaded_at')
    return render(request, 'accounting/ap_vendor_bill_detail.html', {
        'entity': entity,
        'bill': bill,
        'payments': payments,
        'attachments': attachments,
    })


@login_required
def ap_vendor_bill_void(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    bill = get_object_or_404(
        APVendorBill.objects.select_related('journal_entry', 'void_journal_entry'),
        entity=entity,
        pk=pk,
    )
    refresh_ap_vendor_bill_status(bill)
    if request.method == 'POST':
        form = APVendorBillVoidForm(request.POST)
        if form.is_valid():
            try:
                reversal_journal = create_ap_vendor_bill_void_draft(
                    bill,
                    form.cleaned_data['reason'],
                    created_by=request.user,
                )
                if reversal_journal:
                    AuditLog.log('create', 'accounting', f"AP vendor bill void draft created: {bill.bill_number}", user=request.user)
                    messages.success(request, f"AP bill void draft created as journal {reversal_journal.entry_number}.")
                else:
                    AuditLog.log('void', 'accounting', f"Draft AP vendor bill voided: {bill.bill_number}", user=request.user)
                    messages.success(request, 'Draft AP vendor bill voided.')
                return redirect('accounting-ap-vendor-bill-detail', pk=bill.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = APVendorBillVoidForm()
    return render(request, 'accounting/ap_vendor_bill_void_form.html', {
        'entity': entity,
        'bill': bill,
        'form': form,
    })


@login_required
def ap_vendor_bill_attachment_add(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbillattachment',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    bill = get_object_or_404(APVendorBill, entity=entity, pk=pk)
    if request.method == 'POST':
        form = APVendorBillAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = create_ap_vendor_bill_attachment(
                bill,
                form.cleaned_data['file'],
                document_type=form.cleaned_data['document_type'],
                note=form.cleaned_data['note'],
                uploaded_by=request.user,
            )
            AuditLog.log('create', 'accounting', f"AP vendor bill attachment uploaded: {attachment.original_filename}", user=request.user)
            messages.success(request, 'AP vendor bill attachment uploaded.')
            return redirect('accounting-ap-vendor-bill-detail', pk=bill.pk)
    else:
        form = APVendorBillAttachmentForm()
    return render(request, 'accounting/ap_vendor_bill_attachment_form.html', {
        'entity': entity,
        'bill': bill,
        'form': form,
    })


@login_required
def ap_vendor_bill_attachment_download(request, pk, attachment_pk):
    permission_check = _require_accounting_perm(request, 'accounting.view_apvendorbillattachment')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    attachment = get_object_or_404(
        APVendorBillAttachment.objects.select_related('bill'),
        entity=entity,
        bill_id=pk,
        pk=attachment_pk,
    )
    return FileResponse(
        attachment.file.open('rb'),
        as_attachment=True,
        filename=attachment.original_filename,
    )


@login_required
def ap_vendor_payment_add(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    bill = get_object_or_404(
        APVendorBill.objects.select_related('ap_account', 'journal_entry'),
        entity=entity,
        pk=pk,
    )
    refresh_ap_vendor_bill_status(bill)
    if request.method == 'POST':
        form = APVendorPaymentForm(request.POST, entity=entity, bill=bill)
        if form.is_valid():
            try:
                payment = create_ap_vendor_payment_draft(
                    bill,
                    form.cleaned_data['payment_date'],
                    form.cleaned_data['amount'],
                    form.cleaned_data['cash_account'],
                    reference=form.cleaned_data['reference'],
                    created_by=request.user,
                )
                AuditLog.log('create', 'accounting', f"AP vendor payment draft created: {bill.bill_number}", user=request.user)
                messages.success(request, f"AP payment created with draft journal {payment.journal_entry.entry_number}.")
                return redirect('accounting-ap-vendor-bill-detail', pk=bill.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = APVendorPaymentForm(entity=entity, bill=bill, initial={'payment_date': date.today()})
    return render(request, 'accounting/ap_vendor_payment_form.html', {
        'entity': entity,
        'bill': bill,
        'form': form,
    })


@login_required
def ap_vendor_payment_void(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    payment = get_object_or_404(
        APVendorPayment.objects.select_related('bill', 'journal_entry', 'void_journal_entry'),
        entity=entity,
        pk=pk,
    )
    refresh_ap_vendor_payment_status(payment)
    if request.method == 'POST':
        form = APVendorPaymentVoidForm(request.POST)
        if form.is_valid():
            try:
                reversal_journal = create_ap_vendor_payment_void_draft(
                    payment,
                    form.cleaned_data['reason'],
                    created_by=request.user,
                )
                if reversal_journal:
                    AuditLog.log('create', 'accounting', f"AP vendor payment void draft created: {payment.reference or payment.pk}", user=request.user)
                    messages.success(request, f"AP payment void draft created as journal {reversal_journal.entry_number}.")
                else:
                    AuditLog.log('void', 'accounting', f"Draft AP vendor payment voided: {payment.reference or payment.pk}", user=request.user)
                    messages.success(request, 'Draft AP payment voided.')
                return redirect('accounting-ap-vendor-bill-detail', pk=payment.bill.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = APVendorPaymentVoidForm()
    return render(request, 'accounting/ap_vendor_payment_void_form.html', {
        'entity': entity,
        'payment': payment,
        'form': form,
    })


@login_required
def ap_vendor_payment_settlement(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    payment = get_object_or_404(
        APVendorPayment.objects.select_related('bill', 'journal_entry', 'void_journal_entry'),
        entity=entity,
        pk=pk,
    )
    refresh_ap_vendor_payment_status(payment)
    if request.method == 'POST':
        form = APVendorPaymentSettlementForm(request.POST)
        if form.is_valid():
            try:
                match_ap_vendor_payment_settlement(
                    payment,
                    form.cleaned_data['settlement_date'],
                    form.cleaned_data['settlement_reference'],
                    settlement_note=form.cleaned_data['settlement_note'],
                    matched_by=request.user,
                )
                AuditLog.log('update', 'accounting', f"AP vendor payment matched to settlement: {payment.reference or payment.pk}", user=request.user)
                messages.success(request, 'AP payment settlement matched.')
                return redirect('accounting-ap-vendor-bill-detail', pk=payment.bill.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = APVendorPaymentSettlementForm(initial={
            'settlement_date': payment.settlement_date or date.today(),
            'settlement_reference': payment.settlement_reference,
            'settlement_note': payment.settlement_note,
        })
    return render(request, 'accounting/ap_vendor_payment_settlement_form.html', {
        'entity': entity,
        'payment': payment,
        'form': form,
    })


@login_required
def ap_vendor_payment_settlement_clear(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_apvendorbill',
        'accounting-ap-vendor-bill-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    payment = get_object_or_404(APVendorPayment.objects.select_related('bill'), entity=entity, pk=pk)
    if request.method == 'POST':
        clear_ap_vendor_payment_settlement(payment)
        AuditLog.log('update', 'accounting', f"AP vendor payment settlement cleared: {payment.reference or payment.pk}", user=request.user)
        messages.success(request, 'AP payment settlement match cleared.')
    return redirect('accounting-ap-vendor-bill-detail', pk=payment.bill.pk)


@login_required
def ap_aging(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    as_of_date, selected_as_of_preset = _report_as_of_date(request, date.today())
    report = build_ap_aging_report(entity, as_of_date=as_of_date)
    headers = ['vendor_name', 'reference', 'document_date', 'due_date', 'account_code', 'account_name', 'days_overdue', 'bucket', 'amount', 'source']
    export_response = report_export_response(
        request,
        f'accounting-ap-aging-{as_of_date}',
        'AP Aging',
        headers,
        _ap_aging_csv_rows(report),
        {
            'as_of_date': as_of_date,
            'preset': selected_as_of_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/ap_aging.html', {
        'entity': entity,
        'as_of_date': as_of_date,
        'report': report,
        'as_of_preset_choices': AS_OF_PRESET_CHOICES,
        'selected_as_of_preset': selected_as_of_preset,
        **_saved_report_preset_context(request, entity, 'ap_aging'),
        **_report_export_queries(request),
    })


@login_required
def tax_ledger(request):
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    today = date.today()
    start_date, end_date, selected_preset = _report_date_range(
        request,
        today.replace(month=1, day=1),
        today,
    )
    report = build_tax_ledger_report(entity, start_date=start_date, end_date=end_date)
    headers = ['section', 'code', 'name', 'opening_balance', 'debit_or_gross', 'credit_or_withheld', 'movement_or_status', 'ending_balance']
    export_response = report_export_response(
        request,
        f'accounting-tax-ledger-{start_date}-{end_date}',
        'Tax Ledger',
        headers,
        _tax_ledger_csv_rows(report),
        {
            'start_date': start_date,
            'end_date': end_date,
            'preset': selected_preset or 'manual',
        },
        entity=entity,
    )
    if export_response is not None:
        return export_response
    return render(request, 'accounting/tax_ledger.html', {
        'entity': entity,
        'start_date': start_date,
        'end_date': end_date,
        'report': report,
        'preset_choices': RANGE_PRESET_CHOICES,
        'selected_preset': selected_preset,
        **_saved_report_preset_context(request, entity, 'tax_ledger'),
        **_report_export_queries(request),
    })


@login_required
def source_review(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_accountingsourceposting')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    status = request.GET.get('status', '')
    source_type = request.GET.get('source_type', '')
    qs = (
        AccountingSourcePosting.objects
        .filter(Q(entity=entity) | Q(entity__isnull=True))
        .select_related('journal_entry', 'subscriber')
        .order_by('-document_date', '-created_at')
    )
    if status:
        qs = qs.filter(status=status)
    if source_type:
        qs = qs.filter(source_model__icontains=source_type)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/source_review.html', {
        'entity': entity,
        'page_obj': page,
        'status': status,
        'source_type': source_type,
        'status_choices': AccountingSourcePosting.STATUS_CHOICES,
        'source_type_options': [
            ('Invoice', 'Invoices'),
            ('Invoice.waiver', 'Invoice Waivers'),
            ('Invoice.void', 'Invoice Voids'),
            ('Payment.collection', 'Payments'),
            ('PaymentAllocation', 'Advance Applications'),
            ('AccountCreditAdjustment', 'Credit Adjustments'),
        ],
    })


@login_required
def source_posting_retry(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.review_accountingsourceposting',
        'accounting-source-review',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-source-review')
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    posting = get_object_or_404(
        AccountingSourcePosting.objects.filter(Q(entity=entity) | Q(entity__isnull=True)),
        pk=pk,
    )
    try:
        retry_source_posting(posting)
        posting.refresh_from_db()
        if posting.status == 'draft':
            messages.success(request, f"Source posting retried and draft journal is ready: {posting.source_number}.")
        elif posting.status == 'posted':
            messages.success(request, f"Source posting is already posted: {posting.source_number}.")
        elif posting.status == 'skipped':
            messages.info(request, f"Source posting retry skipped: {posting.blocked_reason or posting.source_number}.")
        else:
            messages.warning(request, f"Source posting is still blocked: {posting.blocked_reason}.")
        AuditLog.log(
            'update',
            'accounting',
            f"Source posting retry: {posting.source_model}:{posting.source_id} -> {posting.status}",
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-source-review')


@login_required
def cutover_dashboard(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_cutoverplan')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity

    plan = get_active_cutover_plan(entity)
    imports = OpeningBalanceImport.objects.none()
    if plan:
        imports = (
            OpeningBalanceImport.objects
            .filter(cutover_plan=plan)
            .select_related('journal_entry')
            .order_by('-created_at')
        )
    readiness = build_cutover_readiness(entity)
    return render(request, 'accounting/cutover_dashboard.html', {
        'entity': entity,
        'plan': plan,
        'imports': imports,
        'readiness': readiness,
        'cutover_locked': _cutover_is_locked(plan),
    })


@login_required
def cutover_setup(request):
    permission_check = _require_accounting_perm(request, 'accounting.manage_cutoverplan', 'accounting-cutover-dashboard')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if _cutover_is_locked(plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-cutover-dashboard')

    if request.method == 'POST':
        form = CutoverPlanForm(request.POST, instance=plan)
        if form.is_valid():
            try:
                plan, created = create_cutover_plan(
                    entity,
                    form.cleaned_data['cutover_date'],
                    prepared_by=request.user,
                    notes=form.cleaned_data['notes'],
                    source_policy=form.cleaned_data['source_policy'],
                )
                AuditLog.log(
                    'create' if created else 'update',
                    'accounting',
                    f"Cutover plan {'created' if created else 'updated'}: {plan.cutover_date}",
                    user=request.user,
                )
                messages.success(request, 'Cutover plan saved.')
                return redirect('accounting-cutover-dashboard')
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = CutoverPlanForm(instance=plan, initial={'cutover_date': date.today()})

    return render(request, 'accounting/cutover_setup.html', {
        'entity': entity,
        'plan': plan,
        'form': form,
    })


@login_required
def opening_balance_import_add(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_openingbalanceimport',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before entering opening balances.')
        return redirect('accounting-cutover-setup')
    if _cutover_is_locked(plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-cutover-dashboard')

    if request.method == 'POST':
        form = OpeningBalanceImportForm(request.POST)
        if form.is_valid():
            import_batch = form.save(commit=False)
            import_batch.entity = entity
            import_batch.cutover_plan = plan
            import_batch.created_by = request.user
            try:
                import_batch.full_clean()
                import_batch.save()
                AuditLog.log(
                    'create',
                    'accounting',
                    f"Opening balance import created for {plan.cutover_date}",
                    user=request.user,
                )
                messages.success(request, 'Opening balance import created.')
                return redirect('accounting-opening-balance-import-detail', pk=import_batch.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = OpeningBalanceImportForm(initial={'import_type': 'manual'})

    return render(request, 'accounting/opening_balance_import_form.html', {
        'entity': entity,
        'plan': plan,
        'form': form,
    })


@login_required
def opening_balance_import_detail(request, pk):
    permission_check = _require_accounting_perm(request, 'accounting.view_openingbalanceimport')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    import_batch = get_object_or_404(
        OpeningBalanceImport.objects.select_related('cutover_plan', 'journal_entry'),
        entity=entity,
        pk=pk,
    )
    lines = import_batch.lines.select_related('account', 'subscriber').order_by('id')
    return render(request, 'accounting/opening_balance_import_detail.html', {
        'entity': entity,
        'import_batch': import_batch,
        'plan': import_batch.cutover_plan,
        'lines': lines,
        'can_edit': (
            not import_batch.journal_entry_id
            and import_batch.status not in ('journal_created', 'posted', 'voided')
            and not _cutover_is_locked(import_batch.cutover_plan)
        ),
    })


@login_required
def opening_balance_line_add(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_openingbalanceimport',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    import_batch = get_object_or_404(
        OpeningBalanceImport.objects.select_related('cutover_plan', 'journal_entry'),
        entity=entity,
        pk=pk,
    )
    if import_batch.journal_entry_id or import_batch.status in ('journal_created', 'posted', 'voided'):
        messages.error(request, 'This opening balance import is read-only.')
        return redirect('accounting-opening-balance-import-detail', pk=import_batch.pk)
    if _cutover_is_locked(import_batch.cutover_plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-opening-balance-import-detail', pk=import_batch.pk)

    if request.method == 'POST':
        form = OpeningBalanceLineForm(request.POST, entity=entity)
        if form.is_valid():
            line = form.save(commit=False)
            line.import_batch = import_batch
            line.entity = entity
            try:
                line.full_clean()
                line.save()
                refresh_opening_balance_totals(import_batch)
                AuditLog.log(
                    'create',
                    'accounting',
                    f"Opening balance line added: {line.account.code}",
                    user=request.user,
                )
                messages.success(request, 'Opening balance line added.')
                return redirect('accounting-opening-balance-import-detail', pk=import_batch.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = OpeningBalanceLineForm(entity=entity)

    return render(request, 'accounting/opening_balance_line_form.html', {
        'entity': entity,
        'plan': import_batch.cutover_plan,
        'import_batch': import_batch,
        'form': form,
    })


@login_required
def opening_balance_import_validate(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_openingbalanceimport',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-opening-balance-import-detail', pk=pk)
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    import_batch = get_object_or_404(OpeningBalanceImport, entity=entity, pk=pk)
    if _cutover_is_locked(import_batch.cutover_plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-opening-balance-import-detail', pk=pk)
    try:
        validate_opening_balance_import(import_batch)
        import_batch.refresh_from_db()
        if import_batch.validation_errors:
            messages.warning(request, 'Opening balance import still has validation issues.')
        else:
            messages.success(request, 'Opening balance import is balanced and validated.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-opening-balance-import-detail', pk=pk)


@login_required
def opening_balance_import_create_journal(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_openingbalanceimport',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-opening-balance-import-detail', pk=pk)
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    import_batch = get_object_or_404(OpeningBalanceImport, entity=entity, pk=pk)
    if _cutover_is_locked(import_batch.cutover_plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-opening-balance-import-detail', pk=pk)
    try:
        journal_entry = create_opening_balance_journal(import_batch, created_by=request.user)
        AuditLog.log(
            'create',
            'accounting',
            f"Opening balance journal created: {journal_entry.entry_number}",
            user=request.user,
        )
        messages.success(request, 'Draft opening journal created.')
        return redirect('accounting-journal-detail', pk=journal_entry.pk)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-opening-balance-import-detail', pk=pk)


@login_required
def cutover_readiness(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_cutoverplan')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    readiness = build_cutover_readiness(entity)
    return render(request, 'accounting/cutover_readiness.html', {
        'entity': entity,
        'readiness': readiness,
        'plan': readiness.get('plan'),
    })


@login_required
def cutover_mark_ready(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverplan',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-cutover-dashboard')
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before marking it ready.')
        return redirect('accounting-cutover-setup')
    try:
        mark_cutover_ready(plan, reviewed_by=request.user)
        AuditLog.log('update', 'accounting', f"Cutover marked ready for review: {plan.cutover_date}", user=request.user)
        messages.success(request, 'Cutover marked ready for review.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-cutover-dashboard')


@login_required
def cutover_approve(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverplan',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-cutover-dashboard')
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before approval.')
        return redirect('accounting-cutover-setup')
    try:
        approve_cutover_plan(plan, approved_by=request.user)
        AuditLog.log('update', 'accounting', f"Cutover approved: {plan.cutover_date}", user=request.user)
        messages.success(request, 'Cutover approved and locked.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-cutover-dashboard')


@login_required
def cutover_go_live(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverplan',
        'accounting-cutover-dashboard',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-cutover-dashboard')
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before going live.')
        return redirect('accounting-cutover-setup')
    try:
        mark_accounting_live(plan, live_by=request.user)
        AuditLog.log('update', 'accounting', f"Accounting v2 moved live: {plan.cutover_date}", user=request.user)
        messages.success(request, 'Accounting v2 is live for this cutover.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-cutover-dashboard')


@login_required
def cutover_reconciliation(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_cutoverreconciliationsnapshot')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    snapshots = CutoverReconciliationSnapshot.objects.none()
    latest_snapshot = None
    lines = []
    balance_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    if plan:
        snapshots = (
            CutoverReconciliationSnapshot.objects
            .filter(cutover_plan=plan)
            .exclude(status='voided')
            .order_by('-generated_at', '-id')
        )
        latest_snapshot = get_latest_cutover_reconciliation_snapshot(plan)
        if latest_snapshot:
            lines = latest_snapshot.subscriber_lines.select_related('subscriber').order_by('balance_type', 'subscriber__username')
            if balance_type:
                lines = lines.filter(balance_type=balance_type)
            if status:
                lines = lines.filter(status=status)
    return render(request, 'accounting/cutover_reconciliation.html', {
        'entity': entity,
        'plan': plan,
        'snapshots': snapshots,
        'latest_snapshot': latest_snapshot,
        'lines': lines,
        'balance_type': balance_type,
        'status': status,
    })


@login_required
def cutover_reconciliation_generate(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverreconciliationsnapshot',
        'accounting-cutover-reconciliation',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-cutover-reconciliation')
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before generating reconciliation snapshots.')
        return redirect('accounting-cutover-setup')
    try:
        snapshot = generate_cutover_reconciliation_snapshot(plan, generated_by=request.user)
        AuditLog.log(
            'create',
            'accounting',
            f"Cutover reconciliation snapshot generated: {snapshot.pk}",
            user=request.user,
        )
        if snapshot.all_matched:
            messages.success(request, 'Subscriber AR and customer advances are reconciled.')
        else:
            messages.warning(request, 'Reconciliation snapshot generated with differences to review.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-cutover-reconciliation')


@login_required
def cutover_schedule_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_cutoverbalanceschedule')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    schedules = CutoverBalanceSchedule.objects.none()
    summary = []
    if plan:
        schedules = (
            CutoverBalanceSchedule.objects
            .filter(cutover_plan=plan)
            .exclude(status='voided')
            .order_by('schedule_type')
        )
        summary = build_cutover_balance_schedule_summary(plan)
    return render(request, 'accounting/cutover_schedule_list.html', {
        'entity': entity,
        'plan': plan,
        'schedules': schedules,
        'summary': summary,
        'cutover_locked': _cutover_is_locked(plan),
    })


@login_required
def cutover_schedule_add(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverbalanceschedule',
        'accounting-cutover-schedule-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    plan = get_active_cutover_plan(entity)
    if not plan:
        messages.info(request, 'Create a cutover plan before adding cutover balance schedules.')
        return redirect('accounting-cutover-setup')
    if _cutover_is_locked(plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-cutover-schedule-list')

    if request.method == 'POST':
        form = CutoverBalanceScheduleForm(request.POST)
        if form.is_valid():
            try:
                schedule, created = create_cutover_balance_schedule(
                    plan,
                    form.cleaned_data['schedule_type'],
                    created_by=request.user,
                    notes=form.cleaned_data['notes'],
                )
                AuditLog.log(
                    'create' if created else 'update',
                    'accounting',
                    f"Cutover balance schedule {'created' if created else 'opened'}: {schedule.get_schedule_type_display()}",
                    user=request.user,
                )
                messages.success(request, 'Cutover balance schedule is ready.')
                return redirect('accounting-cutover-schedule-detail', pk=schedule.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = CutoverBalanceScheduleForm()

    return render(request, 'accounting/cutover_schedule_form.html', {
        'entity': entity,
        'plan': plan,
        'form': form,
    })


@login_required
def cutover_schedule_detail(request, pk):
    permission_check = _require_accounting_perm(request, 'accounting.view_cutoverbalanceschedule')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    schedule = get_object_or_404(
        CutoverBalanceSchedule.objects.select_related('cutover_plan'),
        entity=entity,
        pk=pk,
    )
    refresh_cutover_balance_schedule(schedule)
    schedule.refresh_from_db()
    rows = build_cutover_balance_schedule_reconciliation(schedule)
    return render(request, 'accounting/cutover_schedule_detail.html', {
        'entity': entity,
        'plan': schedule.cutover_plan,
        'schedule': schedule,
        'lines': schedule.lines.select_related('account').order_by('account__code', 'label', 'id'),
        'rows': rows,
        'can_edit': schedule.status != 'voided' and not _cutover_is_locked(schedule.cutover_plan),
    })


@login_required
def cutover_schedule_line_add(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverbalanceschedule',
        'accounting-cutover-schedule-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    schedule = get_object_or_404(CutoverBalanceSchedule, entity=entity, pk=pk)
    if schedule.status == 'voided':
        messages.error(request, 'This cutover balance schedule is read-only.')
        return redirect('accounting-cutover-schedule-detail', pk=schedule.pk)
    if _cutover_is_locked(schedule.cutover_plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-cutover-schedule-detail', pk=schedule.pk)

    if request.method == 'POST':
        form = CutoverBalanceScheduleLineForm(request.POST, entity=entity)
        if form.is_valid():
            line = form.save(commit=False)
            line.schedule = schedule
            line.entity = entity
            try:
                line.full_clean()
                line.save()
                refresh_cutover_balance_schedule(schedule)
                AuditLog.log(
                    'create',
                    'accounting',
                    f"Cutover schedule line added: {line.account.code}",
                    user=request.user,
                )
                messages.success(request, 'Schedule line added.')
                return redirect('accounting-cutover-schedule-detail', pk=schedule.pk)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        form = CutoverBalanceScheduleLineForm(entity=entity)

    return render(request, 'accounting/cutover_schedule_line_form.html', {
        'entity': entity,
        'plan': schedule.cutover_plan,
        'schedule': schedule,
        'form': form,
    })


@login_required
def cutover_schedule_validate(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.manage_cutoverbalanceschedule',
        'accounting-cutover-schedule-list',
    )
    if permission_check is not True:
        return permission_check
    if request.method != 'POST':
        return redirect('accounting-cutover-schedule-detail', pk=pk)
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    schedule = get_object_or_404(CutoverBalanceSchedule, entity=entity, pk=pk)
    if _cutover_is_locked(schedule.cutover_plan):
        messages.error(request, 'Approved or live cutover plans are locked.')
        return redirect('accounting-cutover-schedule-detail', pk=pk)
    try:
        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()
        if schedule.status == 'reconciled':
            messages.success(request, 'Cutover balance schedule reconciles to opening balances.')
        else:
            messages.warning(request, 'Cutover balance schedule has differences to review.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('accounting-cutover-schedule-detail', pk=pk)


@login_required
def withholding_2307_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_customerwithholdingtaxclaim')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()
    qs = (
        CustomerWithholdingTaxClaim.objects
        .filter(Q(entity=entity) | Q(entity__isnull=True))
        .select_related('subscriber', 'payment', 'withholding_class')
        .prefetch_related('allocations__invoice')
        .order_by('-received_date', '-created_at')
    )
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(subscriber__username__icontains=q)
            | Q(subscriber__full_name__icontains=q)
            | Q(payor_name__icontains=q)
            | Q(payor_tin__icontains=q)
            | Q(certificate_number__icontains=q)
        )
    totals = qs.aggregate(
        gross_total=Sum('gross_amount'),
        withheld_total=Sum('tax_withheld'),
    )
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/withholding_2307_list.html', {
        'entity': entity,
        'page_obj': page,
        'status': status,
        'q': q,
        'status_choices': CustomerWithholdingTaxClaim.STATUS_CHOICES,
        'gross_total': totals['gross_total'] or Decimal('0.00'),
        'withheld_total': totals['withheld_total'] or Decimal('0.00'),
    })


@login_required
def atc_code_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_alphanumerictaxcode')
    if permission_check is not True:
        return permission_check
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = AlphanumericTaxCode.objects.all().order_by('tax_family', 'code')
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(description__icontains=q))
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/atc_code_list.html', {
        'page_obj': page,
        'q': q,
        'status': status,
    })


@login_required
def withholding_class_list(request):
    permission_check = _require_accounting_perm(request, 'accounting.view_withholdingtaxclass')
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    qs = WithholdingTaxClass.objects.filter(entity=entity).order_by('tax_family', 'code', 'name')
    return render(request, 'accounting/withholding_class_list.html', {
        'entity': entity,
        'classes': qs,
    })


@login_required
def withholding_class_add(request):
    permission_check = _require_accounting_perm(
        request,
        'accounting.add_withholdingtaxclass',
        'accounting-withholding-class-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    if request.method == 'POST':
        form = WithholdingTaxClassForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.entity = entity
            try:
                obj.full_clean()
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
                return render(request, 'accounting/withholding_class_form.html', {
                    'entity': entity,
                    'form': form,
                    'title': 'Add Withholding Class',
                })
            obj.save()
            AuditLog.log('create', 'accounting', f"Withholding tax class created: {obj.code}", user=request.user)
            messages.success(request, 'Withholding tax class saved.')
            return redirect('accounting-withholding-class-list')
    else:
        form = WithholdingTaxClassForm(initial={'rate': Decimal('0.0000'), 'is_active': True})
    return render(request, 'accounting/withholding_class_form.html', {
        'entity': entity,
        'form': form,
        'title': 'Add Withholding Class',
    })


@login_required
def withholding_class_edit(request, pk):
    permission_check = _require_accounting_perm(
        request,
        'accounting.change_withholdingtaxclass',
        'accounting-withholding-class-list',
    )
    if permission_check is not True:
        return permission_check
    entity = _require_entity(request)
    if not isinstance(entity, AccountingEntity):
        return entity
    obj = get_object_or_404(WithholdingTaxClass, entity=entity, pk=pk)
    if request.method == 'POST':
        form = WithholdingTaxClassForm(request.POST, instance=obj)
        if form.is_valid():
            try:
                obj = form.save()
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
                return render(request, 'accounting/withholding_class_form.html', {
                    'entity': entity,
                    'form': form,
                    'title': 'Edit Withholding Class',
                    'withholding_class': obj,
                })
            AuditLog.log('update', 'accounting', f"Withholding tax class updated: {obj.code}", user=request.user)
            messages.success(request, 'Withholding tax class updated.')
            return redirect('accounting-withholding-class-list')
    else:
        form = WithholdingTaxClassForm(instance=obj)
    return render(request, 'accounting/withholding_class_form.html', {
        'entity': entity,
        'form': form,
        'title': 'Edit Withholding Class',
        'withholding_class': obj,
    })


@login_required
def income_list(request):
    qs = IncomeRecord.objects.all()
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/income_list.html', {'page_obj': page})


@login_required
def income_add(request):
    if request.method == 'POST':
        form = IncomeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            AuditLog.log('create', 'accounting', f"Income added: PHP {obj.amount}", user=request.user)
            messages.success(request, 'Income record added.')
            return redirect('income-list')
    else:
        form = IncomeForm(initial={'date': date.today(), 'recorded_by': request.user.username})
    return render(request, 'accounting/income_form.html', {'form': form, 'title': 'Add Income'})


@login_required
def expense_list(request):
    qs = ExpenseRecord.objects.all()
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'accounting/expense_list.html', {'page_obj': page})


@login_required
def expense_add(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            obj = form.save()
            AuditLog.log('create', 'accounting', f"Expense added: PHP {obj.amount}", user=request.user)
            messages.success(request, 'Expense record added.')
            return redirect('expense-list')
    else:
        form = ExpenseForm(initial={'date': date.today(), 'recorded_by': request.user.username})
    return render(request, 'accounting/expense_form.html', {'form': form, 'title': 'Add Expense'})


@login_required
def sync_income(request):
    count = sync_payments_to_income()
    messages.success(request, f"Synced {count} billing payments to income records.")
    return redirect('accounting-dashboard')
