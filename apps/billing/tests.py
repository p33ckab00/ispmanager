from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounting.models import ExpenseRecord
from apps.billing.services import (
    apply_disconnected_credit_policy,
    apply_disconnected_billing_policy,
    apply_unallocated_payments_to_invoice,
    complete_refund_credit_adjustment,
    get_current_cutoff_period,
    get_account_credit_for_subscriber,
    get_cutoff_day_queryset_filter,
    get_effective_cutoff_date,
    get_billing_preview_for_subscriber,
    get_billing_snapshot_preparation_date,
    get_next_cutoff_period,
    record_payment_with_allocation,
    resolve_billing_profile,
    should_prepare_billing_snapshot,
)
from apps.billing.models import AccountCreditAdjustment, BillingSnapshot, Invoice, Payment
from apps.settings_app.models import BillingSettings, SubscriberSettings
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

    def test_snapshot_preparation_uses_sms_lead_window_when_enabled(self):
        preview = {
            'errors': [],
            'snapshot': None,
            'generation_date': date(2026, 5, 28),
            'sms': {
                'enabled': True,
                'first_sms_date': date(2026, 5, 25),
            },
        }

        self.assertEqual(get_billing_snapshot_preparation_date(preview), date(2026, 5, 25))
        self.assertTrue(should_prepare_billing_snapshot(preview, date(2026, 5, 25)))

    def test_snapshot_preparation_falls_back_to_generation_date_without_sms(self):
        preview = {
            'errors': [],
            'snapshot': None,
            'generation_date': date(2026, 5, 28),
            'sms': {
                'enabled': False,
                'first_sms_date': date(2026, 5, 25),
            },
        }

        self.assertEqual(get_billing_snapshot_preparation_date(preview), date(2026, 5, 28))
        self.assertFalse(should_prepare_billing_snapshot(preview, date(2026, 5, 25)))


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
            start_date=date(2026, 4, 29),
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
            start_date=date(2026, 4, 29),
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
            start_date=date(2026, 4, 29),
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


class BillingAutoReconnectTests(TestCase):
    def test_full_payment_reconnects_suspended_subscriber_when_enabled(self):
        SubscriberSettings.objects.update_or_create(
            pk=1,
            defaults={
                'auto_reconnect_after_full_payment': True,
                'mikrotik_auto_reconnect': False,
            },
        )
        subscriber = Subscriber.objects.create(
            username='auto-reconnect-paid',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='suspended',
            is_billable=True,
        )
        Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='overdue',
        )

        with self.captureOnCommitCallbacks(execute=True):
            payment, remaining = record_payment_with_allocation(
                subscriber,
                Decimal('1000.00'),
                recorded_by='tester',
            )

        subscriber.refresh_from_db()
        self.assertEqual(remaining, Decimal('0.00'))
        self.assertEqual(subscriber.status, 'active')
        self.assertTrue(payment.auto_reconnect_result['reconnected'])
        self.assertIn('MikroTik auto-reconnect is disabled', payment.auto_reconnect_result['warning'])

    def test_partial_payment_does_not_reconnect_suspended_subscriber(self):
        SubscriberSettings.objects.update_or_create(
            pk=1,
            defaults={'auto_reconnect_after_full_payment': True},
        )
        subscriber = Subscriber.objects.create(
            username='auto-reconnect-partial',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='suspended',
            is_billable=True,
        )
        Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='overdue',
        )

        with self.captureOnCommitCallbacks(execute=True):
            payment, remaining = record_payment_with_allocation(
                subscriber,
                Decimal('400.00'),
                recorded_by='tester',
            )

        subscriber.refresh_from_db()
        self.assertEqual(remaining, Decimal('0.00'))
        self.assertEqual(subscriber.status, 'suspended')
        self.assertFalse(payment.auto_reconnect_result['attempted'])
        self.assertEqual(payment.auto_reconnect_result['remaining_balance'], Decimal('600.00'))


