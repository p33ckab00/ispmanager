from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from datetime import date
from apps.accounting.models import IncomeRecord, ExpenseRecord
from apps.accounting.forms import IncomeForm, ExpenseForm
from apps.accounting.services import sync_payments_to_income, get_monthly_summary, get_totals
from apps.core.models import AuditLog


@login_required
def accounting_dashboard(request):
    year = int(request.GET.get('year', date.today().year))
    months = get_monthly_summary(year)
    totals = get_totals(year)
    return render(request, 'accounting/dashboard.html', {
        'months': months,
        'totals': totals,
        'year': year,
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
