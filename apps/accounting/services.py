from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounting.models import (
    AccountingEntity,
    AccountingPeriod,
    AccountingSettings,
    AccountingSourcePosting,
    AlphanumericTaxCode,
    ChartOfAccount,
    CUTOVER_LOCKED_STATUSES,
    CutoverBalanceSchedule,
    CutoverBalanceScheduleLine,
    CutoverPlan,
    CutoverReconciliationSnapshot,
    CutoverSubscriberBalanceLine,
    CustomerWithholdingAllocation,
    CustomerWithholdingTaxClaim,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    JournalLine,
    OpeningBalanceImport,
    OpeningBalanceLine,
    SourceDocumentLink,
)
from apps.billing.models import AccountCreditAdjustment, Invoice, Payment, PaymentAllocation
from apps.accounting.atc_seed import DEFAULT_BIR_ATC_CODES


def _account(code, name, account_type, normal_balance, description=''):
    return {
        'code': code,
        'name': name,
        'account_type': account_type,
        'normal_balance': normal_balance,
        'description': description,
    }


COMMON_ISP_ACCOUNTS = [
    _account('1000', 'Cash on Hand', 'asset', 'debit'),
    _account('1010', 'Bank Accounts', 'asset', 'debit'),
    _account('1020', 'E-Wallet and Gateway Clearing', 'asset', 'debit'),
    _account('1100', 'Accounts Receivable - Subscribers', 'asset', 'debit'),
    _account('1210', 'Creditable Withholding Tax Receivable', 'asset', 'debit'),
    _account('1300', 'CPE and Network Inventory', 'asset', 'debit'),
    _account('1400', 'Prepaid Expenses', 'asset', 'debit'),
    _account('1500', 'Network Equipment and Facilities', 'asset', 'debit'),
    _account('1590', 'Accumulated Depreciation - Network Equipment', 'asset', 'credit'),
    _account('2000', 'Accounts Payable', 'liability', 'credit'),
    _account('2110', 'Refunds Payable', 'liability', 'credit'),
    _account('2100', 'Customer Advances', 'liability', 'credit'),
    _account('2200', 'Subscriber Deposits', 'liability', 'credit'),
    _account('2310', 'Withholding Tax Payable', 'liability', 'credit'),
    _account('2400', 'Loans Payable', 'liability', 'credit'),
    _account('4000', 'Internet Service Revenue', 'revenue', 'credit'),
    _account('4010', 'Installation and Activation Revenue', 'revenue', 'credit'),
    _account('4020', 'CPE and Other Service Revenue', 'revenue', 'credit'),
    _account('5000', 'Bandwidth and Upstream Cost', 'direct_cost', 'debit'),
    _account('5010', 'Pole, Facility, and Site Rental', 'direct_cost', 'debit'),
    _account('5020', 'Network Repair and Maintenance', 'direct_cost', 'debit'),
    _account('6000', 'Salaries and Wages', 'expense', 'debit'),
    _account('6010', 'Utilities Expense', 'expense', 'debit'),
    _account('6020', 'Office and Administrative Expense', 'expense', 'debit'),
    _account('6030', 'Professional Fees', 'expense', 'debit'),
    _account('6040', 'Depreciation Expense', 'expense', 'debit'),
    _account('6050', 'Bad Debts and Subscriber Waivers', 'expense', 'debit'),
    _account('7000', 'Other Income', 'other_income', 'credit'),
    _account('8000', 'Other Expense', 'other_expense', 'debit'),
]

CASH_EQUIVALENT_ACCOUNT_CODES = ('1000', '1010', '1020')
AR_CONTROL_ACCOUNT_CODE = '1100'
AP_CONTROL_ACCOUNT_CODE = '2000'
TAX_LEDGER_ACCOUNT_CODES = ('1200', '1210', '2300', '2310', '2320', '2330', '6060')
TEMPORARY_ACCOUNT_TYPES = ('revenue', 'direct_cost', 'expense', 'other_income', 'other_expense')
CLOSING_EQUITY_ACCOUNT_CODE = '3100'

VAT_ACCOUNTS = [
    _account('1200', 'Input VAT', 'asset', 'debit'),
    _account('2300', 'Output VAT', 'liability', 'credit'),
    _account('2320', 'VAT Payable', 'liability', 'credit'),
]

NON_VAT_ACCOUNTS = [
    _account('2330', 'Percentage Tax Payable', 'liability', 'credit'),
    _account('6060', 'Percentage Tax Expense', 'expense', 'debit'),
]

SOLE_PROPRIETOR_EQUITY_ACCOUNTS = [
    _account('3000', "Owner's Capital", 'equity', 'credit'),
    _account('3050', "Owner's Drawings", 'equity', 'debit'),
    _account('3100', 'Current Year Earnings', 'equity', 'credit'),
]

CORPORATION_EQUITY_ACCOUNTS = [
    _account('3000', 'Share Capital', 'equity', 'credit'),
    _account('3100', 'Retained Earnings', 'equity', 'credit'),
    _account('3200', 'Dividends Declared', 'equity', 'debit'),
]

COA_TEMPLATES = {
    'isp_non_vat_sole_prop': {
        'label': 'ISP Non-VAT Sole Proprietor',
        'taxpayer_type': 'sole_proprietor',
        'tax_classification': 'non_vat',
        'accounts': COMMON_ISP_ACCOUNTS + NON_VAT_ACCOUNTS + SOLE_PROPRIETOR_EQUITY_ACCOUNTS,
    },
    'isp_vat_sole_prop': {
        'label': 'ISP VAT Sole Proprietor',
        'taxpayer_type': 'sole_proprietor',
        'tax_classification': 'vat',
        'accounts': COMMON_ISP_ACCOUNTS + VAT_ACCOUNTS + SOLE_PROPRIETOR_EQUITY_ACCOUNTS,
    },
    'isp_non_vat_corporation': {
        'label': 'ISP Non-VAT Corporation',
        'taxpayer_type': 'corporation',
        'tax_classification': 'non_vat',
        'accounts': COMMON_ISP_ACCOUNTS + NON_VAT_ACCOUNTS + CORPORATION_EQUITY_ACCOUNTS,
    },
    'isp_vat_corporation': {
        'label': 'ISP VAT Corporation',
        'taxpayer_type': 'corporation',
        'tax_classification': 'vat',
        'accounts': COMMON_ISP_ACCOUNTS + VAT_ACCOUNTS + CORPORATION_EQUITY_ACCOUNTS,
    },
}


def available_coa_templates():
    return [
        {'key': key, 'label': value['label']}
        for key, value in COA_TEMPLATES.items()
    ]


