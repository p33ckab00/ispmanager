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
    AccountingSourcePosting,
    ChartOfAccount,
    CustomerWithholdingTaxClaim,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    JournalLine,
    SourceDocumentLink,
)
from apps.billing.models import Payment, PaymentAllocation


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


POSTING_ACCOUNT_CODES = {
    'ar': '1100',
    'cash': '1000',
    'bank': '1010',
    'wallet': '1020',
    'cwt_receivable': '1210',
    'customer_advances': '2100',
    'refunds_payable': '2110',
    'internet_revenue': '4000',
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
                           source_type, reference=''):
    existing = _existing_source_journal(entity, source, posting_type)
    if existing:
        _upsert_source_posting(
            source,
            posting_type,
            existing.status if existing.status == 'posted' else 'draft',
            entity=entity,
            journal_entry=existing,
            amount=_source_amount(source),
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
        amount=_source_amount(source),
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


def _payment_allocated_amount(payment):
    return payment.allocations.aggregate(total=Sum('amount_allocated'))['total'] or Decimal('0.00')


def _payment_cwt_amount(payment):
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
