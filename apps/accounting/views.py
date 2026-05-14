from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.accounting.models import (
    AccountingEntity,
    AccountingPeriod,
    AccountingSettings,
    AccountingSourcePosting,
    AlphanumericTaxCode,
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
    AccountingSetupForm,
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
from apps.accounting.services import (
    build_cutover_readiness,
    build_cutover_balance_schedule_reconciliation,
    build_cutover_balance_schedule_summary,
    create_accounting_foundation,
    create_cutover_balance_schedule,
    create_cutover_plan,
    create_manual_journal_entry,
    create_opening_balance_journal,
    generate_cutover_reconciliation_snapshot,
    get_active_cutover_plan,
    refresh_cutover_balance_schedule,
    get_latest_cutover_reconciliation_snapshot,
    post_journal_entry,
    refresh_opening_balance_totals,
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
        'periods': AccountingPeriod.objects.filter(entity=entity).order_by('start_date'),
    })


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
    periods = AccountingPeriod.objects.filter(entity=entity).order_by('-start_date')
    period = periods.filter(pk=period_id).first() if period_id else periods.first()
    rows = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')
    if period:
        line_filter = Q(
            journal_lines__journal_entry__entity=entity,
            journal_lines__journal_entry__status='posted',
            journal_lines__journal_entry__entry_date__gte=period.start_date,
            journal_lines__journal_entry__entry_date__lte=period.end_date,
        )
        accounts = ChartOfAccount.objects.filter(entity=entity, is_active=True).annotate(
            debit_total=Sum('journal_lines__debit', filter=line_filter),
            credit_total=Sum('journal_lines__credit', filter=line_filter),
        ).order_by('code')
        for account in accounts:
            debit = account.debit_total or Decimal('0.00')
            credit = account.credit_total or Decimal('0.00')
            if not debit and not credit:
                continue
            total_debit += debit
            total_credit += credit
            balance = debit - credit if account.normal_balance == 'debit' else credit - debit
            rows.append({
                'account': account,
                'debit': debit,
                'credit': credit,
                'balance': balance,
            })

    return render(request, 'accounting/trial_balance.html', {
        'entity': entity,
        'periods': periods,
        'period': period,
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'is_balanced': total_debit == total_credit,
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
        'can_edit': not import_batch.journal_entry_id and import_batch.status not in ('journal_created', 'posted', 'voided'),
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
        'can_edit': schedule.status != 'voided',
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