def seed_bir_atc_codes():
    created = 0
    updated = 0
    for item in DEFAULT_BIR_ATC_CODES:
        defaults = {
            'description': item['description'],
            'tax_family': item['tax_family'],
            'taxpayer_type': item['taxpayer_type'],
            'rate': item['rate'],
            'rate_label': item['rate_label'],
            'bir_form': item['bir_form'],
            'payor_type': item['payor_type'],
            'source_reference': item['source_reference'],
            'source_url': item['source_url'],
            'is_active': item['is_active'],
            'notes': item['notes'],
        }
        _, was_created = AlphanumericTaxCode.objects.update_or_create(
            code=item['code'],
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return {
        'created': created,
        'updated': updated,
        'total': len(DEFAULT_BIR_ATC_CODES),
    }


def get_coa_template(template_key):
    try:
        return COA_TEMPLATES[template_key]
    except KeyError as exc:
        raise ValidationError(f"Unknown accounting COA template: {template_key}") from exc


def seed_chart_of_accounts(entity, template_key):
    template = get_coa_template(template_key)
    created = 0
    updated = 0

    for account in template['accounts']:
        obj, was_created = ChartOfAccount.objects.get_or_create(
            entity=entity,
            code=account['code'],
            defaults={
                'name': account['name'],
                'account_type': account['account_type'],
                'normal_balance': account['normal_balance'],
                'description': account.get('description', ''),
                'is_system': True,
            },
        )
        if was_created:
            created += 1
            continue

        changed = False
        for field in ('name', 'account_type', 'normal_balance', 'description'):
            value = account.get(field, '')
            if getattr(obj, field) != value:
                setattr(obj, field, value)
                changed = True
        if not obj.is_system:
            obj.is_system = True
            changed = True
        if changed:
            obj.save(update_fields=[
                'name',
                'account_type',
                'normal_balance',
                'description',
                'is_system',
                'updated_at',
            ])
            updated += 1

    return {
        'created': created,
        'updated': updated,
        'total': len(template['accounts']),
        'template': template,
    }


def _safe_month_date(year, month, day):
    return date(year, month, min(day, monthrange(year, month)[1]))


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def create_monthly_periods(entity, fiscal_year=None, start_month=1, start_day=1):
    fiscal_year = fiscal_year or timezone.localdate().year
    start_month = max(1, min(12, int(start_month or 1)))
    start_day = max(1, min(31, int(start_day or 1)))
    first_month = date(fiscal_year, start_month, 1)
    periods = []
    created = 0

    for index in range(12):
        period_month = _add_months(first_month, index)
        next_month = _add_months(first_month, index + 1)
        start_date = _safe_month_date(period_month.year, period_month.month, start_day)
        next_start = _safe_month_date(next_month.year, next_month.month, start_day)
        end_date = next_start - timedelta(days=1)
        name = start_date.strftime('%B %Y')
        period, was_created = AccountingPeriod.objects.get_or_create(
            entity=entity,
            fiscal_year=fiscal_year,
            period_number=index + 1,
            defaults={
                'name': name,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'open',
            },
        )
        periods.append(period)
        if was_created:
            created += 1

    return {'created': created, 'periods': periods}


@transaction.atomic
def create_accounting_foundation(
    entity_name='ISP Operator',
    template_key='isp_non_vat_sole_prop',
    fiscal_year=None,
    legal_name='',
    tin='',
    registered_address='',
):
    template = get_coa_template(template_key)
    entity = AccountingEntity.objects.filter(is_active=True).first()
    entity_created = False
    if not entity:
        entity = AccountingEntity.objects.create(
            name=entity_name,
            legal_name=legal_name,
            tin=tin,
            registered_address=registered_address,
            taxpayer_type=template['taxpayer_type'],
            tax_classification=template['tax_classification'],
            is_active=True,
        )
        entity_created = True

    settings_obj, _ = AccountingSettings.objects.get_or_create(entity=entity)
    if settings_obj.setup_status != 'live' and (
        entity.taxpayer_type != template['taxpayer_type']
        or entity.tax_classification != template['tax_classification']
    ):
        entity.taxpayer_type = template['taxpayer_type']
        entity.tax_classification = template['tax_classification']
        entity.save(update_fields=['taxpayer_type', 'tax_classification', 'updated_at'])
    coa_result = seed_chart_of_accounts(entity, template_key)
    period_result = create_monthly_periods(
        entity,
        fiscal_year=fiscal_year,
        start_month=settings_obj.fiscal_year_start_month,
        start_day=settings_obj.fiscal_year_start_day,
    )
    settings_obj.mark_foundation_ready(template_key)
    return {
        'entity': entity,
        'entity_created': entity_created,
        'settings': settings_obj,
        'coa': coa_result,
        'periods': period_result,
    }


def find_period_for_date(entity, entry_date):
    period = AccountingPeriod.objects.filter(
        entity=entity,
        start_date__lte=entry_date,
        end_date__gte=entry_date,
    ).first()
    if not period:
        raise ValidationError('No accounting period exists for the journal entry date.')
    return period


def next_journal_entry_number(entity, entry_date=None, prefix='JV'):
    entry_date = entry_date or timezone.localdate()
    stem = f"{prefix}-{entry_date.year}-"
    latest = (
        JournalEntry.objects
        .filter(entity=entity, entry_number__startswith=stem)
        .order_by('-entry_number')
        .values_list('entry_number', flat=True)
        .first()
    )
    sequence = 1
    if latest:
        try:
            sequence = int(latest.rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = (
                JournalEntry.objects
                .filter(entity=entity, entry_number__startswith=stem)
                .count()
                + 1
            )
    return f"{stem}{sequence:06d}"


def get_active_cutover_plan(entity):
    if not entity:
        return None
    return (
        CutoverPlan.objects
        .filter(entity=entity)
        .exclude(status='voided')
        .order_by('-cutover_date', '-created_at')
        .first()
    )


CUTOVER_BALANCE_SCHEDULE_CONFIG = {
    'cash_on_hand': {
        'label': 'Cash on Hand',
        'opening_line_types': ['cash'],
        'account_codes': ['1000'],
    },
    'bank_account': {
        'label': 'Bank Accounts',
        'opening_line_types': ['bank'],
        'account_codes': ['1010'],
    },
    'wallet_gateway': {
        'label': 'Wallet / Gateway Clearing',
        'opening_line_types': ['wallet_gateway'],
        'account_codes': ['1020'],
    },
    'accounts_payable': {
        'label': 'Accounts Payable',
        'opening_line_types': ['ap_vendor'],
        'account_codes': ['2000'],
    },
    'tax_balance': {
        'label': 'Tax Balances',
        'opening_line_types': ['tax'],
        'account_codes': ['1200', '1210', '2300', '2310', '2320', '2330'],
    },
    'inventory': {
        'label': 'Inventory',
        'opening_line_types': ['inventory'],
        'account_codes': ['1300'],
    },
    'fixed_assets': {
        'label': 'Fixed Assets and Depreciation',
        'opening_line_types': ['fixed_asset', 'accumulated_depreciation'],
        'account_codes': ['1500', '1590'],
    },
    'loans_payable': {
        'label': 'Loans Payable',
        'opening_line_types': ['loan'],
        'account_codes': ['2400'],
    },
    'equity_balance': {
        'label': 'Equity Balances',
        'opening_line_types': ['equity'],
        'account_codes': ['3000', '3050', '3100', '3200'],
    },
}


def available_cutover_balance_schedule_types():
    return [
        {'key': key, 'label': value['label']}
        for key, value in CUTOVER_BALANCE_SCHEDULE_CONFIG.items()
    ]


def get_cutover_balance_schedule_config(schedule_type):
    try:
        return CUTOVER_BALANCE_SCHEDULE_CONFIG[schedule_type]
    except KeyError as exc:
        raise ValidationError(f"Unsupported cutover balance schedule type: {schedule_type}.") from exc


def get_active_cutover_balance_schedule(plan, schedule_type):
    if not plan:
        return None
    return (
        CutoverBalanceSchedule.objects
        .filter(cutover_plan=plan, schedule_type=schedule_type)
        .exclude(status='voided')
        .first()
    )


@transaction.atomic
def create_cutover_plan(entity, cutover_date, prepared_by=None, notes='', source_policy='opening_balances_only_pre_cutover'):
    plan = get_active_cutover_plan(entity)
    if plan:
        if plan.status in CUTOVER_LOCKED_STATUSES:
            raise ValidationError('Approved or live cutover plans are locked.')
        plan.cutover_date = cutover_date
        plan.source_policy = source_policy
        plan.notes = notes
        if prepared_by and not plan.prepared_by_id:
            plan.prepared_by = prepared_by
        plan.full_clean()
        plan.save(update_fields=[
            'cutover_date',
            'source_policy',
            'notes',
            'prepared_by',
            'updated_at',
        ])
        return plan, False

    plan = CutoverPlan(
        entity=entity,
        cutover_date=cutover_date,
        source_policy=source_policy,
        prepared_by=prepared_by,
        notes=notes,
    )
    plan.full_clean()
    plan.save()
    return plan, True


@transaction.atomic
def create_cutover_balance_schedule(plan, schedule_type, created_by=None, notes=''):
    get_cutover_balance_schedule_config(schedule_type)
    if plan.status in CUTOVER_LOCKED_STATUSES:
        raise ValidationError('Approved or live cutover plans are locked.')
    schedule = get_active_cutover_balance_schedule(plan, schedule_type)
    if schedule:
        if notes:
            schedule.notes = notes
            schedule.save(update_fields=['notes', 'updated_at'])
        return schedule, False

    schedule = CutoverBalanceSchedule(
        entity=plan.entity,
        cutover_plan=plan,
        schedule_type=schedule_type,
        created_by=created_by,
        notes=notes,
    )
    schedule.full_clean()
    schedule.save()
    return schedule, True


def _opening_balance_lines_for_schedule(schedule):
    config = get_cutover_balance_schedule_config(schedule.schedule_type)
    criteria = Q(line_type__in=config['opening_line_types'])
    if config.get('account_codes'):
        criteria |= Q(account__code__in=config['account_codes'])
    return OpeningBalanceLine.objects.filter(
        criteria,
        import_batch__cutover_plan=schedule.cutover_plan,
        import_batch__status__in=['validated', 'journal_created', 'posted'],
    )


def _account_amount_map(qs):
    rows = (
        qs.values('account_id', 'account__code', 'account__name')
        .annotate(debit_total=Sum('debit'), credit_total=Sum('credit'))
        .order_by('account__code')
    )
    return {
        row['account_id']: {
            'account_id': row['account_id'],
            'account_code': row['account__code'],
            'account_name': row['account__name'],
            'debit': row['debit_total'] or Decimal('0.00'),
            'credit': row['credit_total'] or Decimal('0.00'),
        }
        for row in rows
    }


def build_cutover_balance_schedule_reconciliation(schedule):
    schedule_totals = _account_amount_map(schedule.lines.select_related('account'))
    opening_totals = _account_amount_map(_opening_balance_lines_for_schedule(schedule).select_related('account'))
    account_ids = sorted(
        set(schedule_totals) | set(opening_totals),
        key=lambda account_id: (
            (schedule_totals.get(account_id) or opening_totals.get(account_id))['account_code'],
            account_id,
        ),
    )
    rows = []
    for account_id in account_ids:
        schedule_row = schedule_totals.get(account_id, {})
        opening_row = opening_totals.get(account_id, {})
        account_code = schedule_row.get('account_code') or opening_row.get('account_code')
        account_name = schedule_row.get('account_name') or opening_row.get('account_name')
        schedule_debit = schedule_row.get('debit', Decimal('0.00'))
        schedule_credit = schedule_row.get('credit', Decimal('0.00'))
        opening_debit = opening_row.get('debit', Decimal('0.00'))
        opening_credit = opening_row.get('credit', Decimal('0.00'))
        difference = (schedule_debit - schedule_credit) - (opening_debit - opening_credit)
        if schedule_debit == opening_debit and schedule_credit == opening_credit:
            status = 'matched'
        elif schedule_debit == Decimal('0.00') and schedule_credit == Decimal('0.00'):
            status = 'missing_schedule'
        elif opening_debit == Decimal('0.00') and opening_credit == Decimal('0.00'):
            status = 'missing_opening'
        else:
            status = 'difference'
        rows.append({
            'account_id': account_id,
            'account_code': account_code,
            'account_name': account_name,
            'schedule_debit': schedule_debit,
            'schedule_credit': schedule_credit,
            'opening_debit': opening_debit,
            'opening_credit': opening_credit,
            'difference': difference,
            'status': status,
        })
    return rows


def refresh_cutover_balance_schedule(schedule):
    schedule_totals = schedule.lines.aggregate(
        debit_total=Sum('debit'),
        credit_total=Sum('credit'),
    )
    opening_totals = _opening_balance_lines_for_schedule(schedule).aggregate(
        debit_total=Sum('debit'),
        credit_total=Sum('credit'),
    )
    schedule.total_debit = schedule_totals['debit_total'] or Decimal('0.00')
    schedule.total_credit = schedule_totals['credit_total'] or Decimal('0.00')
    schedule.opening_total_debit = opening_totals['debit_total'] or Decimal('0.00')
    schedule.opening_total_credit = opening_totals['credit_total'] or Decimal('0.00')
    schedule.difference = (
        (schedule.total_debit - schedule.total_credit)
        - (schedule.opening_total_debit - schedule.opening_total_credit)
    )
    schedule.save(update_fields=[
        'total_debit',
        'total_credit',
        'opening_total_debit',
        'opening_total_credit',
        'difference',
        'updated_at',
    ])
    return schedule


@transaction.atomic
def validate_cutover_balance_schedule(schedule):
    schedule = (
        CutoverBalanceSchedule.objects
        .select_for_update()
        .select_related('cutover_plan')
        .get(pk=schedule.pk)
    )
    if schedule.status == 'voided':
        raise ValidationError('Voided cutover balance schedules cannot be validated.')
    if schedule.cutover_plan.status in CUTOVER_LOCKED_STATUSES:
        raise ValidationError('Approved or live cutover plans are locked.')

    errors = []
    lines = list(schedule.lines.select_related('account').order_by('account__code', 'label', 'id'))
    for line in lines:
        try:
            line.full_clean()
        except ValidationError as exc:
            message = _validation_message(exc)
            line.validation_status = 'error'
            line.validation_message = message
            line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])
            errors.append(f"Line {line.pk}: {message}")
            continue

        warnings = []
        if schedule.schedule_type in ('bank_account', 'wallet_gateway') and not line.reference:
            warnings.append('Reference is recommended for bank, wallet, and gateway balances.')
        if schedule.schedule_type == 'tax_balance' and not line.source_document_number:
            warnings.append('Tax balance schedule should cite a return, ledger, or worksheet reference.')
        if schedule.schedule_type == 'inventory' and not line.location:
            warnings.append('Inventory schedule should include storage or deployment location.')
        if schedule.schedule_type == 'fixed_assets':
            if line.debit > Decimal('0.00') and not line.asset_identifier:
                warnings.append('Fixed asset cost lines should include an asset tag, serial number, or batch identifier.')
            if line.debit > Decimal('0.00') and not line.acquisition_date:
                warnings.append('Fixed asset cost lines should include acquisition date when known.')
            if line.debit > Decimal('0.00') and not line.useful_life_months:
                warnings.append('Fixed asset cost lines should include useful life in months when known.')
            if line.credit > Decimal('0.00') and not (line.asset_identifier or line.reference or line.source_document_number):
                warnings.append('Accumulated depreciation lines should cite the related asset or depreciation worksheet.')
        if schedule.schedule_type == 'loans_payable':
            if not (line.source_document_number or line.reference):
                warnings.append('Loan schedule should cite loan agreement, statement, or amortization reference.')
            if not line.maturity_date:
                warnings.append('Loan schedule should include maturity date when known.')
        if schedule.schedule_type == 'equity_balance' and not (
            line.source_document_number or line.reference or line.notes
        ):
            warnings.append('Equity schedule should cite capital, retained earnings, or owner equity support.')
        if warnings:
            line.validation_status = 'warning'
            line.validation_message = ' '.join(warnings)
            line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])
        else:
            line.validation_status = 'valid'
            line.validation_message = ''
            line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])

    schedule = refresh_cutover_balance_schedule(schedule)
    rows = build_cutover_balance_schedule_reconciliation(schedule)
    row_errors = [
        f"{row['account_code']} {row['account_name']}: {row['status']}"
        for row in rows
        if row['status'] != 'matched'
    ]
    if not lines:
        errors.append('Schedule needs at least one detail line.')
    errors.extend(row_errors)
    schedule.validation_errors = '\n'.join(errors)
    schedule.status = 'reconciled' if not errors else 'needs_review'
    schedule.save(update_fields=['status', 'validation_errors', 'updated_at'])
    return schedule


def build_cutover_balance_schedule_summary(plan):
    summaries = []
    if not plan:
        return summaries
    for item in available_cutover_balance_schedule_types():
        schedule = get_active_cutover_balance_schedule(plan, item['key'])
        if schedule:
            refresh_cutover_balance_schedule(schedule)
            rows = build_cutover_balance_schedule_reconciliation(schedule)
        else:
            config = get_cutover_balance_schedule_config(item['key'])
            opening_qs = OpeningBalanceLine.objects.filter(
                import_batch__cutover_plan=plan,
                import_batch__status__in=['validated', 'journal_created', 'posted'],
            ).filter(
                Q(line_type__in=config['opening_line_types'])
                | Q(account__code__in=config['account_codes'])
            )
            opening_totals = opening_qs.aggregate(debit_total=Sum('debit'), credit_total=Sum('credit'))
            rows = []
            opening_debit = opening_totals['debit_total'] or Decimal('0.00')
            opening_credit = opening_totals['credit_total'] or Decimal('0.00')
            opening_net = opening_debit - opening_credit
            summaries.append({
                'key': item['key'],
                'label': item['label'],
                'schedule': None,
                'status': 'missing' if opening_debit or opening_credit else 'not_needed',
                'required': bool(opening_debit or opening_credit),
                'line_count': 0,
                'total_debit': Decimal('0.00'),
                'total_credit': Decimal('0.00'),
                'schedule_net': Decimal('0.00'),
                'opening_total_debit': opening_debit,
                'opening_total_credit': opening_credit,
                'opening_net': opening_net,
                'difference': Decimal('0.00') - opening_net,
                'rows': rows,
            })
            continue
        summaries.append({
            'key': item['key'],
            'label': item['label'],
            'schedule': schedule,
            'status': schedule.status,
            'required': True,
            'line_count': schedule.lines.count(),
            'total_debit': schedule.total_debit,
            'total_credit': schedule.total_credit,
            'schedule_net': schedule.total_debit - schedule.total_credit,
            'opening_total_debit': schedule.opening_total_debit,
            'opening_total_credit': schedule.opening_total_credit,
            'opening_net': schedule.opening_total_debit - schedule.opening_total_credit,
            'difference': schedule.difference,
            'rows': rows,
        })
    return summaries


def refresh_opening_balance_totals(import_batch):
    totals = import_batch.lines.aggregate(
        debit_total=Sum('debit'),
        credit_total=Sum('credit'),
    )
    import_batch.total_debit = totals['debit_total'] or Decimal('0.00')
    import_batch.total_credit = totals['credit_total'] or Decimal('0.00')
    import_batch.save(update_fields=['total_debit', 'total_credit', 'updated_at'])
    return import_batch


