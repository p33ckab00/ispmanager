from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounting.models import (
    AccountingPeriod,
    AccountingSourcePosting,
    AlphanumericTaxCode,
    ChartOfAccount,
    CutoverBalanceScheduleLine,
    CutoverPlan,
    CutoverSubscriberBalanceLine,
    CustomerWithholdingAllocation,
    CustomerWithholdingTaxClaim,
    JournalLine,
    OpeningBalanceImport,
    OpeningBalanceLine,
    SourceDocumentLink,
    WithholdingTaxClass,
)
from apps.accounting.services import (
    build_cutover_readiness,
    create_accounting_foundation,
    create_cutover_balance_schedule,
    create_cutover_plan,
    create_credit_adjustment_source_draft,
    create_invoice_source_draft,
    create_invoice_void_source_draft,
    create_invoice_waiver_source_draft,
    create_manual_journal_entry,
    create_opening_balance_journal,
    create_payment_source_draft,
    generate_cutover_reconciliation_snapshot,
    post_journal_entry,
    refresh_opening_balance_totals,
    validate_cutover_balance_schedule,
    retry_source_posting,
    seed_bir_atc_codes,
    validate_opening_balance_import,
)
from apps.billing.models import AccountCreditAdjustment, Invoice, Payment, PaymentAllocation
from apps.subscribers.models import Subscriber


class AccountingV2FoundationTests(TestCase):
    def _foundation(self, template_key='isp_non_vat_sole_prop'):
        return create_accounting_foundation(
            entity_name='Test ISP',
            template_key=template_key,
            fiscal_year=2026,
        )

    def test_foundation_seeds_template_settings_accounts_and_periods(self):
        result = self._foundation(template_key='isp_vat_corporation')
        entity = result['entity']

        self.assertEqual(entity.taxpayer_type, 'corporation')
        self.assertEqual(entity.tax_classification, 'vat')
        self.assertEqual(entity.settings.setup_status, 'foundation_ready')
        self.assertEqual(entity.settings.current_template_key, 'isp_vat_corporation')
        self.assertEqual(AccountingPeriod.objects.filter(entity=entity).count(), 12)
        self.assertTrue(ChartOfAccount.objects.filter(entity=entity, code='1100').exists())
        self.assertTrue(ChartOfAccount.objects.filter(entity=entity, code='1200').exists())
        self.assertTrue(ChartOfAccount.objects.filter(entity=entity, code='2300').exists())

        second_result = self._foundation(template_key='isp_vat_corporation')

        self.assertFalse(second_result['entity_created'])
        self.assertEqual(second_result['coa']['created'], 0)
        self.assertEqual(AccountingPeriod.objects.filter(entity=entity).count(), 12)

    def test_balanced_draft_journal_can_be_posted_and_then_becomes_read_only(self):
        entity = self._foundation()['entity']
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 5),
            'Owner funding',
            [
                {'account': cash, 'debit': Decimal('1000.00')},
                {'account': capital, 'credit': Decimal('1000.00')},
            ],
        )

        posted = post_journal_entry(journal_entry)

        self.assertEqual(posted.status, 'posted')
        self.assertIsNotNone(posted.posted_at)
        self.assertTrue(posted.is_balanced())

        posted.description = 'Edited after posting'
        with self.assertRaises(ValidationError):
            posted.save()

        with self.assertRaises(ValidationError):
            JournalLine.objects.create(
                journal_entry=posted,
                account=cash,
                line_number=3,
                debit=Decimal('1.00'),
            )

    def test_unbalanced_draft_journal_cannot_be_posted(self):
        entity = self._foundation()['entity']
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 6),
            'Unbalanced draft',
            [
                {'account': cash, 'debit': Decimal('1000.00')},
                {'account': capital, 'credit': Decimal('900.00')},
            ],
        )

        with self.assertRaisesMessage(ValidationError, 'debits and credits must be equal'):
            post_journal_entry(journal_entry)

    def test_locked_period_blocks_posting(self):
        entity = self._foundation()['entity']
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)
        period.status = 'locked'
        period.save(update_fields=['status'])
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 7),
            'Locked period draft',
            [
                {'account': cash, 'debit': Decimal('500.00')},
                {'account': capital, 'credit': Decimal('500.00')},
            ],
        )

        with self.assertRaisesMessage(ValidationError, 'open accounting periods'):
            post_journal_entry(journal_entry)

    def test_journal_line_requires_exactly_one_amount_side(self):
        entity = self._foundation()['entity']
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 8),
            'Draft for line validation',
            [
                {'account': cash, 'debit': Decimal('100.00')},
                {'account': capital, 'credit': Decimal('100.00')},
            ],
        )
        bad_line = JournalLine(
            journal_entry=journal_entry,
            account=cash,
            line_number=3,
            debit=Decimal('10.00'),
            credit=Decimal('10.00'),
        )

        with self.assertRaisesMessage(ValidationError, 'either a debit or a credit'):
            bad_line.full_clean()


