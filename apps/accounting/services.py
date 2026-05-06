from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounting.models import (
    AccountingEntity,
    AccountingPeriod,
    AccountingSettings,
    ChartOfAccount,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    JournalLine,
)
from apps.billing.models import Payment


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
    _account('1300', 'CPE and Network Inventory', 'asset', 'debit'),
    _account('1400', 'Prepaid Expenses', 'asset', 'debit'),
    _account('1500', 'Network Equipment and Facilities', 'asset', 'debit'),
    _account('1590', 'Accumulated Depreciation - Network Equipment', 'asset', 'credit'),
    _account('2000', 'Accounts Payable', 'liability', 'credit'),
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
    return journal_entry


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