def _validation_message(exc):
    if hasattr(exc, 'messages'):
        return '; '.join(exc.messages)
    return str(exc)


@transaction.atomic
def validate_opening_balance_import(import_batch):
    import_batch = (
        OpeningBalanceImport.objects
        .select_for_update()
        .select_related('cutover_plan')
        .get(pk=import_batch.pk)
    )
    if import_batch.status in ('journal_created', 'posted', 'voided') or import_batch.journal_entry_id:
        raise ValidationError('Opening balance imports linked to a journal are read-only.')
    if import_batch.cutover_plan.status in CUTOVER_LOCKED_STATUSES:
        raise ValidationError('Approved or live cutover plans are locked.')
    refresh_opening_balance_totals(import_batch)
    errors = []
    lines = list(import_batch.lines.select_related('account', 'subscriber').order_by('id'))

    for line in lines:
        try:
            line.full_clean()
        except ValidationError as exc:
            message = _validation_message(exc)
            line.validation_status = 'error'
            line.validation_message = message
            line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])
            errors.append(f"Line {line.pk}: {message}")
            continue

        if not line.account.is_active:
            message = f"Account {line.account.code} is inactive."
            line.validation_status = 'error'
            line.validation_message = message
            line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])
            errors.append(f"Line {line.pk}: {message}")
            continue

        line.validation_status = 'valid'
        line.validation_message = ''
        line.save(update_fields=['validation_status', 'validation_message', 'updated_at'])

    if len(lines) < 2:
        errors.append('Opening balance import needs at least two lines.')
    if import_batch.total_debit != import_batch.total_credit:
        errors.append(
            f"Opening balance import is unbalanced by {import_batch.difference}."
        )

    import_batch.validation_errors = '\n'.join(errors)
    if errors:
        import_batch.status = 'draft'
    elif import_batch.journal_entry_id:
        import_batch.status = 'journal_created'
    else:
        import_batch.status = 'validated'
    import_batch.save(update_fields=[
        'status',
        'validation_errors',
        'total_debit',
        'total_credit',
        'updated_at',
    ])
    return import_batch


@transaction.atomic
def create_opening_balance_journal(import_batch, created_by=None):
    import_batch = (
        OpeningBalanceImport.objects
        .select_for_update()
        .select_related('cutover_plan')
        .get(pk=import_batch.pk)
    )
    if import_batch.status == 'voided':
        raise ValidationError('Voided opening balance imports cannot create journals.')
    if import_batch.cutover_plan.status in CUTOVER_LOCKED_STATUSES:
        raise ValidationError('Approved or live cutover plans are locked.')
    if import_batch.journal_entry_id:
        return import_batch.journal_entry

    import_batch = validate_opening_balance_import(import_batch)
    if import_batch.validation_errors or not import_batch.is_balanced:
        raise ValidationError('Opening balance import must be balanced and valid before journal creation.')

    entry_date = import_batch.cutover_plan.cutover_date
    period = find_period_for_date(import_batch.entity, entry_date)
    journal_entry = JournalEntry.objects.create(
        entity=import_batch.entity,
        period=period,
        entry_number=next_journal_entry_number(import_batch.entity, entry_date, prefix='OB'),
        entry_date=entry_date,
        description=f"Opening balances as of {entry_date}",
        reference=f"CUTOVER-{entry_date:%Y%m%d}",
        source_type='opening_balance',
        source_document_number=str(import_batch.pk),
        created_by=created_by,
    )
    lines = list(import_batch.lines.select_related('account').order_by('id'))
    for index, line in enumerate(lines, start=1):
        journal_line = JournalLine(
            journal_entry=journal_entry,
            account=line.account,
            line_number=index,
            description=line.description or line.reference or line.get_line_type_display(),
            debit=line.debit,
            credit=line.credit,
        )
        journal_line.full_clean()
        journal_line.save()

    import_batch.journal_entry = journal_entry
    import_batch.status = 'journal_created'
    import_batch.validation_errors = ''
    import_batch.save(update_fields=['journal_entry', 'status', 'validation_errors', 'updated_at'])
    return journal_entry


def _local_date(value):
    if not value:
        return None
    return timezone.localtime(value).date()


def _invoice_excluded_as_of(invoice, cutover_date):
    if invoice.status not in ('voided', 'waived'):
        return False
    voided_date = _local_date(invoice.voided_at)
    return not voided_date or voided_date <= cutover_date


def _subscriber_ar_source_map(cutover_date):
    balances = {}
    invoices = Invoice.objects.filter(
        created_at__date__lte=cutover_date,
    ).select_related('subscriber')
    included_count = 0
    for invoice in invoices:
        if _invoice_excluded_as_of(invoice, cutover_date):
            continue
        paid_as_of = (
            PaymentAllocation.objects
            .filter(
                invoice=invoice,
                created_at__date__lte=cutover_date,
                payment__paid_at__date__lte=cutover_date,
            )
            .aggregate(total=Sum('amount_allocated'))['total']
            or Decimal('0.00')
        )
        balance = max((invoice.amount or Decimal('0.00')) - paid_as_of, Decimal('0.00'))
        if balance <= Decimal('0.00'):
            continue
        included_count += 1
        item = balances.setdefault(invoice.subscriber_id, {
            'subscriber': invoice.subscriber,
            'source_balance': Decimal('0.00'),
            'source_count': 0,
            'source_references': [],
        })
        item['source_balance'] += balance
        item['source_count'] += 1
        item['source_references'].append(f"{invoice.invoice_number}: PHP {balance}")
    return balances, included_count


def _subscriber_ar_total_as_of(cutover_date):
    balances, _ = _subscriber_ar_source_map(cutover_date)
    return sum((item['source_balance'] for item in balances.values()), Decimal('0.00'))


def _customer_advance_source_map(cutover_date):
    from apps.subscribers.models import Subscriber


    balances = {}
    subscribers = (
        Subscriber.objects
        .filter(payments__paid_at__date__lte=cutover_date)
        .distinct()
        .order_by('username')
    )
    for subscriber in subscribers:
        payments = Payment.objects.filter(
            subscriber=subscriber,
            paid_at__date__lte=cutover_date,
        )
        payment_total = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        allocated_total = (
            PaymentAllocation.objects
            .filter(
                payment__subscriber=subscriber,
                payment__paid_at__date__lte=cutover_date,
                created_at__date__lte=cutover_date,
            )
            .aggregate(total=Sum('amount_allocated'))['total']
            or Decimal('0.00')
        )
        adjusted_total = (
            AccountCreditAdjustment.objects
            .filter(
                subscriber=subscriber,
                status__in=['pending', 'completed'],
                effective_at__date__lte=cutover_date,
            )
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0.00')
        )
        balance = max(payment_total - allocated_total - adjusted_total, Decimal('0.00'))
        if balance <= Decimal('0.00'):
            continue
        references = list(
            payments
            .exclude(reference='')
            .order_by('paid_at', 'id')
            .values_list('reference', flat=True)[:10]
        )
        balances[subscriber.pk] = {
            'subscriber': subscriber,
            'source_balance': balance,
            'source_count': payments.count(),
            'source_references': references,
        }
    return balances


def _customer_advance_total_as_of(cutover_date):
    balances = _customer_advance_source_map(cutover_date)
    return sum((item['source_balance'] for item in balances.values()), Decimal('0.00'))


def _opening_line_total(plan, line_types, account_codes=None):
    qs = OpeningBalanceLine.objects.filter(
        import_batch__cutover_plan=plan,
        import_batch__status__in=['validated', 'journal_created', 'posted'],
        line_type__in=line_types,
    )
    if account_codes:
        qs = qs.filter(account__code__in=account_codes)
    totals = qs.aggregate(debit_total=Sum('debit'), credit_total=Sum('credit'))
    return (totals['debit_total'] or Decimal('0.00')) - (totals['credit_total'] or Decimal('0.00'))


def _subscriber_opening_balance_map(plan, balance_type):
    if balance_type == 'subscriber_ar':
        qs = OpeningBalanceLine.objects.filter(
            Q(line_type='subscriber_ar') | Q(account__code='1100'),
            import_batch__cutover_plan=plan,
            import_batch__status__in=['validated', 'journal_created', 'posted'],
            subscriber__isnull=False,
        )
        sign = 'debit'
    elif balance_type == 'customer_advance':
        qs = OpeningBalanceLine.objects.filter(
            Q(line_type='customer_advance') | Q(account__code='2100'),
            import_batch__cutover_plan=plan,
            import_batch__status__in=['validated', 'journal_created', 'posted'],
            subscriber__isnull=False,
        )
        sign = 'credit'
    else:
        raise ValidationError(f"Unsupported subscriber opening balance type: {balance_type}.")

    balances = {}
    for line in qs.select_related('subscriber', 'account').order_by('subscriber__username', 'id'):
        item = balances.setdefault(line.subscriber_id, {
            'subscriber': line.subscriber,
            'opening_balance': Decimal('0.00'),
            'opening_line_count': 0,
        })
        if sign == 'debit':
            item['opening_balance'] += (line.debit or Decimal('0.00')) - (line.credit or Decimal('0.00'))
        else:
            item['opening_balance'] += (line.credit or Decimal('0.00')) - (line.debit or Decimal('0.00'))
        item['opening_line_count'] += 1
    return balances


def _reconciliation_line_status(source_balance, opening_balance):
    if source_balance == opening_balance:
        return 'matched'
    if source_balance > Decimal('0.00') and opening_balance == Decimal('0.00'):
        return 'missing_opening'
    if source_balance == Decimal('0.00') and opening_balance > Decimal('0.00'):
        return 'missing_source'
    return 'difference'


def _snapshot_subscriber_lines(snapshot, source_map, opening_map, balance_type):
    subscriber_ids = sorted(
        set(source_map.keys()) | set(opening_map.keys()),
        key=lambda value: (
            (source_map.get(value) or opening_map.get(value))['subscriber'].username,
            value,
        ),
    )
    line_objects = []
    for subscriber_id in subscriber_ids:
        source = source_map.get(subscriber_id, {})
        opening = opening_map.get(subscriber_id, {})
        subscriber = source.get('subscriber') or opening.get('subscriber')
        source_balance = source.get('source_balance', Decimal('0.00'))
        opening_balance = opening.get('opening_balance', Decimal('0.00'))
        difference = source_balance - opening_balance
        source_refs = source.get('source_references', [])
        line_objects.append(CutoverSubscriberBalanceLine(
            snapshot=snapshot,
            entity=snapshot.entity,
            subscriber=subscriber,
            balance_type=balance_type,
            source_balance=source_balance,
            opening_balance=opening_balance,
            difference=difference,
            source_count=source.get('source_count', 0),
            opening_line_count=opening.get('opening_line_count', 0),
            source_references='\n'.join(source_refs),
            status=_reconciliation_line_status(source_balance, opening_balance),
        ))
    CutoverSubscriberBalanceLine.objects.bulk_create(line_objects)
    return line_objects


def get_latest_cutover_reconciliation_snapshot(plan):
    if not plan:
        return None
    return (
        CutoverReconciliationSnapshot.objects
        .filter(cutover_plan=plan)
        .exclude(status='voided')
        .order_by('-generated_at', '-id')
        .first()
    )


@transaction.atomic
def generate_cutover_reconciliation_snapshot(plan, generated_by=None, notes=''):
    plan = CutoverPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status == 'voided':
        raise ValidationError('Voided cutover plans cannot generate reconciliation snapshots.')

    ar_source_map, invoice_count = _subscriber_ar_source_map(plan.cutover_date)
    advance_source_map = _customer_advance_source_map(plan.cutover_date)
    ar_opening_map = _subscriber_opening_balance_map(plan, 'subscriber_ar')
    advance_opening_map = _subscriber_opening_balance_map(plan, 'customer_advance')

    snapshot = CutoverReconciliationSnapshot.objects.create(
        entity=plan.entity,
        cutover_plan=plan,
        status='generated',
        source_invoice_count=invoice_count,
        source_credit_subscriber_count=len(advance_source_map),
        generated_by=generated_by,
        notes=notes,
    )
    ar_lines = _snapshot_subscriber_lines(snapshot, ar_source_map, ar_opening_map, 'subscriber_ar')
    advance_lines = _snapshot_subscriber_lines(snapshot, advance_source_map, advance_opening_map, 'customer_advance')

    snapshot.ar_source_total = sum((line.source_balance for line in ar_lines), Decimal('0.00'))
    snapshot.ar_opening_total = sum((line.opening_balance for line in ar_lines), Decimal('0.00'))
    snapshot.ar_difference = snapshot.ar_source_total - snapshot.ar_opening_total
    snapshot.advance_source_total = sum((line.source_balance for line in advance_lines), Decimal('0.00'))
    snapshot.advance_opening_total = sum((line.opening_balance for line in advance_lines), Decimal('0.00'))
    snapshot.advance_difference = snapshot.advance_source_total - snapshot.advance_opening_total
    if (
        snapshot.ar_difference == Decimal('0.00')
        and snapshot.advance_difference == Decimal('0.00')
        and all(line.status == 'matched' for line in [*ar_lines, *advance_lines])
    ):
        snapshot.status = 'reconciled'
    snapshot.full_clean()
    snapshot.save(update_fields=[
        'status',
        'ar_source_total',
        'ar_opening_total',
        'ar_difference',
        'advance_source_total',
        'advance_opening_total',
        'advance_difference',
        'updated_at',
    ])
    return snapshot