class AccountingV2CutoverTests(TestCase):
    def _foundation(self):
        return create_accounting_foundation(
            entity_name='Cutover ISP',
            template_key='isp_non_vat_sole_prop',
            fiscal_year=2026,
        )['entity']

    def _plan(self, entity):
        return create_cutover_plan(entity, date(2026, 1, 1))[0]

    def _import_batch(self, entity, plan):
        return OpeningBalanceImport.objects.create(
            entity=entity,
            cutover_plan=plan,
            import_type='manual',
        )

    def test_cutover_plan_updates_single_active_plan(self):
        entity = self._foundation()
        plan, created = create_cutover_plan(entity, date(2026, 1, 1), notes='initial')

        updated, second_created = create_cutover_plan(entity, date(2026, 2, 1), notes='updated')

        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(plan.pk, updated.pk)
        self.assertEqual(CutoverPlan.objects.filter(entity=entity).exclude(status='voided').count(), 1)
        self.assertEqual(updated.cutover_date, date(2026, 2, 1))
        self.assertEqual(updated.notes, 'updated')

    def test_opening_balance_line_requires_exactly_one_amount_side(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        line = OpeningBalanceLine(
            entity=entity,
            import_batch=import_batch,
            account=cash,
            line_type='cash',
            debit=Decimal('100.00'),
            credit=Decimal('100.00'),
        )

        with self.assertRaisesMessage(ValidationError, 'either a debit or a credit'):
            line.full_clean()

    def test_unbalanced_opening_import_cannot_create_journal(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=cash,
            line_type='cash',
            debit=Decimal('1000.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('900.00'),
        )

        validated = validate_opening_balance_import(import_batch)

        self.assertEqual(validated.status, 'draft')
        self.assertIn('unbalanced', validated.validation_errors)
        with self.assertRaisesMessage(ValidationError, 'balanced and valid'):
            create_opening_balance_journal(import_batch)

    def test_balanced_opening_import_creates_draft_opening_journal(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=cash,
            line_type='cash',
            debit=Decimal('1000.00'),
            reference='Cash count',
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('1000.00'),
            reference='Owner capital',
        )

        refresh_opening_balance_totals(import_batch)
        validated = validate_opening_balance_import(import_batch)
        journal_entry = create_opening_balance_journal(validated)
        schedule = create_cutover_balance_schedule(plan, 'cash_on_hand')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=cash,
            label='Cash count',
            debit=Decimal('1000.00'),
        )
        validate_cutover_balance_schedule(schedule)
        readiness = build_cutover_readiness(entity)

        self.assertEqual(validated.status, 'validated')
        self.assertEqual(journal_entry.status, 'draft')
        self.assertEqual(journal_entry.source_type, 'opening_balance')
        self.assertTrue(journal_entry.is_balanced())
        self.assertEqual(journal_entry.lines.count(), 2)
        self.assertTrue(readiness['all_passed'])


class AccountingV2CutoverReconciliationTests(TestCase):
    def _foundation(self):
        return create_accounting_foundation(
            entity_name='Reconciliation ISP',
            template_key='isp_non_vat_sole_prop',
            fiscal_year=2026,
        )['entity']

    def _subscriber(self, username='recon-client'):
        return Subscriber.objects.create(
            username=username,
            full_name='Reconciliation Client',
            status='active',
            is_billable=True,
        )

    def _aware(self, year, month, day):
        return timezone.make_aware(datetime(year, month, day, 12, 0, 0))

    def _invoice(self, subscriber, amount, status='open', created_at=None, period_start=None):
        invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=period_start or date(2025, 12, 1),
            period_end=date(2025, 12, 31),
            due_date=date(2026, 1, 5),
            amount=Decimal(str(amount)),
            rate_snapshot=Decimal(str(amount)),
            status=status,
        )
        if created_at:
            Invoice.objects.filter(pk=invoice.pk).update(created_at=created_at)
            invoice.refresh_from_db()
        return invoice

    def _allocate(self, subscriber, invoice, amount, paid_at, allocated_at=None):
        payment = Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal(str(amount)),
            method='cash',
            reference=f'PAY-{invoice.pk}-{amount}',
            paid_at=paid_at,
        )
        allocation = PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount_allocated=Decimal(str(amount)),
        )
        PaymentAllocation.objects.filter(pk=allocation.pk).update(created_at=allocated_at or paid_at)
        return payment, allocation

    def _opening_import(self, entity, plan):
        return OpeningBalanceImport.objects.create(
            entity=entity,
            cutover_plan=plan,
            import_type='manual',
        )

    def test_reconciliation_snapshot_matches_ar_and_customer_advances(self):
        entity = self._foundation()
        plan = create_cutover_plan(entity, date(2026, 1, 1))[0]
        subscriber = self._subscriber()
        invoice = self._invoice(
            subscriber,
            Decimal('100.00'),
            status='partial',
            created_at=self._aware(2025, 12, 15),
        )
        self._allocate(subscriber, invoice, Decimal('30.00'), self._aware(2025, 12, 20))
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('50.00'),
            method='gcash',
            reference='ADV-50',
            paid_at=self._aware(2025, 12, 21),
        )
        import_batch = self._opening_import(entity, plan)
        ar = ChartOfAccount.objects.get(entity=entity, code='1100')
        advances = ChartOfAccount.objects.get(entity=entity, code='2100')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=ar,
            line_type='subscriber_ar',
            subscriber=subscriber,
            debit=Decimal('70.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=advances,
            line_type='customer_advance',
            subscriber=subscriber,
            credit=Decimal('50.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('20.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)

        snapshot = generate_cutover_reconciliation_snapshot(plan)

        self.assertEqual(snapshot.status, 'reconciled')
        self.assertEqual(snapshot.ar_source_total, Decimal('70.00'))
        self.assertEqual(snapshot.ar_opening_total, Decimal('70.00'))
        self.assertEqual(snapshot.advance_source_total, Decimal('50.00'))
        self.assertEqual(snapshot.advance_opening_total, Decimal('50.00'))
        self.assertEqual(
            set(snapshot.subscriber_lines.values_list('status', flat=True)),
            {'matched'},
        )

    def test_reconciliation_snapshot_flags_missing_opening_balance(self):
        entity = self._foundation()
        plan = create_cutover_plan(entity, date(2026, 1, 1))[0]
        subscriber = self._subscriber(username='missing-opening')
        self._invoice(
            subscriber,
            Decimal('100.00'),
            status='open',
            created_at=self._aware(2025, 12, 15),
        )

        snapshot = generate_cutover_reconciliation_snapshot(plan)
        line = CutoverSubscriberBalanceLine.objects.get(
            snapshot=snapshot,
            subscriber=subscriber,
            balance_type='subscriber_ar',
        )

        self.assertEqual(snapshot.status, 'generated')
        self.assertEqual(line.status, 'missing_opening')
        self.assertEqual(line.source_balance, Decimal('100.00'))
        self.assertEqual(line.opening_balance, Decimal('0.00'))

    def test_reconciliation_uses_cutover_as_of_dates(self):
        entity = self._foundation()
        plan = create_cutover_plan(entity, date(2026, 1, 1))[0]
        subscriber = self._subscriber(username='as-of-client')
        invoice = self._invoice(
            subscriber,
            Decimal('100.00'),
            status='paid',
            created_at=self._aware(2025, 12, 15),
        )
        self._allocate(
            subscriber,
            invoice,
            Decimal('100.00'),
            paid_at=self._aware(2026, 1, 5),
            allocated_at=self._aware(2026, 1, 5),
        )

        snapshot = generate_cutover_reconciliation_snapshot(plan)
        line = CutoverSubscriberBalanceLine.objects.get(
            snapshot=snapshot,
            subscriber=subscriber,
            balance_type='subscriber_ar',
        )

        self.assertEqual(line.source_balance, Decimal('100.00'))
        self.assertEqual(line.status, 'missing_opening')

    def test_reconciliation_requires_subscriber_level_matches_not_only_total_match(self):
        entity = self._foundation()
        plan = create_cutover_plan(entity, date(2026, 1, 1))[0]
        source_subscriber = self._subscriber(username='source-only')
        opening_subscriber = self._subscriber(username='opening-only')
        self._invoice(
            source_subscriber,
            Decimal('100.00'),
            status='open',
            created_at=self._aware(2025, 12, 15),
        )
        import_batch = self._opening_import(entity, plan)
        ar = ChartOfAccount.objects.get(entity=entity, code='1100')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=ar,
            line_type='subscriber_ar',
            subscriber=opening_subscriber,
            debit=Decimal('100.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('100.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)

        snapshot = generate_cutover_reconciliation_snapshot(plan)

        self.assertEqual(snapshot.ar_difference, Decimal('0.00'))
        self.assertEqual(snapshot.status, 'generated')
        self.assertFalse(snapshot.all_matched)
        self.assertEqual(
            set(snapshot.subscriber_lines.values_list('status', flat=True)),
            {'missing_opening', 'missing_source'},
        )


class AccountingV2CutoverBalanceScheduleTests(TestCase):
    def _foundation(self):
        return create_accounting_foundation(
            entity_name='Schedule ISP',
            template_key='isp_non_vat_sole_prop',
            fiscal_year=2026,
        )['entity']

    def _plan(self, entity):
        return create_cutover_plan(entity, date(2026, 1, 1))[0]

    def _import_batch(self, entity, plan):
        return OpeningBalanceImport.objects.create(
            entity=entity,
            cutover_plan=plan,
            import_type='manual',
        )

    def test_cash_schedule_reconciles_to_opening_balance_lines(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=cash,
            line_type='cash',
            debit=Decimal('250.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('250.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'cash_on_hand')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=cash,
            label='Cash count',
            debit=Decimal('250.00'),
        )

        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.status, 'reconciled')
        self.assertEqual(schedule.difference, Decimal('0.00'))

    def test_tax_schedule_checks_account_level_differences_not_only_net_total(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cwt = ChartOfAccount.objects.get(entity=entity, code='1210')
        wht_payable = ChartOfAccount.objects.get(entity=entity, code='2310')
        percentage_tax = ChartOfAccount.objects.get(entity=entity, code='2330')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=cwt,
            line_type='tax',
            debit=Decimal('100.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=wht_payable,
            line_type='tax',
            credit=Decimal('100.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'tax_balance')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=cwt,
            label='CWT receivable',
            debit=Decimal('100.00'),
            source_document_number='Tax worksheet',
        )
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=percentage_tax,
            label='Percentage tax payable',
            credit=Decimal('100.00'),
            source_document_number='Tax worksheet',
        )

        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.difference, Decimal('0.00'))
        self.assertEqual(schedule.status, 'needs_review')
        self.assertIn('2310', schedule.validation_errors)
        self.assertIn('2330', schedule.validation_errors)

    def test_ap_schedule_line_requires_counterparty_name(self):
        entity = self._foundation()
        plan = self._plan(entity)
        schedule = create_cutover_balance_schedule(plan, 'accounts_payable')[0]
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        line = CutoverBalanceScheduleLine(
            entity=entity,
            schedule=schedule,
            account=ap,
            label='Unpaid vendor bill',
            credit=Decimal('100.00'),
        )

        with self.assertRaisesMessage(ValidationError, 'vendor or payee'):
            line.full_clean()

    def test_inventory_schedule_reconciles_and_requires_quantity(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        inventory = ChartOfAccount.objects.get(entity=entity, code='1300')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=inventory,
            line_type='inventory',
            debit=Decimal('750.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('750.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'inventory')[0]
        missing_quantity = CutoverBalanceScheduleLine(
            entity=entity,
            schedule=schedule,
            account=inventory,
            label='ONU stock count',
            debit=Decimal('750.00'),
        )

        with self.assertRaisesMessage(ValidationError, 'quantity'):
            missing_quantity.full_clean()

        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=inventory,
            label='ONU stock count',
            debit=Decimal('750.00'),
            quantity=Decimal('10.0000'),
            unit='pcs',
            location='Main warehouse',
        )
        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.status, 'reconciled')
        self.assertEqual(schedule.difference, Decimal('0.00'))

    def test_fixed_asset_schedule_reconciles_cost_and_accumulated_depreciation(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        network_asset = ChartOfAccount.objects.get(entity=entity, code='1500')
        accumulated_depreciation = ChartOfAccount.objects.get(entity=entity, code='1590')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=network_asset,
            line_type='fixed_asset',
            debit=Decimal('1000.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=accumulated_depreciation,
            line_type='accumulated_depreciation',
            credit=Decimal('200.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('800.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'fixed_assets')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=network_asset,
            label='Core router',
            debit=Decimal('1000.00'),
            asset_identifier='RTR-CORE-001',
            acquisition_date=date(2025, 1, 15),
            useful_life_months=60,
            source_document_number='Asset register',
        )
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=accumulated_depreciation,
            label='Core router accumulated depreciation',
            credit=Decimal('200.00'),
            asset_identifier='RTR-CORE-001',
            source_document_number='Depreciation worksheet',
        )

        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.status, 'reconciled')
        self.assertEqual(schedule.total_debit, Decimal('1000.00'))
        self.assertEqual(schedule.total_credit, Decimal('200.00'))

    def test_loan_schedule_reconciles_and_requires_lender(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        bank = ChartOfAccount.objects.get(entity=entity, code='1010')
        loans = ChartOfAccount.objects.get(entity=entity, code='2400')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=bank,
            line_type='bank',
            debit=Decimal('500.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=loans,
            line_type='loan',
            credit=Decimal('500.00'),
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'loans_payable')[0]
        missing_lender = CutoverBalanceScheduleLine(
            entity=entity,
            schedule=schedule,
            account=loans,
            label='Equipment loan',
            credit=Decimal('500.00'),
        )

        with self.assertRaisesMessage(ValidationError, 'lender'):
            missing_lender.full_clean()

        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=loans,
            label='Equipment loan',
            credit=Decimal('500.00'),
            counterparty_name='Local Bank',
            source_document_number='Loan agreement',
            maturity_date=date(2028, 12, 31),
        )
        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.status, 'reconciled')
        self.assertEqual(schedule.difference, Decimal('0.00'))

    def test_equity_schedule_reconciles_opening_equity_accounts(self):
        entity = self._foundation()
        plan = self._plan(entity)
        import_batch = self._import_batch(entity, plan)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=cash,
            line_type='cash',
            debit=Decimal('700.00'),
        )
        OpeningBalanceLine.objects.create(
            entity=entity,
            import_batch=import_batch,
            account=capital,
            line_type='equity',
            credit=Decimal('700.00'),
            reference='Opening capital support',
        )
        refresh_opening_balance_totals(import_batch)
        validate_opening_balance_import(import_batch)
        schedule = create_cutover_balance_schedule(plan, 'equity_balance')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=capital,
            label='Owner capital',
            credit=Decimal('700.00'),
            source_document_number='Opening equity worksheet',
        )

        validate_cutover_balance_schedule(schedule)
        schedule.refresh_from_db()

        self.assertEqual(schedule.status, 'reconciled')
        self.assertEqual(schedule.difference, Decimal('0.00'))


