import json
import hashlib
import tempfile
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounting.models import (
    AccountingPeriod,
    AccountingReportArchive,
    AccountingSourcePosting,
    AlphanumericTaxCode,
    APVendor,
    APVendorBill,
    APVendorBillAttachment,
    APVendorPayment,
    ChartOfAccount,
    CutoverBalanceSchedule,
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
    approve_cutover_plan,
    build_ap_aging_report,
    build_ar_aging_report,
    build_balance_sheet_report,
    build_cash_flow_report,
    build_changes_in_equity_report,
    build_cutover_readiness,
    build_general_ledger_report,
    build_income_statement_report,
    build_period_close_preview,
    build_period_reopen_preview,
    build_tax_ledger_report,
    build_trial_balance_report,
    close_accounting_period,
    create_ap_vendor_bill_attachment,
    create_ap_vendor_bill_draft,
    create_ap_vendor_bill_void_draft,
    create_ap_vendor_payment_draft,
    create_ap_vendor_payment_void_draft,
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
    mark_accounting_live,
    mark_cutover_ready,
    match_ap_vendor_payment_settlement,
    post_journal_entry,
    refresh_ap_vendor_bill_status,
    refresh_ap_vendor_payment_status,
    refresh_opening_balance_totals,
    reopen_accounting_period,
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


class AccountingV2FinancialStatementTests(TestCase):
    def _foundation(self):
        return create_accounting_foundation(
            entity_name='Statement ISP',
            template_key='isp_non_vat_sole_prop',
            fiscal_year=2026,
        )['entity']

    def _post_sample_activity(self):
        entity = self._foundation()
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        revenue = ChartOfAccount.objects.get(entity=entity, code='4000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6010')
        opening = create_manual_journal_entry(
            entity,
            date(2026, 1, 1),
            'Opening capital',
            [
                {'account': cash, 'debit': Decimal('1000.00')},
                {'account': capital, 'credit': Decimal('1000.00')},
            ],
        )
        sale = create_manual_journal_entry(
            entity,
            date(2026, 1, 10),
            'Monthly service revenue',
            [
                {'account': cash, 'debit': Decimal('500.00')},
                {'account': revenue, 'credit': Decimal('500.00')},
            ],
        )
        utility = create_manual_journal_entry(
            entity,
            date(2026, 1, 15),
            'Power bill',
            [
                {'account': expense, 'debit': Decimal('120.00')},
                {'account': cash, 'credit': Decimal('120.00')},
            ],
        )
        for journal_entry in (opening, sale, utility):
            post_journal_entry(journal_entry)
        return entity, cash

    def test_trial_balance_uses_posted_journals_only_and_balances(self):
        entity, _cash = self._post_sample_activity()

        report = build_trial_balance_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertTrue(report['is_balanced'])
        self.assertEqual(report['total_debit'], Decimal('1620.00'))
        self.assertEqual(report['total_credit'], Decimal('1620.00'))

    def test_income_statement_and_balance_sheet_include_current_earnings(self):
        entity, _cash = self._post_sample_activity()

        income = build_income_statement_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        balance_sheet = build_balance_sheet_report(entity, as_of_date=date(2026, 1, 31))

        self.assertEqual(income['totals']['revenue'], Decimal('500.00'))
        self.assertEqual(income['totals']['expense'], Decimal('120.00'))
        self.assertEqual(income['net_income'], Decimal('380.00'))
        self.assertEqual(balance_sheet['totals']['asset'], Decimal('1380.00'))
        self.assertEqual(balance_sheet['totals']['equity'], Decimal('1380.00'))
        self.assertTrue(balance_sheet['is_balanced'])

    def test_period_close_posts_closing_entry_and_removes_unclosed_current_earnings(self):
        entity, cash = self._post_sample_activity()
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')

        preview = build_period_close_preview(period)
        result = close_accounting_period(period)
        period.refresh_from_db()
        closing_journal = result['closing_journal']

        self.assertTrue(preview['can_close'])
        self.assertEqual(preview['net_income'], Decimal('380.00'))
        self.assertEqual(period.status, 'closed')
        self.assertIsNotNone(period.closed_at)
        self.assertEqual(period.closing_journal_entry, closing_journal)
        self.assertEqual(closing_journal.status, 'posted')
        self.assertEqual(closing_journal.source_type, 'closing')
        self.assertEqual(closing_journal.reference, 'CLOSE-2026-01')

        income = build_income_statement_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        balance_sheet = build_balance_sheet_report(entity, as_of_date=date(2026, 1, 31))
        trial_balance = build_trial_balance_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        revenue_balance = next(row['balance'] for row in trial_balance['rows'] if row['account'].code == '4000')
        expense_balance = next(row['balance'] for row in trial_balance['rows'] if row['account'].code == '6010')

        self.assertEqual(income['net_income'], Decimal('380.00'))
        self.assertFalse(balance_sheet['uses_unclosed_current_earnings'])
        self.assertEqual(balance_sheet['current_earnings'], Decimal('0.00'))
        self.assertEqual(balance_sheet['totals']['equity'], Decimal('1380.00'))
        self.assertTrue(balance_sheet['is_balanced'])
        self.assertEqual(revenue_balance, Decimal('0.00'))
        self.assertEqual(expense_balance, Decimal('0.00'))

        blocked_journal = create_manual_journal_entry(
            entity,
            date(2026, 1, 20),
            'Post-close adjustment',
            [
                {'account': cash, 'debit': Decimal('25.00')},
                {'account': capital, 'credit': Decimal('25.00')},
            ],
        )
        with self.assertRaisesMessage(ValidationError, 'open accounting periods'):
            post_journal_entry(blocked_journal)

    def test_period_close_requires_no_draft_journals(self):
        entity = self._foundation()
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        capital = ChartOfAccount.objects.get(entity=entity, code='3000')
        create_manual_journal_entry(
            entity,
            date(2026, 1, 5),
            'Unposted funding',
            [
                {'account': cash, 'debit': Decimal('100.00')},
                {'account': capital, 'credit': Decimal('100.00')},
            ],
        )

        preview = build_period_close_preview(period)

        self.assertFalse(preview['can_close'])
        self.assertEqual(preview['draft_journal_count'], 1)
        with self.assertRaisesMessage(ValidationError, 'draft journal'):
            close_accounting_period(period)

    def test_period_reopen_posts_reversal_and_restores_unclosed_earnings(self):
        entity, _cash = self._post_sample_activity()
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)
        close_result = close_accounting_period(period)
        closing_journal = close_result['closing_journal']

        preview = build_period_reopen_preview(period)
        result = reopen_accounting_period(period)
        period.refresh_from_db()
        reversal_journal = result['reversal_journal']

        self.assertTrue(preview['can_reopen'])
        self.assertEqual(period.status, 'open')
        self.assertIsNone(period.closed_at)
        self.assertIsNone(period.closed_by)
        self.assertIsNone(period.closing_journal_entry)
        self.assertEqual(reversal_journal.status, 'posted')
        self.assertEqual(reversal_journal.source_type, 'closing')
        self.assertEqual(reversal_journal.reference, f'REVERSE-{closing_journal.entry_number}')

        income = build_income_statement_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        balance_sheet = build_balance_sheet_report(entity, as_of_date=date(2026, 1, 31))
        trial_balance = build_trial_balance_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        revenue_balance = next(row['balance'] for row in trial_balance['rows'] if row['account'].code == '4000')
        expense_balance = next(row['balance'] for row in trial_balance['rows'] if row['account'].code == '6010')

        self.assertEqual(income['net_income'], Decimal('380.00'))
        self.assertTrue(balance_sheet['uses_unclosed_current_earnings'])
        self.assertEqual(balance_sheet['current_earnings'], Decimal('380.00'))
        self.assertEqual(balance_sheet['totals']['equity'], Decimal('1380.00'))
        self.assertTrue(balance_sheet['is_balanced'])
        self.assertEqual(revenue_balance, Decimal('500.00'))
        self.assertEqual(expense_balance, Decimal('120.00'))

    def test_general_ledger_carries_opening_balance_into_date_range(self):
        entity, cash = self._post_sample_activity()

        report = build_general_ledger_report(
            entity,
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 31),
            account=cash,
        )
        section = report['sections'][0]

        self.assertEqual(section['opening_balance'], Decimal('1000.00'))
        self.assertEqual(section['closing_balance'], Decimal('1380.00'))
        self.assertEqual(len(section['lines']), 2)

    def test_zero_balance_toggle_includes_inactive_statement_accounts(self):
        entity, _cash = self._post_sample_activity()
        bank = ChartOfAccount.objects.get(entity=entity, code='1010')

        trial_balance = build_trial_balance_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            include_zero=True,
        )
        ledger = build_general_ledger_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            account=bank,
            include_zero=True,
        )

        self.assertIn(bank, [row['account'] for row in trial_balance['rows']])
        self.assertEqual(len(ledger['sections']), 1)
        self.assertEqual(ledger['sections'][0]['account'], bank)
        self.assertEqual(ledger['sections'][0]['closing_balance'], Decimal('0.00'))

    def test_cash_flow_and_changes_in_equity_reconcile_to_statements(self):
        entity, _cash = self._post_sample_activity()

        cash_flow = build_cash_flow_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        equity = build_changes_in_equity_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(cash_flow['opening_cash'], Decimal('0.00'))
        self.assertEqual(cash_flow['totals']['operating'], Decimal('380.00'))
        self.assertEqual(cash_flow['totals']['financing'], Decimal('1000.00'))
        self.assertEqual(cash_flow['closing_cash'], Decimal('1380.00'))
        self.assertEqual(cash_flow['difference'], Decimal('0.00'))
        self.assertEqual(equity['opening_equity'], Decimal('0.00'))
        self.assertEqual(equity['equity_account_movement'], Decimal('1000.00'))
        self.assertEqual(equity['period_net_income'], Decimal('380.00'))
        self.assertEqual(equity['ending_equity'], Decimal('1380.00'))
        self.assertEqual(equity['difference'], Decimal('0.00'))

    def test_ar_aging_reconciles_invoice_schedule_to_ar_control(self):
        entity = self._foundation()
        subscriber = Subscriber.objects.create(
            username='aging-client',
            full_name='Aging Client',
            status='active',
            is_billable=True,
        )
        invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            due_date=date(2026, 1, 31),
            amount=Decimal('1000.00'),
            amount_paid=Decimal('250.00'),
            status='partial',
        )
        ar = ChartOfAccount.objects.get(entity=entity, code='1100')
        revenue = ChartOfAccount.objects.get(entity=entity, code='4000')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 15),
            'Invoice AR control',
            [
                {'account': ar, 'debit': Decimal('750.00')},
                {'account': revenue, 'credit': Decimal('750.00')},
            ],
        )
        post_journal_entry(journal_entry)

        report = build_ar_aging_report(entity, as_of_date=date(2026, 3, 15))

        self.assertEqual(invoice.remaining_balance, Decimal('750.00'))
        self.assertEqual(report['totals']['31_60'], Decimal('750.00'))
        self.assertEqual(report['total'], Decimal('750.00'))
        self.assertEqual(report['control_balance'], Decimal('750.00'))
        self.assertEqual(report['control_difference'], Decimal('0.00'))

    def test_ap_aging_reconciles_vendor_schedule_to_ap_control(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        journal_entry = create_manual_journal_entry(
            entity,
            date(2026, 1, 20),
            'Vendor payable',
            [
                {'account': expense, 'debit': Decimal('700.00')},
                {'account': ap, 'credit': Decimal('700.00')},
            ],
        )
        post_journal_entry(journal_entry)
        plan = CutoverPlan.objects.create(entity=entity, cutover_date=date(2026, 1, 1))
        schedule = CutoverBalanceSchedule.objects.create(
            entity=entity,
            cutover_plan=plan,
            schedule_type='accounts_payable',
        )
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=schedule,
            account=ap,
            label='Bandwidth supplier',
            counterparty_name='Upstream Provider',
            statement_date=date(2026, 1, 20),
            source_document_number='BILL-100',
            credit=Decimal('700.00'),
        )

        report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))

        self.assertEqual(report['totals']['31_60'], Decimal('700.00'))
        self.assertEqual(report['total'], Decimal('700.00'))
        self.assertEqual(report['control_balance'], Decimal('700.00'))
        self.assertEqual(report['control_difference'], Decimal('0.00'))

    def test_ap_vendor_bill_subledger_reconciles_to_ap_control(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Upstream Provider',
            'BILL-200',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )

        draft_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))

        self.assertEqual(bill.status, 'draft')
        self.assertEqual(bill.journal_entry.status, 'draft')
        self.assertEqual(draft_report['total'], Decimal('0.00'))

        post_journal_entry(bill.journal_entry)
        bill.refresh_from_db()
        open_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))

        self.assertEqual(open_report['totals']['31_60'], Decimal('700.00'))
        self.assertEqual(open_report['total'], Decimal('700.00'))
        self.assertEqual(open_report['control_balance'], Decimal('700.00'))
        self.assertEqual(open_report['control_difference'], Decimal('0.00'))
        self.assertEqual(open_report['rows'][0]['source'], 'AP vendor bill subledger')

        payment = create_ap_vendor_payment_draft(
            bill,
            date(2026, 2, 5),
            Decimal('200.00'),
            cash,
            reference='CHK-200',
        )
        draft_payment_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))

        self.assertEqual(payment.journal_entry.status, 'draft')
        self.assertEqual(draft_payment_report['total'], Decimal('700.00'))
        self.assertEqual(draft_payment_report['control_balance'], Decimal('700.00'))

        post_journal_entry(payment.journal_entry)
        paid_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))
        bill.refresh_from_db()

        self.assertEqual(paid_report['total'], Decimal('500.00'))
        self.assertEqual(paid_report['control_balance'], Decimal('500.00'))
        self.assertEqual(paid_report['control_difference'], Decimal('0.00'))
        self.assertEqual(APVendorBill.objects.count(), 1)
        self.assertEqual(APVendorPayment.objects.count(), 1)
        self.assertEqual(bill.remaining_balance, Decimal('500.00'))

    def test_ap_vendor_payment_void_uses_reversal_draft_until_posted(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Upstream Provider',
            'BILL-PAY-VOID-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )
        post_journal_entry(bill.journal_entry)
        payment = create_ap_vendor_payment_draft(
            bill,
            date(2026, 2, 5),
            Decimal('200.00'),
            cash,
            reference='CHK-VOID-001',
        )
        post_journal_entry(payment.journal_entry)

        reversal_journal = create_ap_vendor_payment_void_draft(payment, 'Duplicate disbursement')
        pending_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))
        payment.refresh_from_db()

        self.assertEqual(payment.status, 'void_pending')
        self.assertEqual(reversal_journal.status, 'draft')
        self.assertEqual(pending_report['total'], Decimal('500.00'))
        self.assertEqual(pending_report['control_balance'], Decimal('500.00'))
        lines = {line.account.code: line for line in reversal_journal.lines.select_related('account')}
        self.assertEqual(lines['1000'].debit, Decimal('200.00'))
        self.assertEqual(lines['2000'].credit, Decimal('200.00'))

        post_journal_entry(reversal_journal)
        refresh_ap_vendor_payment_status(payment)
        bill.refresh_from_db()
        historical_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))
        voided_report = build_ap_aging_report(entity, as_of_date=timezone.localdate())

        self.assertEqual(payment.status, 'voided')
        self.assertEqual(bill.remaining_balance, Decimal('700.00'))
        self.assertEqual(historical_report['total'], Decimal('500.00'))
        self.assertEqual(historical_report['control_balance'], Decimal('500.00'))
        self.assertEqual(voided_report['total'], Decimal('700.00'))
        self.assertEqual(voided_report['control_balance'], Decimal('700.00'))
        self.assertEqual(voided_report['control_difference'], Decimal('0.00'))

    def test_matched_ap_vendor_payment_requires_clear_before_void(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Matched Supplier',
            'BILL-MATCH-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )
        post_journal_entry(bill.journal_entry)
        payment = create_ap_vendor_payment_draft(
            bill,
            date(2026, 2, 5),
            Decimal('200.00'),
            cash,
            reference='CHK-MATCH-001',
        )
        post_journal_entry(payment.journal_entry)

        match_ap_vendor_payment_settlement(
            payment,
            date(2026, 2, 7),
            'BANK-SETTLEMENT-001',
            settlement_note='Cleared in bank statement',
        )
        payment.refresh_from_db()

        self.assertEqual(payment.settlement_status, 'matched')
        self.assertEqual(payment.settlement_reference, 'BANK-SETTLEMENT-001')
        with self.assertRaises(ValidationError):
            create_ap_vendor_payment_void_draft(payment, 'Should require clearing first')

    def test_ap_vendor_bill_vat_breakdown_posts_input_vat(self):
        entity = create_accounting_foundation(
            entity_name='VAT AP ISP',
            template_key='isp_vat_corporation',
            fiscal_year=2026,
        )['entity']
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'VAT Supplier',
            'BILL-VAT-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('1120.00'),
            tax_treatment='vat',
            base_amount=Decimal('1000.00'),
            input_vat_amount=Decimal('120.00'),
        )

        lines = {line.account.code: line for line in bill.journal_entry.lines.select_related('account')}

        self.assertTrue(bill.journal_entry.is_balanced())
        self.assertEqual(lines['6020'].debit, Decimal('1000.00'))
        self.assertEqual(lines['1200'].debit, Decimal('120.00'))
        self.assertEqual(lines['2000'].credit, Decimal('1120.00'))

    def test_ap_vendor_bill_void_uses_reversal_draft_until_posted(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Upstream Provider',
            'BILL-VOID-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )
        post_journal_entry(bill.journal_entry)

        reversal_journal = create_ap_vendor_bill_void_draft(bill, 'Duplicate supplier bill')
        pending_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))
        bill.refresh_from_db()

        self.assertEqual(bill.status, 'void_pending')
        self.assertEqual(reversal_journal.status, 'draft')
        self.assertEqual(pending_report['total'], Decimal('700.00'))
        self.assertEqual(pending_report['control_balance'], Decimal('700.00'))
        lines = {line.account.code: line for line in reversal_journal.lines.select_related('account')}
        self.assertEqual(lines['2000'].debit, Decimal('700.00'))
        self.assertEqual(lines['6020'].credit, Decimal('700.00'))
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        with self.assertRaises(ValidationError):
            create_ap_vendor_payment_draft(
                bill,
                date(2026, 2, 5),
                Decimal('100.00'),
                cash,
                reference='CHK-BLOCKED',
            )

        post_journal_entry(reversal_journal)
        refresh_ap_vendor_bill_status(bill)
        bill.refresh_from_db()
        historical_report = build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))
        voided_report = build_ap_aging_report(entity, as_of_date=timezone.localdate())

        self.assertEqual(bill.status, 'voided')
        self.assertEqual(historical_report['total'], Decimal('700.00'))
        self.assertEqual(historical_report['control_balance'], Decimal('700.00'))
        self.assertEqual(voided_report['total'], Decimal('0.00'))
        self.assertEqual(voided_report['control_balance'], Decimal('0.00'))
        self.assertEqual(voided_report['control_difference'], Decimal('0.00'))

    def test_draft_ap_vendor_bill_voids_without_reversal(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Draft Supplier',
            'BILL-DRAFT-VOID-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )

        reversal_journal = create_ap_vendor_bill_void_draft(bill, 'Entered in error')
        bill.refresh_from_db()
        bill.journal_entry.refresh_from_db()

        self.assertIsNone(reversal_journal)
        self.assertEqual(bill.status, 'voided')
        self.assertEqual(bill.journal_entry.status, 'voided')
        self.assertEqual(build_ap_aging_report(entity, as_of_date=date(2026, 3, 5))['total'], Decimal('0.00'))

    def test_ap_vendor_master_supplies_bill_snapshot_and_defaults(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        vendor = APVendor.objects.create(
            entity=entity,
            code='UPSTREAM',
            name='Upstream Provider',
            registered_name='Upstream Provider Inc.',
            tax_classification='non_vat',
            default_expense_account=expense,
            default_ap_account=ap,
        )

        bill = create_ap_vendor_bill_draft(
            entity,
            '',
            'BILL-MASTER-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
            vendor=vendor,
        )

        self.assertEqual(bill.vendor, vendor)
        self.assertEqual(bill.vendor_name, 'Upstream Provider Inc.')

    def test_ap_vendor_bill_attachment_stores_file_metadata(self):
        entity = self._foundation()
        ap = ChartOfAccount.objects.get(entity=entity, code='2000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        bill = create_ap_vendor_bill_draft(
            entity,
            'Attachment Supplier',
            'BILL-ATTACH-001',
            date(2026, 1, 20),
            date(2026, 1, 31),
            expense,
            ap,
            Decimal('700.00'),
        )
        payload = b'supplier invoice pdf bytes'
        upload = SimpleUploadedFile('supplier-invoice.pdf', payload, content_type='application/pdf')

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            attachment = create_ap_vendor_bill_attachment(
                bill,
                upload,
                document_type='supplier_invoice',
                note='January bill',
            )
            attachment.refresh_from_db()

            self.assertEqual(APVendorBillAttachment.objects.count(), 1)
            self.assertEqual(attachment.original_filename, 'supplier-invoice.pdf')
            self.assertEqual(attachment.file_size, len(payload))
            self.assertEqual(attachment.sha256, hashlib.sha256(payload).hexdigest())
            self.assertTrue(attachment.file.storage.exists(attachment.file.name))

    def test_tax_ledger_reports_vat_and_optional_2307_claims(self):
        entity = create_accounting_foundation(
            entity_name='VAT Statement ISP',
            template_key='isp_vat_corporation',
            fiscal_year=2026,
        )['entity']
        cash = ChartOfAccount.objects.get(entity=entity, code='1000')
        ar = ChartOfAccount.objects.get(entity=entity, code='1100')
        input_vat = ChartOfAccount.objects.get(entity=entity, code='1200')
        output_vat = ChartOfAccount.objects.get(entity=entity, code='2300')
        revenue = ChartOfAccount.objects.get(entity=entity, code='4000')
        expense = ChartOfAccount.objects.get(entity=entity, code='6020')
        subscriber = Subscriber.objects.create(username='vat-client', full_name='VAT Client')
        for journal_entry in [
            create_manual_journal_entry(
                entity,
                date(2026, 1, 12),
                'VAT sale',
                [
                    {'account': ar, 'debit': Decimal('1120.00')},
                    {'account': revenue, 'credit': Decimal('1000.00')},
                    {'account': output_vat, 'credit': Decimal('120.00')},
                ],
            ),
            create_manual_journal_entry(
                entity,
                date(2026, 1, 18),
                'Input VAT expense',
                [
                    {'account': expense, 'debit': Decimal('500.00')},
                    {'account': input_vat, 'debit': Decimal('60.00')},
                    {'account': cash, 'credit': Decimal('560.00')},
                ],
            ),
        ]:
            post_journal_entry(journal_entry)
        CustomerWithholdingTaxClaim.objects.create(
            entity=entity,
            subscriber=subscriber,
            gross_amount=Decimal('1000.00'),
            tax_withheld=Decimal('20.00'),
            withholding_rate=Decimal('2.0000'),
            atc='WI158',
            period_from=date(2026, 1, 1),
            period_to=date(2026, 1, 31),
            payor_name='Corporate Client',
            status='pending_2307',
        )

        report = build_tax_ledger_report(
            entity,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(report['input_vat'], Decimal('60.00'))
        self.assertEqual(report['output_vat'], Decimal('120.00'))
        self.assertEqual(report['vat_due_estimate'], Decimal('60.00'))
        self.assertEqual(len(report['claim_rows']), 1)
        self.assertEqual(report['claim_rows'][0]['tax_withheld'], Decimal('20.00'))

    def test_financial_statement_pages_export_csv(self):
        entity, cash = self._post_sample_activity()
        user = get_user_model().objects.create_user(
            username='statement-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(user)
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)

        endpoints = [
            (f'/accounting/trial-balance/?period={period.pk}&format=csv', b'account_code'),
            (f'/accounting/trial-balance/?period={period.pk}&include_zero=1&format=csv', b'account_code'),
            ('/accounting/general-ledger/?start=2026-01-01&end=2026-01-31&format=csv', b'account_code'),
            (f'/accounting/general-ledger/?start=2026-01-02&end=2026-01-31&account={cash.pk}&format=csv', b'account_code'),
            ('/accounting/general-ledger/?preset=current_year&include_zero=1&format=csv', b'account_code'),
            ('/accounting/income-statement/?start=2026-01-01&end=2026-01-31&format=csv', b'account_code'),
            ('/accounting/income-statement/?preset=current_year&format=csv', b'account_code'),
            ('/accounting/balance-sheet/?as_of=2026-01-31&format=csv', b'account_code'),
            ('/accounting/balance-sheet/?as_of_preset=current_year_end&format=csv', b'account_code'),
            ('/accounting/cash-flow/?start=2026-01-01&end=2026-01-31&format=csv', b'section'),
            ('/accounting/changes-in-equity/?start=2026-01-01&end=2026-01-31&format=csv', b'account_code'),
            ('/accounting/ar-aging/?as_of=2026-01-31&format=csv', b'subscriber_username'),
            ('/accounting/ap-aging/?as_of=2026-01-31&format=csv', b'vendor_name'),
            ('/accounting/tax-ledger/?start=2026-01-01&end=2026-01-31&format=csv', b'section'),
        ]

        for endpoint, expected_header in endpoints:
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'text/csv')
            self.assertIn('attachment;', response['Content-Disposition'])
            self.assertIn(expected_header, response.content)

    def test_financial_statement_export_package_formats(self):
        entity, _cash = self._post_sample_activity()
        user = get_user_model().objects.create_user(
            username='statement-export-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(user)
        period = AccountingPeriod.objects.get(entity=entity, period_number=1)
        archive_start_count = AccountingReportArchive.objects.filter(entity=entity).count()

        binary_endpoints = [
            (
                f'/accounting/trial-balance/?period={period.pk}&format=xlsx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                b'PK',
            ),
            (
                '/accounting/tax-ledger/?preset=current_year&format=xlsx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                b'PK',
            ),
        ]

        for endpoint, content_type, prefix in binary_endpoints:
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], content_type)
            self.assertIn('attachment;', response['Content-Disposition'])
            self.assertEqual(len(response['X-Report-Data-SHA256']), 64)
            self.assertTrue(response['X-Accounting-Report-Archive-ID'].isdigit())
            self.assertEqual(len(response['X-Accounting-Report-File-SHA256']), 64)
            self.assertTrue(response.content.startswith(prefix))

        manifest_response = self.client.get(
            f'/accounting/trial-balance/?period={period.pk}&format=manifest',
        )
        manifest = json.loads(manifest_response.content.decode('utf-8'))

        self.assertEqual(manifest_response.status_code, 200)
        self.assertEqual(manifest_response['Content-Type'], 'application/json')
        self.assertTrue(manifest_response['X-Accounting-Report-Archive-ID'].isdigit())
        self.assertEqual(len(manifest_response['X-Accounting-Report-File-SHA256']), 64)
        self.assertEqual(manifest['report_name'], 'Trial Balance')
        self.assertEqual(len(manifest['canonical_data']['sha256']), 64)
        self.assertIn('account_code', manifest['columns'])

        pdf_response = self.client.get(
            '/accounting/general-ledger/?preset=current_year&include_zero=1&format=pdf',
        )

        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn(pdf_response['Content-Type'], ('application/pdf', 'text/html'))
        self.assertIn('attachment;', pdf_response['Content-Disposition'])
        self.assertEqual(len(pdf_response['X-Report-Data-SHA256']), 64)
        self.assertTrue(pdf_response['X-Accounting-Report-Archive-ID'].isdigit())
        self.assertEqual(len(pdf_response['X-Accounting-Report-File-SHA256']), 64)
        self.assertTrue(
            pdf_response.content.startswith(b'%PDF')
            or b'General Ledger' in pdf_response.content
        )
        self.assertEqual(
            AccountingReportArchive.objects.filter(entity=entity).count(),
            archive_start_count + 4,
        )

        archive = AccountingReportArchive.objects.get(pk=manifest_response['X-Accounting-Report-Archive-ID'])
        self.assertEqual(archive.report_name, 'Trial Balance')
        self.assertEqual(archive.export_format, 'manifest')
        self.assertEqual(archive.generated_by, user)
        self.assertEqual(archive.canonical_sha256, manifest['canonical_data']['sha256'])
        archive.filename = 'changed.csv'
        with self.assertRaisesMessage(ValidationError, 'immutable'):
            archive.save()


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
        self.assertFalse(readiness['all_passed'])
        self.assertIn(
            'opening_journal_posted',
            [
                item['key']
                for item in readiness['checks']
                if not item['passed'] and item['severity'] == 'error'
            ],
        )

    def _cash_equity_cutover_ready(self, post_opening=False):
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
        validate_opening_balance_import(import_batch)
        journal_entry = create_opening_balance_journal(import_batch)

        cash_schedule = create_cutover_balance_schedule(plan, 'cash_on_hand')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=cash_schedule,
            account=cash,
            label='Cash count',
            debit=Decimal('1000.00'),
        )
        validate_cutover_balance_schedule(cash_schedule)
        equity_schedule = create_cutover_balance_schedule(plan, 'equity_balance')[0]
        CutoverBalanceScheduleLine.objects.create(
            entity=entity,
            schedule=equity_schedule,
            account=capital,
            label='Owner capital',
            credit=Decimal('1000.00'),
            source_document_number='Opening equity worksheet',
        )
        validate_cutover_balance_schedule(equity_schedule)
        if post_opening:
            post_journal_entry(journal_entry)
            journal_entry.refresh_from_db()
        return entity, plan, import_batch, journal_entry, cash

    def test_cutover_ready_requires_posted_opening_journal(self):
        entity, plan, _import_batch, _journal_entry, _cash = self._cash_equity_cutover_ready()

        readiness = build_cutover_readiness(entity)

        self.assertFalse(readiness['all_passed'])
        with self.assertRaisesMessage(ValidationError, 'Opening journal is posted'):
            mark_cutover_ready(plan)

    def test_cutover_approval_live_and_lock_controls(self):
        entity, plan, import_batch, journal_entry, cash = self._cash_equity_cutover_ready(post_opening=True)

        ready = mark_cutover_ready(plan)
        approved = approve_cutover_plan(ready)
        live = mark_accounting_live(approved)
        entity.settings.refresh_from_db()
        import_batch.refresh_from_db()

        self.assertEqual(journal_entry.status, 'posted')
        self.assertEqual(ready.status, 'ready_for_review')
        self.assertEqual(approved.status, 'approved')
        self.assertEqual(live.status, 'live')
        self.assertEqual(entity.settings.setup_status, 'live')
        self.assertEqual(import_batch.status, 'posted')
        with self.assertRaisesMessage(ValidationError, 'locked'):
            OpeningBalanceImport.objects.create(
                entity=entity,
                cutover_plan=live,
                import_type='manual',
            )
        with self.assertRaisesMessage(ValidationError, 'locked'):
            OpeningBalanceLine.objects.create(
                entity=entity,
                import_batch=import_batch,
                account=cash,
                line_type='cash',
                debit=Decimal('1.00'),
            )
        with self.assertRaisesMessage(ValidationError, 'locked'):
            create_cutover_plan(entity, date(2026, 2, 1))


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