def build_cutover_readiness(entity):
    checks = []

    def add(key, label, passed, detail='', severity='error'):
        checks.append({
            'key': key,
            'label': label,
            'passed': bool(passed),
            'detail': detail,
            'severity': severity,
        })

    add('entity', 'Active accounting entity exists', bool(entity), str(entity) if entity else 'Run Accounting v2 setup first.')
    if not entity:
        return {'checks': checks, 'all_passed': False, 'plan': None}

    account_count = ChartOfAccount.objects.filter(entity=entity, is_active=True).count()
    add('coa', 'Active chart of accounts exists', account_count > 0, f"{account_count} active account(s).")

    plan = get_active_cutover_plan(entity)
    add('cutover_plan', 'Cutover plan exists', bool(plan), str(plan) if plan else 'Create a cutover plan.')
    if not plan:
        return {'checks': checks, 'all_passed': False, 'plan': None}

    period = AccountingPeriod.objects.filter(
        entity=entity,
        start_date__lte=plan.cutover_date,
        end_date__gte=plan.cutover_date,
    ).first()
    add('period', 'Accounting period covers cutover date', bool(period), period.name if period else str(plan.cutover_date))

    imports = OpeningBalanceImport.objects.filter(cutover_plan=plan)
    add('opening_import', 'Opening balance import exists', imports.exists(), f"{imports.count()} import batch(es).")

    balanced_import = imports.filter(
        status__in=['validated', 'journal_created', 'posted'],
        total_debit=F('total_credit'),
    ).first()
    add(
        'balanced_import',
        'Opening balance import is balanced',
        bool(balanced_import),
        f"Debit {balanced_import.total_debit} / Credit {balanced_import.total_credit}" if balanced_import else 'Validate a balanced import.',
    )

    opening_journal = (
        JournalEntry.objects
        .filter(entity=entity, source_type='opening_balance', entry_date=plan.cutover_date)
        .order_by('-created_at')
        .first()
    )
    add(
        'opening_journal',
        'Opening journal draft exists',
        bool(opening_journal),
        opening_journal.entry_number if opening_journal else 'Create the opening journal from a balanced import.',
    )
    add(
        'opening_journal_balanced',
        'Opening journal is balanced',
        bool(opening_journal and opening_journal.is_balanced()),
        opening_journal.get_status_display() if opening_journal else 'No opening journal yet.',
    )
    add(
        'opening_journal_posted',
        'Opening journal is posted',
        bool(opening_journal and opening_journal.status == 'posted'),
        opening_journal.get_status_display() if opening_journal else 'No opening journal yet.',
    )

    inactive_lines = OpeningBalanceLine.objects.filter(import_batch__cutover_plan=plan, account__is_active=False).count()
    add('active_accounts', 'Opening lines use active accounts', inactive_lines == 0, f"{inactive_lines} inactive-account line(s).")

    open_ar_total = _subscriber_ar_total_as_of(plan.cutover_date)
    opening_ar_total = _opening_line_total(plan, ['subscriber_ar', 'gl_control'], ['1100'])
    add(
        'subscriber_ar_present',
        'Subscriber AR opening line is present when open invoices exist',
        open_ar_total == Decimal('0.00') or opening_ar_total > Decimal('0.00'),
        f"Open billing AR {open_ar_total}; opening AR {opening_ar_total}.",
        severity='warning',
    )

    customer_advance_total = _customer_advance_total_as_of(plan.cutover_date)
    opening_advance_total = abs(_opening_line_total(plan, ['customer_advance', 'gl_control'], ['2100']))
    add(
        'customer_advances_present',
        'Customer advance opening line is present when credits exist',
        customer_advance_total == Decimal('0.00') or opening_advance_total > Decimal('0.00'),
        f"Current customer credits {customer_advance_total}; opening advances {opening_advance_total}.",
        severity='warning',
    )

    latest_snapshot = get_latest_cutover_reconciliation_snapshot(plan)
    has_reconciliation_basis = any([
        open_ar_total > Decimal('0.00'),
        opening_ar_total > Decimal('0.00'),
        customer_advance_total > Decimal('0.00'),
        opening_advance_total > Decimal('0.00'),
    ])
    add(
        'subscriber_reconciliation_snapshot',
        'Subscriber AR and advance reconciliation snapshot exists',
        not has_reconciliation_basis or bool(latest_snapshot),
        latest_snapshot.generated_at if latest_snapshot else 'Generate a Slice 2B reconciliation snapshot.',
    )
    if latest_snapshot:
        line_difference_count = latest_snapshot.subscriber_lines.exclude(status='matched').count()
        add(
            'subscriber_ar_reconciled',
            'Subscriber AR source total matches opening subscriber AR',
            latest_snapshot.ar_difference == Decimal('0.00'),
            f"Source {latest_snapshot.ar_source_total}; opening {latest_snapshot.ar_opening_total}; difference {latest_snapshot.ar_difference}.",
        )
        add(
            'customer_advances_reconciled',
            'Customer advance source total matches opening customer advances',
            latest_snapshot.advance_difference == Decimal('0.00'),
            f"Source {latest_snapshot.advance_source_total}; opening {latest_snapshot.advance_opening_total}; difference {latest_snapshot.advance_difference}.",
        )
        add(
            'subscriber_reconciliation_lines_matched',
            'Every subscriber reconciliation line is matched',
            line_difference_count == 0,
            f"{line_difference_count} subscriber line(s) need review.",
        )

    balance_schedule_summary = build_cutover_balance_schedule_summary(plan)
    for schedule_item in balance_schedule_summary:
        if not schedule_item['required']:
            continue
        add(
            f"cutover_balance_schedule_{schedule_item['key']}",
            f"{schedule_item['label']} schedule is reconciled",
            schedule_item['status'] == 'reconciled' and schedule_item['difference'] == Decimal('0.00'),
            (
                f"Schedule net {schedule_item['total_debit'] - schedule_item['total_credit']}; "
                f"opening net {schedule_item['opening_total_debit'] - schedule_item['opening_total_credit']}; "
                f"difference {schedule_item['difference']}."
            ),
        )

    blocked_source_count = AccountingSourcePosting.objects.filter(
        Q(entity=entity) | Q(entity__isnull=True),
        status='blocked',
    ).count()
    try:
        settings_status = entity.settings.setup_status
    except AccountingSettings.DoesNotExist:
        settings_status = ''
    if plan.status == 'live' or settings_status == 'live':
        add(
            'post_cutover_blocked_source_postings',
            'No blocked source postings after cutover live',
            blocked_source_count == 0,
            f"{blocked_source_count} blocked source posting(s).",
            severity='warning',
        )

    all_passed = all(item['passed'] for item in checks if item['severity'] == 'error')
    return {
        'checks': checks,
        'all_passed': all_passed,
        'plan': plan,
        'opening_journal': opening_journal,
        'open_ar_total': open_ar_total,
        'customer_advance_total': customer_advance_total,
        'reconciliation_snapshot': latest_snapshot,
        'balance_schedule_summary': balance_schedule_summary,
        'blocked_source_count': blocked_source_count,
        'can_mark_ready': all_passed and plan.status in ('draft', 'reconciling'),
        'can_approve': all_passed and plan.status == 'ready_for_review',
        'can_go_live': all_passed and plan.status == 'approved',
    }


def _readiness_failure_message(readiness):
    failures = [
        item['label']
        for item in readiness['checks']
        if item['severity'] == 'error' and not item['passed']
    ]
    if not failures:
        return ''
    return 'Cutover is not ready: ' + '; '.join(failures[:5])


@transaction.atomic
def mark_cutover_ready(plan, reviewed_by=None):
    plan = CutoverPlan.objects.select_for_update().select_related('entity').get(pk=plan.pk)
    if plan.status == 'voided':
        raise ValidationError('Voided cutover plans cannot be marked ready.')
    if plan.status == 'live':
        raise ValidationError('Live cutover plans are already locked.')
    readiness = build_cutover_readiness(plan.entity)
    failure_message = _readiness_failure_message(readiness)
    if failure_message:
        raise ValidationError(failure_message)
    if plan.status == 'approved':
        return plan
    plan.status = 'ready_for_review'
    plan.reviewed_by = reviewed_by or plan.reviewed_by
    plan.full_clean()
    plan.save(update_fields=['status', 'reviewed_by', 'updated_at'])
    return plan


@transaction.atomic
def approve_cutover_plan(plan, approved_by=None):
    plan = CutoverPlan.objects.select_for_update().select_related('entity').get(pk=plan.pk)
    if plan.status == 'voided':
        raise ValidationError('Voided cutover plans cannot be approved.')
    if plan.status == 'live':
        raise ValidationError('Live cutover plans are already locked.')
    if plan.status != 'ready_for_review':
        raise ValidationError('Cutover plan must be ready for review before approval.')
    readiness = build_cutover_readiness(plan.entity)
    failure_message = _readiness_failure_message(readiness)
    if failure_message:
        raise ValidationError(failure_message)
    plan.status = 'approved'
    plan.reviewed_by = plan.reviewed_by or approved_by
    plan.approved_by = approved_by or plan.approved_by
    plan.approved_at = timezone.now()
    plan.full_clean()
    plan.save(update_fields=['status', 'reviewed_by', 'approved_by', 'approved_at', 'updated_at'])
    return plan


@transaction.atomic
def mark_accounting_live(plan, live_by=None):
    plan = CutoverPlan.objects.select_for_update().select_related('entity').get(pk=plan.pk)
    if plan.status == 'voided':
        raise ValidationError('Voided cutover plans cannot be moved live.')
    if plan.status == 'live':
        return plan
    if plan.status != 'approved':
        raise ValidationError('Cutover plan must be approved before going live.')
    readiness = build_cutover_readiness(plan.entity)
    failure_message = _readiness_failure_message(readiness)
    if failure_message:
        raise ValidationError(failure_message)
    opening_journal = readiness.get('opening_journal')
    if not opening_journal or opening_journal.status != 'posted':
        raise ValidationError('Opening journal must be posted before Accounting v2 goes live.')

    plan.status = 'live'
    plan.approved_by = plan.approved_by or live_by
    plan.approved_at = plan.approved_at or timezone.now()
    plan.live_at = timezone.now()
    plan.full_clean()
    plan.save(update_fields=['status', 'approved_by', 'approved_at', 'live_at', 'updated_at'])

    AccountingSettings.objects.update_or_create(
        entity=plan.entity,
        defaults={'setup_status': 'live'},
    )
    OpeningBalanceImport.objects.filter(
        cutover_plan=plan,
        journal_entry=opening_journal,
    ).update(status='posted')
    return plan


def _posted_line_criteria(entity, start_date=None, end_date=None, include_closing_entries=True):
    criteria = Q(
        journal_lines__journal_entry__entity=entity,
        journal_lines__journal_entry__status='posted',
    )
    if not include_closing_entries:
        criteria &= ~Q(journal_lines__journal_entry__source_type='closing')
    if start_date:
        criteria &= Q(journal_lines__journal_entry__entry_date__gte=start_date)
    if end_date:
        criteria &= Q(journal_lines__journal_entry__entry_date__lte=end_date)
    return criteria


def _line_queryset(entity, start_date=None, end_date=None, include_closing_entries=True):
    qs = (
        JournalLine.objects
        .filter(
            journal_entry__entity=entity,
            journal_entry__status='posted',
        )
        .select_related('journal_entry', 'account')
    )
    if not include_closing_entries:
        qs = qs.exclude(journal_entry__source_type='closing')
    if start_date:
        qs = qs.filter(journal_entry__entry_date__gte=start_date)
    if end_date:
        qs = qs.filter(journal_entry__entry_date__lte=end_date)
    return qs


def _statement_balance(account, debit, credit):
    debit = debit or Decimal('0.00')
    credit = credit or Decimal('0.00')
    if account.account_type in ('asset', 'direct_cost', 'expense', 'other_expense'):
        return debit - credit
    return credit - debit


def _account_activity_rows(
    entity,
    start_date=None,
    end_date=None,
    account_types=None,
    include_zero=False,
    include_closing_entries=True,
):
    line_filter = _posted_line_criteria(
        entity,
        start_date=start_date,
        end_date=end_date,
        include_closing_entries=include_closing_entries,
    )
    accounts = ChartOfAccount.objects.filter(entity=entity, is_active=True)
    if account_types:
        accounts = accounts.filter(account_type__in=account_types)
    accounts = accounts.annotate(
        debit_total=Sum('journal_lines__debit', filter=line_filter),
        credit_total=Sum('journal_lines__credit', filter=line_filter),
    ).order_by('code')

    rows = []
    for account in accounts:
        debit = account.debit_total or Decimal('0.00')
        credit = account.credit_total or Decimal('0.00')
        if not include_zero and debit == Decimal('0.00') and credit == Decimal('0.00'):
            continue
        rows.append({
            'account': account,
            'debit': debit,
            'credit': credit,
            'balance': _statement_balance(account, debit, credit),
        })
    return rows


