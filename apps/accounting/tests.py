from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounting.models import (
    AccountingPeriod,
    AccountingSourcePosting,
    ChartOfAccount,
    CustomerWithholdingAllocation,
    CustomerWithholdingTaxClaim,
    JournalLine,
    SourceDocumentLink,
)
from apps.accounting.services import (
    create_accounting_foundation,
    create_invoice_source_draft,
    create_manual_journal_entry,
    create_payment_source_draft,
    post_journal_entry,
)
from apps.billing.models import Invoice, Payment, PaymentAllocation
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
