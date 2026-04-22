from django.db.models import Sum
from django.db.models.functions import TruncMonth
from apps.accounting.models import IncomeRecord, ExpenseRecord
from apps.billing.models import Payment


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