def _account_balance_as_of(account, as_of_date=None):
    qs = JournalLine.objects.filter(
        account=account,
        journal_entry__entity=account.entity,
        journal_entry__status='posted',
    )
    if as_of_date:
        qs = qs.filter(journal_entry__entry_date__lte=as_of_date)
    totals = qs.aggregate(debit_total=Sum('debit'), credit_total=Sum('credit'))
    return _statement_balance(
        account,
        totals['debit_total'] or Decimal('0.00'),
        totals['credit_total'] or Decimal('0.00'),
    )


def _account_activity_balance(account, start_date=None, end_date=None, include_closing_entries=True):
    qs = JournalLine.objects.filter(
        account=account,
        journal_entry__entity=account.entity,
        journal_entry__status='posted',
    )
    if not include_closing_entries:
        qs = qs.exclude(journal_entry__source_type='closing')
    if start_date:
        qs = qs.filter(journal_entry__entry_date__gte=start_date)
    if end_date:
        qs = qs.filter(journal_entry__entry_date__lte=end_date)
    totals = qs.aggregate(debit_total=Sum('debit'), credit_total=Sum('credit'))
    debit = totals['debit_total'] or Decimal('0.00')
    credit = totals['credit_total'] or Decimal('0.00')
    return {
        'debit': debit,
        'credit': credit,
        'balance': _statement_balance(account, debit, credit),
    }


def _aging_bucket(days_overdue):
    if days_overdue <= 0:
        return 'current'
    if days_overdue <= 30:
        return '1_30'
    if days_overdue <= 60:
        return '31_60'
    if days_overdue <= 90:
        return '61_90'
    return 'over_90'


def _empty_aging_totals():
    return {
        'current': Decimal('0.00'),
        '1_30': Decimal('0.00'),
        '31_60': Decimal('0.00'),
        '61_90': Decimal('0.00'),
        'over_90': Decimal('0.00'),
    }


def _bucket_labels():
    return {
        'current': 'Current',
        '1_30': '1-30 Days',
        '31_60': '31-60 Days',
        '61_90': '61-90 Days',
        'over_90': 'Over 90 Days',
    }


def _bucket_total_rows(totals):
    labels = _bucket_labels()
    return [
        {'key': key, 'label': labels[key], 'amount': totals[key]}
        for key in ('current', '1_30', '31_60', '61_90', 'over_90')
    ]


def _account_balance_for_code(entity, code, as_of_date=None):
    account = ChartOfAccount.objects.filter(entity=entity, code=code).first()
    if not account:
        return None, Decimal('0.00')
    return account, _account_balance_as_of(account, as_of_date)


def build_trial_balance_report(entity, start_date=None, end_date=None, include_zero=False):
    rows = _account_activity_rows(
        entity,
        start_date=start_date,
        end_date=end_date,
        include_zero=include_zero,
    )
    total_debit = sum((row['debit'] for row in rows), Decimal('0.00'))
    total_credit = sum((row['credit'] for row in rows), Decimal('0.00'))
    return {
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'is_balanced': total_debit == total_credit,
        'start_date': start_date,
        'end_date': end_date,
    }


def _unclosed_income_start_date(entity, as_of_date=None):
    closed_periods = AccountingPeriod.objects.filter(
        entity=entity,
        status__in=['closed', 'locked'],
    )
    if as_of_date:
        closed_periods = closed_periods.filter(end_date__lte=as_of_date)
    last_closed_end = (
        closed_periods
        .order_by('-end_date')
        .values_list('end_date', flat=True)
        .first()
    )
    if not last_closed_end:
        return None
    return last_closed_end + timedelta(days=1)