class AccountingV2SourcePostingTests(TestCase):
    def _subscriber(self):
        return Subscriber.objects.create(
            username='source-client',
            full_name='Source Client',
            status='active',
            is_billable=True,
        )

    def _invoice(self, subscriber=None, amount=Decimal('1000.00')):
        subscriber = subscriber or self._subscriber()
        today = timezone.localdate()
        return Invoice.objects.create(
            subscriber=subscriber,
            period_start=today.replace(day=1),
            period_end=today,
            due_date=today,
            amount=amount,
            rate_snapshot=amount,
        )

    def _foundation(self):
        return create_accounting_foundation(
            entity_name='Source ISP',
            template_key='isp_non_vat_sole_prop',
            fiscal_year=timezone.localdate().year,
        )['entity']

    def test_invoice_source_posting_blocks_without_accounting_setup(self):
        invoice = self._invoice()

        result = create_invoice_source_draft(invoice)

        self.assertIsInstance(result, AccountingSourcePosting)
        self.assertEqual(result.status, 'blocked')
        self.assertIn('setup is not ready', result.blocked_reason)

    def test_non_vat_invoice_source_posting_creates_idempotent_draft(self):
        entity = self._foundation()
        invoice = self._invoice()

        journal_entry = create_invoice_source_draft(invoice)
        second = create_invoice_source_draft(invoice)

        self.assertEqual(journal_entry.pk, second.pk)
        self.assertEqual(journal_entry.source_type, 'billing')
        self.assertTrue(journal_entry.is_balanced())
        self.assertEqual(SourceDocumentLink.objects.filter(journal_entry=journal_entry).count(), 1)
        posting = AccountingSourcePosting.objects.get(source_model='Invoice.invoice', source_id=str(invoice.pk))
        self.assertEqual(posting.status, 'draft')
        self.assertEqual(posting.entity, entity)

        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['1100'].debit, Decimal('1000.00'))
        self.assertEqual(lines['4000'].credit, Decimal('1000.00'))

    def test_payment_with_cwt_claim_posts_cash_cwt_and_ar(self):
        self._foundation()
        subscriber = self._subscriber()
        invoice = self._invoice(subscriber=subscriber)
        payment = Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('900.00'),
            method='bank',
            reference='NET-CWT',
            recorded_by='tester',
            paid_at=timezone.now(),
        )
        PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount_allocated=Decimal('900.00'),
        )
        claim = CustomerWithholdingTaxClaim.objects.create(
            subscriber=subscriber,
            payment=payment,
            gross_amount=Decimal('1000.00'),
            tax_withheld=Decimal('100.00'),
            withholding_rate=Decimal('10.0000'),
            status='pending_2307',
        )
        CustomerWithholdingAllocation.objects.create(
            claim=claim,
            invoice=invoice,
            amount=Decimal('100.00'),
        )

        journal_entry = create_payment_source_draft(payment)

        self.assertTrue(journal_entry.is_balanced())
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['1010'].debit, Decimal('900.00'))
        self.assertEqual(lines['1210'].debit, Decimal('100.00'))
        self.assertEqual(lines['1100'].credit, Decimal('1000.00'))

    def test_posting_source_journal_marks_source_posting_posted(self):
        self._foundation()
        invoice = self._invoice()
        journal_entry = create_invoice_source_draft(invoice)

        post_journal_entry(journal_entry)

        posting = AccountingSourcePosting.objects.get(source_model='Invoice.invoice', source_id=str(invoice.pk))
        self.assertEqual(posting.status, 'posted')

    def test_withholding_tax_class_blocks_invalid_effective_date_range(self):
        entity = self._foundation()
        tax_class = WithholdingTaxClass(
            entity=entity,
            code='BAD-DATES',
            name='Bad date range',
            effective_from=date(2026, 12, 31),
            effective_to=date(2026, 1, 1),
        )

        with self.assertRaisesMessage(ValidationError, 'end date cannot be before start date'):
            tax_class.full_clean()

    def test_refund_due_source_posting_creates_customer_advance_reclass(self):
        entity = self._foundation()
        subscriber = self._subscriber()
        adjustment = AccountCreditAdjustment.objects.create(
            subscriber=subscriber,
            adjustment_type='refund_due',
            status='pending',
            amount=Decimal('300.00'),
            recorded_by='tester',
            effective_at=timezone.now(),
        )

        journal_entry = create_credit_adjustment_source_draft(adjustment)

        self.assertTrue(journal_entry.is_balanced())
        posting = AccountingSourcePosting.objects.get(
            source_model='AccountCreditAdjustment.refund_due',
            source_id=str(adjustment.pk),
        )
        self.assertEqual(posting.entity, entity)
        self.assertEqual(posting.status, 'draft')
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['2100'].debit, Decimal('300.00'))
        self.assertEqual(lines['2110'].credit, Decimal('300.00'))

    def test_refund_paid_source_posting_uses_settlement_method(self):
        self._foundation()
        subscriber = self._subscriber()
        adjustment = AccountCreditAdjustment.objects.create(
            subscriber=subscriber,
            adjustment_type='refund_paid',
            status='completed',
            amount=Decimal('300.00'),
            reference='MAYA-REFUND',
            settlement_method='maya',
            recorded_by='tester',
            effective_at=timezone.now(),
        )

        journal_entry = create_credit_adjustment_source_draft(adjustment)

        self.assertTrue(journal_entry.is_balanced())
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['2110'].debit, Decimal('300.00'))
        self.assertEqual(lines['1020'].credit, Decimal('300.00'))

    def test_credit_forfeiture_source_posting_recognizes_other_income(self):
        self._foundation()
        subscriber = self._subscriber()
        adjustment = AccountCreditAdjustment.objects.create(
            subscriber=subscriber,
            adjustment_type='forfeit',
            status='completed',
            amount=Decimal('250.00'),
            recorded_by='tester',
            effective_at=timezone.now(),
        )

        journal_entry = create_credit_adjustment_source_draft(adjustment)

        self.assertTrue(journal_entry.is_balanced())
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['2100'].debit, Decimal('250.00'))
        self.assertEqual(lines['7000'].credit, Decimal('250.00'))

    def test_invoice_waiver_source_posting_clears_remaining_ar(self):
        self._foundation()
        invoice = self._invoice(amount=Decimal('1000.00'))
        invoice.amount_paid = Decimal('250.00')
        invoice.status = 'waived'
        invoice.voided_at = timezone.now()
        invoice.save(update_fields=['amount_paid', 'status', 'voided_at', 'updated_at'])

        journal_entry = create_invoice_waiver_source_draft(invoice)

        self.assertTrue(journal_entry.is_balanced())
        posting = AccountingSourcePosting.objects.get(
            source_model='Invoice.waiver',
            source_id=str(invoice.pk),
        )
        self.assertEqual(posting.status, 'draft')
        self.assertEqual(posting.amount, Decimal('750.00'))
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['6050'].debit, Decimal('750.00'))
        self.assertEqual(lines['1100'].credit, Decimal('750.00'))

    def test_invoice_void_source_posting_blocks_when_invoice_journal_is_not_posted(self):
        self._foundation()
        invoice = self._invoice()
        invoice.status = 'voided'
        invoice.voided_at = timezone.now()
        invoice.save(update_fields=['status', 'voided_at', 'updated_at'])

        result = create_invoice_void_source_draft(invoice)

        self.assertIsInstance(result, AccountingSourcePosting)
        self.assertEqual(result.status, 'blocked')
        self.assertIn('source journal is not posted', result.blocked_reason)

    def test_invoice_void_source_posting_reverses_posted_invoice_remaining_ar(self):
        self._foundation()
        invoice = self._invoice(amount=Decimal('1000.00'))
        invoice_journal = create_invoice_source_draft(invoice)
        post_journal_entry(invoice_journal)
        invoice.amount_paid = Decimal('250.00')
        invoice.status = 'voided'
        invoice.voided_at = timezone.now()
        invoice.save(update_fields=['amount_paid', 'status', 'voided_at', 'updated_at'])

        journal_entry = create_invoice_void_source_draft(invoice)

        self.assertTrue(journal_entry.is_balanced())
        posting = AccountingSourcePosting.objects.get(
            source_model='Invoice.void',
            source_id=str(invoice.pk),
        )
        self.assertEqual(posting.status, 'draft')
        self.assertEqual(posting.amount, Decimal('750.00'))
        lines = {line.account.code: line for line in journal_entry.lines.select_related('account')}
        self.assertEqual(lines['4000'].debit, Decimal('750.00'))
        self.assertEqual(lines['1100'].credit, Decimal('750.00'))

    def test_retry_blocked_invoice_source_posting_after_setup_creates_draft(self):
        invoice = self._invoice()
        blocked = create_invoice_source_draft(invoice)
        self.assertEqual(blocked.status, 'blocked')

        entity = self._foundation()
        retry_source_posting(blocked)

        posting = AccountingSourcePosting.objects.get(
            source_model='Invoice.invoice',
            source_id=str(invoice.pk),
        )
        self.assertEqual(posting.entity, entity)
        self.assertEqual(posting.status, 'draft')
        self.assertIsNotNone(posting.journal_entry)

    def test_retry_missing_source_document_stays_blocked(self):
        entity = self._foundation()
        posting = AccountingSourcePosting.objects.create(
            entity=entity,
            source_app='billing',
            source_model='Invoice.invoice',
            source_id='999999',
            status='blocked',
            blocked_reason='Initial failure',
        )

        result = retry_source_posting(posting)

        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.blocked_reason, 'Source document no longer exists.')

    def test_bir_atc_catalog_seed_includes_common_2307_codes(self):
        result = seed_bir_atc_codes()

        self.assertGreaterEqual(result['total'], 60)
        self.assertTrue(AlphanumericTaxCode.objects.filter(code='WC160', rate=Decimal('2.0000')).exists())
        self.assertTrue(AlphanumericTaxCode.objects.filter(code='WC158', rate=Decimal('1.0000')).exists())
        self.assertTrue(AlphanumericTaxCode.objects.filter(code='WI820', rate=Decimal('0.5000')).exists())
        self.assertFalse(AlphanumericTaxCode.objects.get(code='WC760').is_active)
