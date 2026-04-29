from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.billing.services import (
    get_current_cutoff_period,
    get_cutoff_day_queryset_filter,
    get_effective_cutoff_date,
    get_billing_preview_for_subscriber,
    get_next_cutoff_period,
    resolve_billing_profile,
)
from apps.billing.models import BillingSnapshot, Invoice, Payment
from apps.settings_app.models import BillingSettings
from apps.subscribers.models import Subscriber


class BillingCutoffPeriodTests(SimpleTestCase):
    def test_effective_cutoff_uses_month_end_when_configured_day_is_missing(self):
        self.assertEqual(get_effective_cutoff_date(30, 2026, 2), date(2026, 2, 28))
        self.assertEqual(get_effective_cutoff_date(30, 2028, 2), date(2028, 2, 29))
        self.assertEqual(get_effective_cutoff_date(31, 2026, 4), date(2026, 4, 30))
        self.assertEqual(get_effective_cutoff_date(31, 2026, 5), date(2026, 5, 31))

    def test_postpaid_period_contains_effective_cutoff_date(self):
        period_start, period_end = get_current_cutoff_period(30, date(2026, 2, 28))
        self.assertEqual(period_start, date(2026, 1, 31))
        self.assertEqual(period_end, date(2026, 2, 28))

    def test_prepaid_advance_period_moves_forward_on_effective_cutoff_date(self):
        period_start, period_end = get_next_cutoff_period(30, date(2026, 2, 28))
        self.assertEqual(period_start, date(2026, 3, 1))
        self.assertEqual(period_end, date(2026, 3, 30))

    def test_cutoff_filter_includes_month_end_fallback_cutoffs(self):
        settings = BillingSettings(billing_day=30)

        query = get_cutoff_day_queryset_filter(28, settings, date(2026, 2, 28))

        self.assertIn(('cutoff_day__in', [28, 29, 30, 31]), query.children)
        self.assertIn(('cutoff_day__isnull', True), query.children)

    def test_postpaid_profile_due_date_defaults_to_period_end(self):
        settings = BillingSettings(billing_day=1, due_days=0, billing_due_offset_days=0)
        subscriber = Subscriber(username='postpaid', cutoff_day=28, billing_type='postpaid')

        profile = resolve_billing_profile(subscriber, settings, date(2026, 5, 25))

        self.assertEqual(profile['billing_type'], 'postpaid')
        self.assertEqual(profile['period_start'], date(2026, 4, 29))
        self.assertEqual(profile['period_end'], date(2026, 5, 28))
        self.assertEqual(profile['cutoff_date'], date(2026, 5, 28))
        self.assertEqual(profile['generation_date'], date(2026, 5, 28))
        self.assertEqual(profile['due_date'], date(2026, 5, 28))

    def test_prepaid_profile_due_date_defaults_to_period_start(self):
        settings = BillingSettings(billing_day=1, due_days=0, billing_due_offset_days=0)
        subscriber = Subscriber(username='prepaid', cutoff_day=28, billing_type='prepaid')

        profile = resolve_billing_profile(subscriber, settings, date(2026, 5, 28))

        self.assertEqual(profile['billing_type'], 'prepaid')
        self.assertEqual(profile['period_start'], date(2026, 5, 29))
        self.assertEqual(profile['period_end'], date(2026, 6, 28))
        self.assertEqual(profile['cutoff_date'], date(2026, 6, 28))
        self.assertEqual(profile['generation_date'], date(2026, 5, 28))
        self.assertEqual(profile['due_date'], date(2026, 5, 29))


class BillingPreviewTests(TestCase):
    def _billing_settings(self):
        return BillingSettings(billing_day=1, due_days=0, billing_due_offset_days=0)

    def _sms_settings(self):
        from apps.settings_app.models import SMSSettings
        return SMSSettings(enable_billing_sms=True, billing_sms_days_before_due=3)

    def test_preview_computes_unissued_bill_without_writing_records(self):
        subscriber = Subscriber.objects.create(
            username='preview-postpaid',
            phone='09171234567',
            monthly_rate=Decimal('1000.00'),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
        )

        preview = get_billing_preview_for_subscriber(
            subscriber,
            billing_settings=self._billing_settings(),
            sms_settings=self._sms_settings(),
            reference_date=date(2026, 5, 25),
        )

        self.assertTrue(preview['can_generate'])
        self.assertEqual(preview['period_start'], date(2026, 4, 29))
        self.assertEqual(preview['period_end'], date(2026, 5, 28))
        self.assertEqual(preview['generation_date'], date(2026, 5, 28))
        self.assertEqual(preview['due_date'], date(2026, 5, 28))
        self.assertEqual(preview['current_charge'], Decimal('1000.00'))
        self.assertEqual(preview['total_due'], Decimal('1000.00'))
        self.assertEqual(preview['invoice_status'], 'missing')
        self.assertEqual(preview['snapshot_status'], 'missing')
        self.assertEqual(preview['sms']['first_sms_date'], date(2026, 5, 25))
        self.assertEqual(preview['sms']['skip_reason'], 'frozen_snapshot_missing')
        self.assertEqual(Invoice.objects.count(), 0)

    def test_preview_applies_unallocated_payment_as_account_credit(self):
        subscriber = Subscriber.objects.create(
            username='preview-credit',
            phone='09171234567',
            monthly_rate=Decimal('1000.00'),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
        )
        Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 3, 29),
            period_end=date(2026, 4, 28),
            due_date=date(2026, 4, 28),
            amount=Decimal('500.00'),
            amount_paid=Decimal('100.00'),
            status='partial',
        )
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('300.00'),
            method='cash',
            paid_at=timezone.now(),
        )

        preview = get_billing_preview_for_subscriber(
            subscriber,
            billing_settings=self._billing_settings(),
            sms_settings=self._sms_settings(),
            reference_date=date(2026, 5, 25),
        )

        self.assertEqual(preview['previous_balance'], Decimal('400.00'))
        self.assertEqual(preview['account_credit'], Decimal('300.00'))
        self.assertEqual(preview['credit_applied'], Decimal('300.00'))
        self.assertEqual(preview['total_due'], Decimal('1100.00'))
        self.assertIn('has_account_credit', preview['flags'])

    def test_preview_marks_sms_eligible_when_frozen_snapshot_is_ready(self):
        subscriber = Subscriber.objects.create(
            username='preview-sms',
            phone='09171234567',
            monthly_rate=Decimal('1000.00'),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
        )
        invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='open',
        )
        BillingSnapshot.objects.create(
            subscriber=subscriber,
            cutoff_date=date(2026, 5, 28),
            issue_date=date(2026, 5, 25),
            due_date=date(2026, 5, 28),
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            current_cycle_amount=Decimal('1000.00'),
            previous_balance_amount=Decimal('0.00'),
            credit_amount=Decimal('0.00'),
            total_due_amount=Decimal('1000.00'),
            status='frozen',
        )

        preview = get_billing_preview_for_subscriber(
            subscriber,
            billing_settings=self._billing_settings(),
            sms_settings=self._sms_settings(),
            reference_date=date(2026, 5, 25),
        )

        self.assertEqual(preview['invoice'], invoice)
        self.assertTrue(preview['sms']['eligible_today'])
        self.assertEqual(preview['sms']['skip_reason'], '')
        self.assertIn('sms_eligible_today', preview['flags'])