def build_income_statement_report(entity, start_date=None, end_date=None):
    rows = _account_activity_rows(
        entity,
        start_date=start_date,
        end_date=end_date,
        account_types=TEMPORARY_ACCOUNT_TYPES,
        include_closing_entries=False,
    )
    sections = {
        'revenue': [],
        'direct_cost': [],
        'expense': [],
        'other_income': [],
        'other_expense': [],
    }
    for row in rows:
        sections[row['account'].account_type].append(row)

    totals = {
        key: sum((row['balance'] for row in value), Decimal('0.00'))
        for key, value in sections.items()
    }
    gross_profit = totals['revenue'] - totals['direct_cost']
    operating_income = gross_profit - totals['expense']
    net_income = operating_income + totals['other_income'] - totals['other_expense']
    return {
        'sections': sections,
        'totals': totals,
        'gross_profit': gross_profit,
        'operating_income': operating_income,
        'net_income': net_income,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_balance_sheet_report(entity, as_of_date=None):
    balance_rows = _account_activity_rows(
        entity,
        end_date=as_of_date,
        account_types=['asset', 'liability', 'equity'],
    )
    sections = {
        'asset': [],
        'liability': [],
        'equity': [],
    }
    for row in balance_rows:
        sections[row['account'].account_type].append(row)

    income_start_date = _unclosed_income_start_date(entity, as_of_date)
    if as_of_date and income_start_date and income_start_date > as_of_date:
        current_earnings = Decimal('0.00')
    else:
        income_report = build_income_statement_report(
            entity,
            start_date=income_start_date,
            end_date=as_of_date,
        )
        current_earnings = income_report['net_income']
    if current_earnings != Decimal('0.00'):
        sections['equity'].append({
            'account': None,
            'label': 'Unclosed Current Earnings',
            'debit': Decimal('0.00'),
            'credit': Decimal('0.00'),
            'balance': current_earnings,
        })

    totals = {
        key: sum((row['balance'] for row in value), Decimal('0.00'))
        for key, value in sections.items()
    }
    total_liabilities_equity = totals['liability'] + totals['equity']
    difference = totals['asset'] - total_liabilities_equity
    return {
        'sections': sections,
        'totals': totals,
        'total_liabilities_equity': total_liabilities_equity,
        'difference': difference,
        'is_balanced': difference == Decimal('0.00'),
        'as_of_date': as_of_date,
        'current_earnings': current_earnings,
        'uses_unclosed_current_earnings': current_earnings != Decimal('0.00'),
    }


def _cash_flow_section_for_lines(lines):
    if not lines:
        return 'transfer'
    for line in lines:
        account = line.account
        if account.account_type == 'equity' or account.code == '2400':
            return 'financing'
    for line in lines:
        account = line.account
        name = account.name.lower()
        if account.account_type == 'asset' and (
            account.code.startswith('15')
            or 'equipment' in name
            or 'facilities' in name
            or 'fixed asset' in name
        ):
            return 'investing'
    return 'operating'


def build_cash_flow_report(entity, start_date=None, end_date=None):
    day_before_start = start_date - timedelta(days=1) if start_date else None
    cash_accounts = list(
        ChartOfAccount.objects
        .filter(entity=entity, is_active=True, code__in=CASH_EQUIVALENT_ACCOUNT_CODES)
        .order_by('code')
    )
    cash_account_ids = {account.pk for account in cash_accounts}
    cash_account_rows = []
    for account in cash_accounts:
        opening_balance = _account_balance_as_of(account, day_before_start)
        closing_balance = _account_balance_as_of(account, end_date)
        cash_account_rows.append({
            'account': account,
            'opening_balance': opening_balance,
            'closing_balance': closing_balance,
            'movement': closing_balance - opening_balance,
        })

    entries = (
        JournalEntry.objects
        .filter(
            entity=entity,
            status='posted',
            lines__account_id__in=cash_account_ids,
        )
        .prefetch_related('lines__account')
        .distinct()
        .order_by('entry_date', 'entry_number', 'id')
    )
    if start_date:
        entries = entries.filter(entry_date__gte=start_date)
    if end_date:
        entries = entries.filter(entry_date__lte=end_date)

    sections = {
        'operating': [],
        'investing': [],
        'financing': [],
    }
    transfer_rows = []
    for entry in entries:
        lines = list(entry.lines.all())
        cash_lines = [line for line in lines if line.account_id in cash_account_ids]
        cash_movement = sum((
            _statement_balance(line.account, line.debit, line.credit)
            for line in cash_lines
        ), Decimal('0.00'))
        if cash_movement == Decimal('0.00'):
            continue

        non_cash_lines = [line for line in lines if line.account_id not in cash_account_ids]
        section_key = _cash_flow_section_for_lines(non_cash_lines)
        row = {
            'journal_entry': entry,
            'entry_date': entry.entry_date,
            'entry_number': entry.entry_number,
            'description': entry.description,
            'counterparty': ', '.join(
                sorted({f'{line.account.code} {line.account.name}' for line in non_cash_lines})
            ) or 'Cash transfer',
            'amount': cash_movement,
            'section': section_key,
        }
        if section_key == 'transfer':
            transfer_rows.append(row)
        else:
            sections[section_key].append(row)

    totals = {
        key: sum((row['amount'] for row in value), Decimal('0.00'))
        for key, value in sections.items()
    }
    net_cash_change = sum(totals.values(), Decimal('0.00'))
    opening_cash = sum((row['opening_balance'] for row in cash_account_rows), Decimal('0.00'))
    closing_cash = sum((row['closing_balance'] for row in cash_account_rows), Decimal('0.00'))
    return {
        'sections': sections,
        'totals': totals,
        'transfer_rows': transfer_rows,
        'cash_accounts': cash_account_rows,
        'opening_cash': opening_cash,
        'net_cash_change': net_cash_change,
        'closing_cash': closing_cash,
        'recomputed_closing_cash': opening_cash + net_cash_change,
        'difference': closing_cash - (opening_cash + net_cash_change),
        'start_date': start_date,
        'end_date': end_date,
    }


def build_changes_in_equity_report(entity, start_date=None, end_date=None):
    day_before_start = start_date - timedelta(days=1) if start_date else None
    accounts = (
        ChartOfAccount.objects
        .filter(entity=entity, is_active=True, account_type='equity')
        .order_by('code')
    )
    rows = []
    for account in accounts:
        opening_balance = _account_balance_as_of(account, day_before_start)
        activity = _account_activity_balance(account, start_date=start_date, end_date=end_date)
        movement = activity['balance']
        ending_balance = opening_balance + movement
        if opening_balance == Decimal('0.00') and movement == Decimal('0.00') and ending_balance == Decimal('0.00'):
            continue
        rows.append({
            'account': account,
            'opening_balance': opening_balance,
            'movement': movement,
            'ending_balance': ending_balance,
        })

    prior_income = Decimal('0.00')
    if day_before_start:
        prior_income_start = _unclosed_income_start_date(entity, day_before_start)
        if not prior_income_start or prior_income_start <= day_before_start:
            prior_income = build_income_statement_report(
                entity,
                start_date=prior_income_start,
                end_date=day_before_start,
            )['net_income']
    period_income = build_income_statement_report(
        entity,
        start_date=start_date,
        end_date=end_date,
    )['net_income']
    closing_entry_movement = sum((
        _statement_balance(line.account, line.debit, line.credit)
        for line in _line_queryset(entity, start_date=start_date, end_date=end_date)
        .filter(account__account_type='equity', journal_entry__source_type='closing')
    ), Decimal('0.00'))
    closing_entry_adjustment = -closing_entry_movement
    opening_equity = sum((row['opening_balance'] for row in rows), Decimal('0.00')) + prior_income
    equity_account_movement = sum((row['movement'] for row in rows), Decimal('0.00'))
    total_period_change = equity_account_movement + period_income + closing_entry_adjustment
    ending_equity = opening_equity + total_period_change
    balance_sheet = build_balance_sheet_report(entity, as_of_date=end_date)

    return {
        'rows': rows,
        'prior_unclosed_earnings': prior_income,
        'period_net_income': period_income,
        'closing_entry_movement': closing_entry_movement,
        'closing_entry_adjustment': closing_entry_adjustment,
        'opening_equity': opening_equity,
        'equity_account_movement': equity_account_movement,
        'total_period_change': total_period_change,
        'ending_equity': ending_equity,
        'balance_sheet_equity': balance_sheet['totals']['equity'],
        'difference': ending_equity - balance_sheet['totals']['equity'],
        'start_date': start_date,
        'end_date': end_date,
    }


def build_ar_aging_report(entity, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    totals = _empty_aging_totals()
    rows = []
    invoices = (
        Invoice.objects
        .select_related('subscriber')
        .exclude(status__in=['paid', 'voided', 'waived'])
        .order_by('subscriber__username', 'due_date', 'invoice_number')
    )
    for invoice in invoices:
        balance = max(_decimal_amount(invoice.remaining_balance), Decimal('0.00'))
        if balance <= Decimal('0.00'):
            continue
        days_overdue = max((as_of_date - invoice.due_date).days, 0)
        bucket = _aging_bucket(days_overdue)
        totals[bucket] += balance
        rows.append({
            'subscriber': invoice.subscriber,
            'invoice': invoice,
            'invoice_number': invoice.invoice_number,
            'due_date': invoice.due_date,
            'status': invoice.get_status_display(),
            'balance': balance,
            'days_overdue': days_overdue,
            'bucket': bucket,
            'bucket_label': _bucket_labels()[bucket],
        })

    total = sum(totals.values(), Decimal('0.00'))
    control_account, control_balance = _account_balance_for_code(entity, AR_CONTROL_ACCOUNT_CODE, as_of_date)
    return {
        'rows': rows,
        'totals': totals,
        'bucket_totals': _bucket_total_rows(totals),
        'total': total,
        'bucket_labels': _bucket_labels(),
        'control_account': control_account,
        'control_balance': control_balance,
        'control_difference': control_balance - total,
        'as_of_date': as_of_date,
        'source_note': 'Subscriber invoice aging is based on current unpaid invoice balances as of the selected date.',
    }


def _ap_amount_from_line(line):
    return max((line.credit or Decimal('0.00')) - (line.debit or Decimal('0.00')), Decimal('0.00'))


def build_ap_aging_report(entity, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    totals = _empty_aging_totals()
    rows = []
    schedule_lines = (
        CutoverBalanceScheduleLine.objects
        .filter(
            entity=entity,
            schedule__schedule_type='accounts_payable',
        )
        .exclude(schedule__status='voided')
        .select_related('account', 'schedule')
        .order_by('counterparty_name', 'statement_date', 'source_document_number', 'id')
    )
    if schedule_lines.exists():
        for line in schedule_lines:
            reference_date = line.maturity_date or line.statement_date or as_of_date
            if reference_date and reference_date > as_of_date:
                bucket = 'current'
                days_overdue = 0
            else:
                days_overdue = max((as_of_date - reference_date).days, 0)
                bucket = _aging_bucket(days_overdue)
            amount = _ap_amount_from_line(line)
            if amount <= Decimal('0.00'):
                continue
            totals[bucket] += amount
            rows.append({
                'vendor_name': line.counterparty_name or line.label,
                'reference': line.source_document_number or line.reference,
                'document_date': line.statement_date,
                'due_date': reference_date,
                'account': line.account,
                'amount': amount,
                'days_overdue': days_overdue,
                'bucket': bucket,
                'bucket_label': _bucket_labels()[bucket],
                'source': 'Cutover AP schedule',
            })
    else:
        opening_lines = (
            OpeningBalanceLine.objects
            .filter(
                entity=entity,
                line_type='ap_vendor',
                import_batch__status__in=['validated', 'journal_created', 'posted'],
            )
            .select_related('account', 'import_batch')
            .order_by('vendor_name', 'reference', 'id')
        )
        for line in opening_lines:
            amount = _ap_amount_from_line(line)
            if amount <= Decimal('0.00'):
                continue
            totals['current'] += amount
            rows.append({
                'vendor_name': line.vendor_name,
                'reference': line.reference,
                'document_date': None,
                'due_date': as_of_date,
                'account': line.account,
                'amount': amount,
                'days_overdue': 0,
                'bucket': 'current',
                'bucket_label': _bucket_labels()['current'],
                'source': 'Opening AP vendor line',
            })

    total = sum(totals.values(), Decimal('0.00'))
    control_account, control_balance = _account_balance_for_code(entity, AP_CONTROL_ACCOUNT_CODE, as_of_date)
    return {
        'rows': rows,
        'totals': totals,
        'bucket_totals': _bucket_total_rows(totals),
        'total': total,
        'bucket_labels': _bucket_labels(),
        'control_account': control_account,
        'control_balance': control_balance,
        'control_difference': control_balance - total,
        'as_of_date': as_of_date,
        'source_note': 'AP aging uses cutover AP schedule lines when present, otherwise validated opening AP vendor lines.',
    }


def build_tax_ledger_report(entity, start_date=None, end_date=None):
    day_before_start = start_date - timedelta(days=1) if start_date else None
    accounts = (
        ChartOfAccount.objects
        .filter(entity=entity, is_active=True, code__in=TAX_LEDGER_ACCOUNT_CODES)
        .order_by('code')
    )
    rows = []
    for account in accounts:
        activity = _account_activity_balance(account, start_date=start_date, end_date=end_date)
        opening_balance = _account_balance_as_of(account, day_before_start)
        ending_balance = _account_balance_as_of(account, end_date)
        rows.append({
            'account': account,
            'opening_balance': opening_balance,
            'debit': activity['debit'],
            'credit': activity['credit'],
            'movement': activity['balance'],
            'ending_balance': ending_balance,
        })

    balances_by_code = {row['account'].code: row['ending_balance'] for row in rows}
    input_vat = balances_by_code.get('1200', Decimal('0.00'))
    output_vat = balances_by_code.get('2300', Decimal('0.00'))
    vat_payable = balances_by_code.get('2320', Decimal('0.00'))
    cwt_receivable = balances_by_code.get('1210', Decimal('0.00'))
    percentage_tax_payable = balances_by_code.get('2330', Decimal('0.00'))

    claims = CustomerWithholdingTaxClaim.objects.filter(Q(entity=entity) | Q(entity__isnull=True))
    claim_rows = []
    claim_status_totals = {}
    for claim in claims.select_related('subscriber', 'withholding_class', 'atc_code'):
        claim_date = claim.received_date or claim.certificate_date or claim.period_to or claim.created_at.date()
        if start_date and claim_date < start_date:
            continue
        if end_date and claim_date > end_date:
            continue
        claim_rows.append({
            'claim': claim,
            'claim_date': claim_date,
            'subscriber': claim.subscriber,
            'payor_name': claim.payor_name,
            'atc': claim.atc or (claim.atc_code.code if claim.atc_code else ''),
            'gross_amount': claim.gross_amount,
            'tax_withheld': claim.tax_withheld,
            'status': claim.get_status_display(),
        })
        claim_status_totals[claim.status] = claim_status_totals.get(claim.status, Decimal('0.00')) + claim.tax_withheld

    return {
        'rows': rows,
        'claim_rows': claim_rows,
        'claim_status_totals': [
            {
                'status': dict(CustomerWithholdingTaxClaim.STATUS_CHOICES).get(status, status),
                'amount': amount,
            }
            for status, amount in sorted(claim_status_totals.items())
        ],
        'total_debit': sum((row['debit'] for row in rows), Decimal('0.00')),
        'total_credit': sum((row['credit'] for row in rows), Decimal('0.00')),
        'input_vat': input_vat,
        'output_vat': output_vat,
        'vat_due_estimate': output_vat - input_vat,
        'vat_payable': vat_payable,
        'vat_difference': vat_payable - (output_vat - input_vat),
        'cwt_receivable': cwt_receivable,
        'percentage_tax_payable': percentage_tax_payable,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_general_ledger_report(entity, start_date=None, end_date=None, account=None, include_zero=False):
    accounts = ChartOfAccount.objects.filter(entity=entity, is_active=True).order_by('code')
    if account:
        accounts = accounts.filter(pk=account.pk)
    line_qs = _line_queryset(entity, start_date=start_date, end_date=end_date)
    if account:
        line_qs = line_qs.filter(account=account)
    line_qs = line_qs.order_by(
        'account__code',
        'journal_entry__entry_date',
        'journal_entry__entry_number',
        'line_number',
        'id',
    )

    lines_by_account = {}
    for line in line_qs:
        lines_by_account.setdefault(line.account_id, []).append(line)

    sections = []
    for item in accounts:
        opening_balance = Decimal('0.00')
        if start_date:
            opening_totals = (
                JournalLine.objects
                .filter(
                    account=item,
                    journal_entry__entity=entity,
                    journal_entry__status='posted',
                    journal_entry__entry_date__lt=start_date,
                )
                .aggregate(debit_total=Sum('debit'), credit_total=Sum('credit'))
            )
            opening_balance = _statement_balance(
                item,
                opening_totals['debit_total'] or Decimal('0.00'),
                opening_totals['credit_total'] or Decimal('0.00'),
            )

        running_balance = opening_balance
        ledger_lines = []
        for line in lines_by_account.get(item.pk, []):
            movement = _statement_balance(item, line.debit, line.credit)
            running_balance += movement
            ledger_lines.append({
                'line': line,
                'journal_entry': line.journal_entry,
                'debit': line.debit,
                'credit': line.credit,
                'movement': movement,
                'running_balance': running_balance,
            })
        if ledger_lines or opening_balance != Decimal('0.00') or include_zero:
            sections.append({
                'account': item,
                'opening_balance': opening_balance,
                'lines': ledger_lines,
                'closing_balance': running_balance,
            })

    return {
        'sections': sections,
        'start_date': start_date,
        'end_date': end_date,
        'account': account,
    }


def _resolve_account(entity, account):
    if isinstance(account, ChartOfAccount):
        if account.entity_id != entity.id:
            raise ValidationError('Journal line account belongs to a different accounting entity.')
        return account
    return ChartOfAccount.objects.get(entity=entity, code=str(account))


def _decimal_amount(value):
    if value in (None, ''):
        return Decimal('0.00')
    return Decimal(str(value)).quantize(Decimal('0.01'))


POSTING_ACCOUNT_CODES = {
    'ar': '1100',
    'cash': '1000',
    'bank': '1010',
    'wallet': '1020',
    'cwt_receivable': '1210',
    'customer_advances': '2100',
    'refunds_payable': '2110',
    'internet_revenue': '4000',
    'waiver_expense': '6050',
    'other_income': '7000',
}

PAYMENT_METHOD_ACCOUNT_KEYS = {
    'cash': 'cash',
    'bank': 'bank',
    'gcash': 'wallet',
    'maya': 'wallet',
    'other': 'wallet',
}


def _active_accounting_entity():
    return AccountingEntity.objects.filter(is_active=True).first()


def _document_date_from_datetime(value):
    if not value:
        return timezone.localdate()
    return timezone.localtime(value).date()


def _source_identity(source, posting_type):
    return {
        'source_app': source._meta.app_label,
        'source_model': f"{source.__class__.__name__}.{posting_type}",
        'source_id': str(source.pk),
    }


def _source_number(source):
    return (
        getattr(source, 'invoice_number', '')
        or getattr(getattr(source, 'invoice', None), 'invoice_number', '')
        or getattr(source, 'reference', '')
        or getattr(source, 'certificate_number', '')
        or str(source.pk)
    )


def _source_subscriber(source):
    return getattr(source, 'subscriber', None) or getattr(getattr(source, 'payment', None), 'subscriber', None)


def _source_amount(source):
    return getattr(source, 'amount', Decimal('0.00')) or Decimal('0.00')


def _upsert_source_posting(source, posting_type, status, entity=None, journal_entry=None,
                           blocked_reason='', amount=None, document_date=None):
    identity = _source_identity(source, posting_type)
    defaults = {
        'entity': entity,
        'journal_entry': journal_entry,
        'source_number': _source_number(source),
        'subscriber': _source_subscriber(source),
        'document_date': document_date,
        'amount': amount if amount is not None else _source_amount(source),
        'status': status,
        'blocked_reason': blocked_reason,
        'last_attempt_at': timezone.now(),
    }
    posting, _ = AccountingSourcePosting.objects.update_or_create(
        **identity,
        defaults=defaults,
    )
    return posting


def _block_source_posting(source, posting_type, reason, entity=None, amount=None, document_date=None):
    return _upsert_source_posting(
        source,
        posting_type,
        'blocked',
        entity=entity,
        blocked_reason=reason,
        amount=amount,
        document_date=document_date,
    )


def _posting_account(entity, account_key):
    code = POSTING_ACCOUNT_CODES[account_key]
    try:
        return ChartOfAccount.objects.get(entity=entity, code=code, is_active=True)
    except ChartOfAccount.DoesNotExist as exc:
        raise ValidationError(f"Missing Accounting v2 account mapping for {account_key}: {code}") from exc


def _payment_cash_account(entity, method):
    account_key = PAYMENT_METHOD_ACCOUNT_KEYS.get(method or 'other', 'wallet')
    return _posting_account(entity, account_key)


def _existing_source_journal(entity, source, posting_type):
    identity = _source_identity(source, posting_type)
    link = (
        SourceDocumentLink.objects
        .filter(entity=entity, **identity)
        .select_related('journal_entry')
        .first()
    )
    return link.journal_entry if link else None


@transaction.atomic
def _create_source_journal(entity, source, posting_type, entry_date, description, lines,
                           source_type, reference='', posting_amount=None):
    posting_amount = posting_amount if posting_amount is not None else _source_amount(source)
    existing = _existing_source_journal(entity, source, posting_type)
    if existing:
        _upsert_source_posting(
            source,
            posting_type,
            existing.status if existing.status == 'posted' else 'draft',
            entity=entity,
            journal_entry=existing,
            amount=posting_amount,
            document_date=entry_date,
        )
        return existing

    period = find_period_for_date(entity, entry_date)
    journal_entry = JournalEntry.objects.create(
        entity=entity,
        period=period,
        entry_number=next_journal_entry_number(entity, entry_date, prefix='SRC'),
        entry_date=entry_date,
        description=description,
        reference=reference,
        source_type=source_type,
        source_document_number=_source_number(source),
    )
    for index, line in enumerate(lines, start=1):
        journal_line = JournalLine(
            journal_entry=journal_entry,
            account=line['account'],
            line_number=index,
            description=line.get('description', ''),
            debit=_decimal_amount(line.get('debit')),
            credit=_decimal_amount(line.get('credit')),
        )
        journal_line.full_clean()
        journal_line.save()

    identity = _source_identity(source, posting_type)
    SourceDocumentLink.objects.create(
        entity=entity,
        journal_entry=journal_entry,
        source_app=identity['source_app'],
        source_model=identity['source_model'],
        source_id=identity['source_id'],
        source_number=_source_number(source),
        document_date=entry_date,
    )
    _upsert_source_posting(
        source,
        posting_type,
        'draft',
        entity=entity,
        journal_entry=journal_entry,
        amount=posting_amount,
        document_date=entry_date,
    )
    return journal_entry


def _source_posting_fail_soft(source, posting_type, callback, amount=None, document_date=None):
    entity = _active_accounting_entity()
    if not entity:
        return _block_source_posting(
            source,
            posting_type,
            'Accounting v2 setup is not ready.',
            amount=amount,
            document_date=document_date,
        )
    try:
        return callback(entity)
    except ValidationError as exc:
        return _block_source_posting(
            source,
            posting_type,
            exc.messages[0] if hasattr(exc, 'messages') else str(exc),
            entity=entity,
            amount=amount,
            document_date=document_date,
        )
    except (ChartOfAccount.DoesNotExist, AccountingPeriod.DoesNotExist) as exc:
        return _block_source_posting(
            source,
            posting_type,
            str(exc),
            entity=entity,
            amount=amount,
            document_date=document_date,
        )


@transaction.atomic
def create_manual_journal_entry(
    entity,
    entry_date,
    description,
    lines,
    reference='',
    created_by=None,
    entry_number='',
):
    period = find_period_for_date(entity, entry_date)
    journal_entry = JournalEntry.objects.create(
        entity=entity,
        period=period,
        entry_number=entry_number or next_journal_entry_number(entity, entry_date),
        entry_date=entry_date,
        description=description,
        reference=reference,
        source_type='manual',
        created_by=created_by,
    )
    for index, line in enumerate(lines, start=1):
        journal_line = JournalLine(
            journal_entry=journal_entry,
            account=_resolve_account(entity, line['account']),
            line_number=line.get('line_number') or index,
            description=line.get('description', ''),
            debit=_decimal_amount(line.get('debit')),
            credit=_decimal_amount(line.get('credit')),
        )
        journal_line.full_clean()
        journal_line.save()
    return journal_entry


@transaction.atomic
def post_journal_entry(journal_entry, posted_by=None):
    journal_entry = (
        JournalEntry.objects
        .select_for_update()
        .select_related('period')
        .get(pk=journal_entry.pk)
    )
    if journal_entry.status != 'draft':
        raise ValidationError('Only draft journal entries can be posted.')
    if journal_entry.period.status != 'open':
        raise ValidationError('Journal entries can only be posted to open accounting periods.')

    lines = list(journal_entry.lines.select_related('account'))
    if len(lines) < 2:
        raise ValidationError('A journal entry must have at least two lines before posting.')
    for line in lines:
        line.full_clean()
    if not journal_entry.is_balanced():
        raise ValidationError('Journal entry debits and credits must be equal before posting.')

    journal_entry.status = 'posted'
    journal_entry.posted_by = posted_by
    journal_entry.posted_at = timezone.now()
    journal_entry.full_clean()
    journal_entry.save(update_fields=['status', 'posted_by', 'posted_at', 'updated_at'])
    AccountingSourcePosting.objects.filter(journal_entry=journal_entry).update(
        status='posted',
        blocked_reason='',
        last_attempt_at=timezone.now(),
        updated_at=timezone.now(),
    )
    return journal_entry


def _period_closing_reference(period):
    return f"CLOSE-{period.fiscal_year}-{period.period_number:02d}"


def _period_closing_journal(period):
    if period.closing_journal_entry_id:
        return period.closing_journal_entry
    return (
        JournalEntry.objects
        .filter(
            entity=period.entity,
            period=period,
            source_type='closing',
            reference=_period_closing_reference(period),
        )
        .exclude(status='voided')
        .order_by('-entry_date', '-created_at')
        .first()
    )


def _closing_equity_account(entity):
    account = ChartOfAccount.objects.filter(
        entity=entity,
        code=CLOSING_EQUITY_ACCOUNT_CODE,
        account_type='equity',
        is_active=True,
    ).first()
    if account:
        return account
    account = ChartOfAccount.objects.filter(
        entity=entity,
        account_type='equity',
        normal_balance='credit',
        is_active=True,
    ).order_by('code').first()
    if not account:
        raise ValidationError('No active equity account is available for period closing.')
    return account


def _closing_line_for_row(row):
    account = row['account']
    balance = row['balance']
    if balance == Decimal('0.00'):
        return None
    amount = abs(balance)
    line = {
        'account': account,
        'description': f"Close {account.code} {account.name}",
        'debit': Decimal('0.00'),
        'credit': Decimal('0.00'),
    }
    if balance > Decimal('0.00'):
        if account.normal_balance == 'debit':
            line['credit'] = amount
        else:
            line['debit'] = amount
    elif account.normal_balance == 'debit':
        line['debit'] = amount
    else:
        line['credit'] = amount
    return line


def _period_source_review_blockers(period):
    return AccountingSourcePosting.objects.filter(
        Q(entity=period.entity) | Q(entity__isnull=True),
        status__in=['draft', 'blocked'],
        document_date__gte=period.start_date,
        document_date__lte=period.end_date,
    ).count()


def build_period_close_preview(period):
    period = AccountingPeriod.objects.select_related(
        'entity',
        'closed_by',
        'closing_journal_entry',
    ).get(pk=period.pk)
    income_report = build_income_statement_report(
        period.entity,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    temporary_rows = _account_activity_rows(
        period.entity,
        start_date=period.start_date,
        end_date=period.end_date,
        account_types=TEMPORARY_ACCOUNT_TYPES,
        include_closing_entries=False,
    )
    closing_lines = [
        line
        for line in (_closing_line_for_row(row) for row in temporary_rows)
        if line
    ]
    debit_total = sum((line['debit'] for line in closing_lines), Decimal('0.00'))
    credit_total = sum((line['credit'] for line in closing_lines), Decimal('0.00'))
    net_close_amount = debit_total - credit_total
    equity_account = _closing_equity_account(period.entity)
    if net_close_amount > Decimal('0.00'):
        closing_lines.append({
            'account': equity_account,
            'description': 'Close net income to equity',
            'debit': Decimal('0.00'),
            'credit': net_close_amount,
        })
        credit_total += net_close_amount
    elif net_close_amount < Decimal('0.00'):
        closing_lines.append({
            'account': equity_account,
            'description': 'Close net loss to equity',
            'debit': abs(net_close_amount),
            'credit': Decimal('0.00'),
        })
        debit_total += abs(net_close_amount)

    draft_journal_count = JournalEntry.objects.filter(
        entity=period.entity,
        period=period,
        status='draft',
    ).count()
    source_review_count = _period_source_review_blockers(period)
    existing_closing_journal = _period_closing_journal(period)
    blockers = []
    if period.status != 'open':
        blockers.append('Period is not open.')
    if existing_closing_journal:
        blockers.append('Period already has a closing journal.')
    if draft_journal_count:
        blockers.append(f"{draft_journal_count} draft journal(s) still need posting or deletion.")
    if source_review_count:
        blockers.append(f"{source_review_count} source posting(s) are still draft or blocked for this period.")

    return {
        'period': period,
        'income_report': income_report,
        'temporary_rows': temporary_rows,
        'closing_lines': closing_lines,
        'debit_total': debit_total,
        'credit_total': credit_total,
        'is_balanced': debit_total == credit_total,
        'net_income': income_report['net_income'],
        'equity_account': equity_account,
        'closing_reference': _period_closing_reference(period),
        'draft_journal_count': draft_journal_count,
        'source_review_count': source_review_count,
        'existing_closing_journal': existing_closing_journal,
        'blockers': blockers,
        'can_close': not blockers and debit_total == credit_total,
    }


@transaction.atomic
def close_accounting_period(period, closed_by=None):
    period = (
        AccountingPeriod.objects
        .select_for_update()
        .select_related('entity')
        .get(pk=period.pk)
    )
    preview = build_period_close_preview(period)
    if not preview['can_close']:
        raise ValidationError('Period cannot be closed: ' + ' '.join(preview['blockers']))

    closing_journal = None
    if preview['closing_lines']:
        closing_journal = JournalEntry.objects.create(
            entity=period.entity,
            period=period,
            entry_number=next_journal_entry_number(period.entity, period.end_date, prefix='CL'),
            entry_date=period.end_date,
            description=f"Close {period.name}",
            reference=preview['closing_reference'],
            source_type='closing',
            source_document_number=preview['closing_reference'],
            created_by=closed_by if getattr(closed_by, 'is_authenticated', False) else None,
        )
        for index, line in enumerate(preview['closing_lines'], start=1):
            journal_line = JournalLine(
                journal_entry=closing_journal,
                account=line['account'],
                line_number=index,
                description=line['description'],
                debit=line['debit'],
                credit=line['credit'],
            )
            journal_line.full_clean()
            journal_line.save()
        post_journal_entry(closing_journal, posted_by=closed_by)
        closing_journal.refresh_from_db()

    period.status = 'closed'
    period.closed_at = timezone.now()
    period.closed_by = closed_by if getattr(closed_by, 'is_authenticated', False) else None
    period.closing_journal_entry = closing_journal
    period.save(update_fields=[
        'status',
        'closed_at',
        'closed_by',
        'closing_journal_entry',
    ])
    return {
        'period': period,
        'closing_journal': closing_journal,
        'preview': preview,
    }


def create_invoice_source_draft(invoice):
    entry_date = _document_date_from_datetime(invoice.created_at)

    def create(entity):
        if entity.tax_classification == 'vat':
            raise ValidationError(
                'VAT invoice source posting is blocked until invoice tax breakdown is available.'
            )
        return _create_source_journal(
            entity,
            invoice,
            'invoice',
            entry_date,
            f"Invoice {invoice.invoice_number} - {invoice.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'ar'),
                    'debit': invoice.amount,
                    'description': invoice.invoice_number,
                },
                {
                    'account': _posting_account(entity, 'internet_revenue'),
                    'credit': invoice.amount,
                    'description': invoice.invoice_number,
                },
            ],
            source_type='billing',
            reference=invoice.invoice_number,
        )

    return _source_posting_fail_soft(
        invoice,
        'invoice',
        create,
        amount=invoice.amount,
        document_date=entry_date,
    )


def _invoice_action_date(invoice):
    return _document_date_from_datetime(
        getattr(invoice, 'voided_at', None)
        or getattr(invoice, 'updated_at', None)
        or getattr(invoice, 'created_at', None)
    )


def _invoice_remaining_amount(invoice):
    return max(
        _decimal_amount(getattr(invoice, 'remaining_balance', Decimal('0.00'))),
        Decimal('0.00'),
    )


def create_invoice_waiver_source_draft(invoice):
    entry_date = _invoice_action_date(invoice)
    amount = _invoice_remaining_amount(invoice)

    def create(entity):
        if invoice.status != 'waived':
            raise ValidationError('Only waived invoices can create waiver drafts.')
        if amount <= Decimal('0.00'):
            return _upsert_source_posting(
                invoice,
                'waiver',
                'skipped',
                entity=entity,
                blocked_reason='Waived invoice has no remaining AR balance to clear.',
                amount=amount,
                document_date=entry_date,
            )
        return _create_source_journal(
            entity,
            invoice,
            'waiver',
            entry_date,
            f"Waiver {invoice.invoice_number} - {invoice.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'waiver_expense'),
                    'debit': amount,
                    'description': invoice.invoice_number,
                },
                {
                    'account': _posting_account(entity, 'ar'),
                    'credit': amount,
                    'description': invoice.invoice_number,
                },
            ],
            source_type='adjustment',
            reference=invoice.invoice_number,
            posting_amount=amount,
        )

    return _source_posting_fail_soft(
        invoice,
        'waiver',
        create,
        amount=amount,
        document_date=entry_date,
    )


def create_invoice_void_source_draft(invoice):
    entry_date = _invoice_action_date(invoice)
    amount = _invoice_remaining_amount(invoice)

    def create(entity):
        if invoice.status != 'voided':
            raise ValidationError('Only voided invoices can create void drafts.')
        if amount <= Decimal('0.00'):
            return _upsert_source_posting(
                invoice,
                'void',
                'skipped',
                entity=entity,
                blocked_reason='Voided invoice has no remaining AR balance to reverse.',
                amount=amount,
                document_date=entry_date,
            )

        original_invoice_journal = _existing_source_journal(entity, invoice, 'invoice')
        if not original_invoice_journal or original_invoice_journal.status != 'posted':
            return _block_source_posting(
                invoice,
                'void',
                'Original invoice source journal is not posted; review or void the original draft instead.',
                entity=entity,
                amount=amount,
                document_date=entry_date,
            )

        if entity.tax_classification == 'vat':
            return _block_source_posting(
                invoice,
                'void',
                'VAT invoice void reversal is blocked until invoice tax breakdown is available.',
                entity=entity,
                amount=amount,
                document_date=entry_date,
            )

        return _create_source_journal(
            entity,
            invoice,
            'void',
            entry_date,
            f"Void {invoice.invoice_number} - {invoice.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'internet_revenue'),
                    'debit': amount,
                    'description': invoice.invoice_number,
                },
                {
                    'account': _posting_account(entity, 'ar'),
                    'credit': amount,
                    'description': invoice.invoice_number,
                },
            ],
            source_type='adjustment',
            reference=invoice.invoice_number,
            posting_amount=amount,
        )

    return _source_posting_fail_soft(
        invoice,
        'void',
        create,
        amount=amount,
        document_date=entry_date,
    )


