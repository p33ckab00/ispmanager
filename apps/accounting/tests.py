from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounting.models import (
    AccountingPeriod,
    ChartOfAccount,
    JournalLine,
)
from apps.accounting.services import (
    create_accounting_foundation,
    create_manual_journal_entry,
    post_journal_entry,
)


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