class DisconnectedBillingPolicyTests(TestCase):
    def test_preserve_balance_policy_leaves_open_invoices_unchanged(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-preserve',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='overdue',
        )

        result = apply_disconnected_billing_policy(subscriber, policy='preserve_balance')

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'overdue')
        self.assertEqual(result['message'], 'Existing balances preserved.')

    def test_waive_policy_marks_open_balances_waived(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-waive',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        open_invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='open',
        )
        paid_invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 3, 29),
            period_end=date(2026, 4, 28),
            due_date=date(2026, 4, 28),
            amount=Decimal('1000.00'),
            amount_paid=Decimal('1000.00'),
            status='paid',
        )

        result = apply_disconnected_billing_policy(
            subscriber,
            policy='waive_open_balances',
            disconnected_by='tester',
        )

        open_invoice.refresh_from_db()
        paid_invoice.refresh_from_db()
        self.assertEqual(result['waived_count'], 1)
        self.assertEqual(open_invoice.status, 'waived')
        self.assertEqual(open_invoice.voided_by, 'tester')
        self.assertEqual(paid_invoice.status, 'paid')

    def test_final_invoice_policy_generates_current_invoice(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-final',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )

        result = apply_disconnected_billing_policy(
            subscriber,
            policy='final_invoice',
            reference_date=date(2026, 5, 10),
        )

        self.assertTrue(result['final_invoice_created'])
        self.assertEqual(result['final_invoice'].period_start, date(2026, 4, 29))
        self.assertEqual(result['final_invoice'].period_end, date(2026, 5, 28))


class DisconnectedCreditPolicyTests(TestCase):
    def test_preserve_credit_policy_leaves_available_credit_unchanged(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-credit-preserve',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('300.00'),
            method='cash',
            paid_at=timezone.now(),
        )

        result = apply_disconnected_credit_policy(subscriber, policy='preserve_credit')

        self.assertEqual(result['available_credit'], Decimal('300.00'))
        self.assertEqual(get_account_credit_for_subscriber(subscriber), Decimal('300.00'))
        self.assertEqual(AccountCreditAdjustment.objects.count(), 0)

    def test_mark_refund_due_reserves_remaining_credit(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-credit-refund',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('300.00'),
            method='cash',
            paid_at=timezone.now(),
        )

        result = apply_disconnected_credit_policy(
            subscriber,
            policy='mark_refund_due',
            disconnected_by='tester',
        )

        adjustment = AccountCreditAdjustment.objects.get()
        self.assertEqual(result['available_credit'], Decimal('300.00'))
        self.assertEqual(result['adjustment'], adjustment)
        self.assertEqual(adjustment.adjustment_type, 'refund_due')
        self.assertEqual(adjustment.status, 'pending')
        self.assertEqual(adjustment.amount, Decimal('300.00'))
        self.assertEqual(adjustment.recorded_by, 'tester')
        self.assertEqual(get_account_credit_for_subscriber(subscriber), Decimal('0.00'))

    def test_forfeited_credit_is_not_auto_applied_to_future_invoice(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-credit-forfeit',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('300.00'),
            method='cash',
            paid_at=timezone.now(),
        )
        apply_disconnected_credit_policy(
            subscriber,
            policy='forfeit_credit',
            disconnected_by='tester',
        )
        invoice = Invoice.objects.create(
            subscriber=subscriber,
            period_start=date(2026, 4, 29),
            period_end=date(2026, 5, 28),
            due_date=date(2026, 5, 28),
            amount=Decimal('1000.00'),
            status='open',
        )

        applied = apply_unallocated_payments_to_invoice(invoice)

        invoice.refresh_from_db()
        adjustment = AccountCreditAdjustment.objects.get()
        self.assertEqual(applied, Decimal('0.00'))
        self.assertEqual(invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(adjustment.adjustment_type, 'forfeit')
        self.assertEqual(adjustment.status, 'completed')

    def test_complete_refund_due_marks_paid_and_creates_expense(self):
        subscriber = Subscriber.objects.create(
            username='disconnect-credit-complete-refund',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='disconnected',
            is_billable=True,
        )
        Payment.objects.create(
            subscriber=subscriber,
            amount=Decimal('300.00'),
            method='cash',
            paid_at=timezone.now(),
        )
        refund_due = apply_disconnected_credit_policy(
            subscriber,
            policy='mark_refund_due',
            disconnected_by='tester',
        )['adjustment']

        completed, expense = complete_refund_credit_adjustment(
            refund_due,
            reference='GCASH-123',
            notes='Refund sent to customer.',
            completed_by='cashier',
            paid_at=timezone.now(),
            create_expense=True,
        )

        completed.refresh_from_db()
        self.assertEqual(completed.adjustment_type, 'refund_paid')
        self.assertEqual(completed.status, 'completed')
        self.assertEqual(completed.reference, 'GCASH-123')
        self.assertEqual(completed.expense_record, expense)
        self.assertEqual(expense.amount, Decimal('300.00'))
        self.assertEqual(expense.category, 'other')
        self.assertEqual(ExpenseRecord.objects.count(), 1)
        self.assertEqual(get_account_credit_for_subscriber(subscriber), Decimal('0.00'))