def _set_source_posting_blocked(posting, reason):
    posting.status = 'blocked'
    posting.blocked_reason = reason
    posting.journal_entry = None
    posting.last_attempt_at = timezone.now()
    posting.save(update_fields=[
        'status',
        'blocked_reason',
        'journal_entry',
        'last_attempt_at',
        'updated_at',
    ])
    return posting


def _split_source_model(source_model):
    if '.' not in source_model:
        raise ValidationError('Source posting is missing a posting type.')
    model_name, posting_type = source_model.rsplit('.', 1)
    if not model_name or not posting_type:
        raise ValidationError('Source posting is missing a source model or posting type.')
    return model_name, posting_type


def retry_source_posting(posting):
    model_name, posting_type = _split_source_model(posting.source_model)
    try:
        model = apps.get_model(posting.source_app, model_name)
    except LookupError:
        return _set_source_posting_blocked(
            posting,
            f"Source model {posting.source_app}.{model_name} is not available.",
        )

    try:
        source = model.objects.get(pk=posting.source_id)
    except model.DoesNotExist:
        return _set_source_posting_blocked(
            posting,
            'Source document no longer exists.',
        )

    if model_name == 'Invoice' and posting_type == 'invoice':
        return create_invoice_source_draft(source)
    if model_name == 'Invoice' and posting_type == 'waiver':
        return create_invoice_waiver_source_draft(source)
    if model_name == 'Invoice' and posting_type == 'void':
        return create_invoice_void_source_draft(source)
    if model_name == 'Payment' and posting_type == 'collection':
        return create_payment_source_draft(source)
    if model_name == 'PaymentAllocation' and posting_type == 'advance_application':
        return create_payment_allocation_advance_application_draft(source)
    if model_name == 'AccountCreditAdjustment' and posting_type == 'refund_due':
        return create_refund_due_source_draft(source)
    if model_name == 'AccountCreditAdjustment' and posting_type == 'refund_paid':
        return create_refund_paid_source_draft(source)
    if model_name == 'AccountCreditAdjustment' and posting_type == 'credit_forfeit':
        return create_credit_forfeiture_source_draft(source)

    return _set_source_posting_blocked(
        posting,
        f"Unsupported source posting type: {posting.source_model}.",
    )


def _payment_allocated_amount(payment):
    return payment.allocations.aggregate(total=Sum('amount_allocated'))['total'] or Decimal('0.00')


def _payment_cwt_amount(payment):
    allocated = (
        CustomerWithholdingAllocation.objects
        .filter(claim__payment=payment)
        .exclude(claim__status__in=['disallowed', 'canceled'])
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0.00')
    )
    if allocated > Decimal('0.00'):
        return allocated
    return (
        CustomerWithholdingTaxClaim.objects
        .filter(payment=payment)
        .exclude(status__in=['disallowed', 'canceled'])
        .aggregate(total=Sum('tax_withheld'))['total']
        or Decimal('0.00')
    )


def create_payment_source_draft(payment):
    entry_date = _document_date_from_datetime(payment.paid_at)

    def create(entity):
        allocated = _payment_allocated_amount(payment)
        cwt_amount = _payment_cwt_amount(payment)
        advance_amount = payment.amount - allocated
        if allocated < Decimal('0.00') or advance_amount < Decimal('0.00'):
            raise ValidationError('Payment allocations exceed the recorded cash receipt.')
        if allocated == Decimal('0.00') and advance_amount == Decimal('0.00') and cwt_amount == Decimal('0.00'):
            raise ValidationError('Payment source posting has no amount to post.')

        lines = []
        if payment.amount > Decimal('0.00'):
            lines.append({
                'account': _payment_cash_account(entity, payment.method),
                'debit': payment.amount,
                'description': payment.get_method_display(),
            })
        if cwt_amount > Decimal('0.00'):
            lines.append({
                'account': _posting_account(entity, 'cwt_receivable'),
                'debit': cwt_amount,
                'description': 'Customer EWT/CWT claim',
            })
        if allocated > Decimal('0.00'):
            lines.append({
                'account': _posting_account(entity, 'ar'),
                'credit': allocated + cwt_amount,
                'description': 'Subscriber receivable settled',
            })
        elif cwt_amount > Decimal('0.00'):
            raise ValidationError('Customer EWT/CWT claim needs a receivable allocation.')
        if advance_amount > Decimal('0.00'):
            lines.append({
                'account': _posting_account(entity, 'customer_advances'),
                'credit': advance_amount,
                'description': 'Unallocated customer advance',
            })

        return _create_source_journal(
            entity,
            payment,
            'collection',
            entry_date,
            f"Payment {payment.pk} - {payment.subscriber.username}",
            lines,
            source_type='payment',
            reference=payment.reference,
        )

    return _source_posting_fail_soft(
        payment,
        'collection',
        create,
        amount=payment.amount,
        document_date=entry_date,
    )


def create_payment_allocation_advance_application_draft(allocation):
    entry_date = _document_date_from_datetime(allocation.created_at)

    def create(entity):
        payment = allocation.payment
        allocations = list(
            PaymentAllocation.objects
            .filter(payment=payment)
            .order_by('created_at', 'pk')
        )
        running_cash_used = Decimal('0.00')
        advance_amount = Decimal('0.00')
        for item in allocations:
            available_cash = max(payment.amount - running_cash_used, Decimal('0.00'))
            cash_part = min(item.amount_allocated, available_cash)
            advance_part = item.amount_allocated - cash_part
            running_cash_used += cash_part
            if item.pk == allocation.pk:
                advance_amount = advance_part
                break

        if advance_amount <= Decimal('0.00'):
            return _upsert_source_posting(
                allocation,
                'advance_application',
                'skipped',
                entity=entity,
                blocked_reason='Allocation was covered by the original payment collection draft.',
                amount=allocation.amount_allocated,
                document_date=entry_date,
            )

        return _create_source_journal(
            entity,
            allocation,
            'advance_application',
            entry_date,
            f"Advance application - {allocation.invoice.invoice_number}",
            [
                {
                    'account': _posting_account(entity, 'customer_advances'),
                    'debit': advance_amount,
                    'description': allocation.invoice.invoice_number,
                },
                {
                    'account': _posting_account(entity, 'ar'),
                    'credit': advance_amount,
                    'description': allocation.invoice.invoice_number,
                },
            ],
            source_type='payment',
            reference=allocation.invoice.invoice_number,
        )

    return _source_posting_fail_soft(
        allocation,
        'advance_application',
        create,
        amount=allocation.amount_allocated,
        document_date=entry_date,
    )


def _credit_adjustment_date(adjustment):
    return _document_date_from_datetime(adjustment.effective_at)


def create_refund_due_source_draft(adjustment):
    entry_date = _credit_adjustment_date(adjustment)

    def create(entity):
        if adjustment.adjustment_type != 'refund_due':
            raise ValidationError('Only refund-due credit adjustments can create refund-due drafts.')
        return _create_source_journal(
            entity,
            adjustment,
            'refund_due',
            entry_date,
            f"Refund due - {adjustment.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'customer_advances'),
                    'debit': adjustment.amount,
                    'description': 'Reserve customer advance for refund',
                },
                {
                    'account': _posting_account(entity, 'refunds_payable'),
                    'credit': adjustment.amount,
                    'description': 'Refund payable to subscriber',
                },
            ],
            source_type='adjustment',
            reference=adjustment.reference,
        )

    return _source_posting_fail_soft(
        adjustment,
        'refund_due',
        create,
        amount=adjustment.amount,
        document_date=entry_date,
    )


def create_refund_paid_source_draft(adjustment):
    entry_date = _credit_adjustment_date(adjustment)

    def create(entity):
        if adjustment.adjustment_type != 'refund_paid':
            raise ValidationError('Only refund-paid credit adjustments can create refund-paid drafts.')
        refund_method = getattr(adjustment, 'settlement_method', '') or 'bank'
        return _create_source_journal(
            entity,
            adjustment,
            'refund_paid',
            entry_date,
            f"Refund paid - {adjustment.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'refunds_payable'),
                    'debit': adjustment.amount,
                    'description': 'Settle refund payable',
                },
                {
                    'account': _payment_cash_account(entity, refund_method),
                    'credit': adjustment.amount,
                    'description': adjustment.reference or 'Refund paid',
                },
            ],
            source_type='adjustment',
            reference=adjustment.reference,
        )

    return _source_posting_fail_soft(
        adjustment,
        'refund_paid',
        create,
        amount=adjustment.amount,
        document_date=entry_date,
    )


def create_credit_forfeiture_source_draft(adjustment):
    entry_date = _credit_adjustment_date(adjustment)

    def create(entity):
        if adjustment.adjustment_type != 'forfeit':
            raise ValidationError('Only forfeited credit adjustments can create forfeiture drafts.')
        return _create_source_journal(
            entity,
            adjustment,
            'credit_forfeit',
            entry_date,
            f"Credit forfeiture - {adjustment.subscriber.username}",
            [
                {
                    'account': _posting_account(entity, 'customer_advances'),
                    'debit': adjustment.amount,
                    'description': 'Forfeited customer advance',
                },
                {
                    'account': _posting_account(entity, 'other_income'),
                    'credit': adjustment.amount,
                    'description': 'Credit forfeiture income',
                },
            ],
            source_type='adjustment',
            reference=adjustment.reference,
        )

    return _source_posting_fail_soft(
        adjustment,
        'credit_forfeit',
        create,
        amount=adjustment.amount,
        document_date=entry_date,
    )


def create_credit_adjustment_source_draft(adjustment):
    if adjustment.adjustment_type == 'refund_due':
        return create_refund_due_source_draft(adjustment)
    if adjustment.adjustment_type == 'refund_paid':
        return create_refund_paid_source_draft(adjustment)
    if adjustment.adjustment_type == 'forfeit':
        return create_credit_forfeiture_source_draft(adjustment)
    return _block_source_posting(
        adjustment,
        adjustment.adjustment_type or 'credit_adjustment',
        f"Unsupported credit adjustment type: {adjustment.adjustment_type}.",
        amount=adjustment.amount,
        document_date=_credit_adjustment_date(adjustment),
    )


def build_billing_income_description(payment):
    return f"Bill payment - {payment.subscriber.username}"


def ensure_income_record_for_payment(payment):
    income_record = getattr(payment, 'income_record', None)
    if income_record:
        return income_record, False

    income_record = IncomeRecord.objects.create(
        source='billing',
        description=build_billing_income_description(payment),
        amount=payment.amount,
        reference=payment.reference,
        payment=payment,
        recorded_by=payment.recorded_by,
        date=payment.paid_at.date(),
    )
    return income_record, True


def sync_payments_to_income():
    synced = 0
    for payment in Payment.objects.filter(income_record__isnull=True):
        _, created = ensure_income_record_for_payment(payment)
        if created:
            synced += 1
    return synced


def get_monthly_summary(year=None):
    from datetime import date
    year = year or date.today().year

    income = (
        IncomeRecord.objects
        .filter(date__year=year)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    expense = (
        ExpenseRecord.objects
        .filter(date__year=year)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    income_map = {r['month'].month: r['total'] for r in income}
    expense_map = {r['month'].month: r['total'] for r in expense}

    months = []
    for m in range(1, 13):
        inc = income_map.get(m, 0)
        exp = expense_map.get(m, 0)
        months.append({
            'month': m,
            'income': inc,
            'expense': exp,
            'net': inc - exp,
        })

    return months


def get_totals(year=None):
    from datetime import date
    year = year or date.today().year
    income = IncomeRecord.objects.filter(date__year=year).aggregate(t=Sum('amount'))['t'] or 0
    expense = ExpenseRecord.objects.filter(date__year=year).aggregate(t=Sum('amount'))['t'] or 0
    return {'income': income, 'expense': expense, 'net': income - expense}
