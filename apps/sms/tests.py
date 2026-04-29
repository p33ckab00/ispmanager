from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.sms.services import (
    get_billing_sms_schedule_state,
    get_billing_sms_send_dates,
)


class BillingSMSScheduleTests(SimpleTestCase):
    def _settings(self):
        return SimpleNamespace(
            enable_billing_sms=True,
            billing_sms_days_before_due=3,
            billing_sms_repeat_interval_days=2,
            billing_sms_send_after_due=False,
            billing_sms_after_due_interval_days=2,
        )

    def _settings_with_after_due(self):
        settings = self._settings()
        settings.billing_sms_send_after_due = True
        return settings

    def _subscriber(self):
        return SimpleNamespace(sms_opt_out=False, phone='09171234567')

    def test_send_dates_include_repeat_dates_and_due_date(self):
        send_dates = get_billing_sms_send_dates(
            due_date=date(2026, 5, 28),
            days_before_due=3,
            repeat_interval_days=2,
        )

        self.assertEqual(
            send_dates,
            [
                date(2026, 5, 25),
                date(2026, 5, 27),
                date(2026, 5, 28),
            ],
        )

    def test_schedule_state_marks_repeat_day_eligible(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('1000.00'),
            sms_settings=self._settings(),
            reference_date=date(2026, 5, 27),
        )

        self.assertTrue(state['eligible_today'])
        self.assertEqual(state['reminder_stage'], 2)
        self.assertEqual(state['skip_reason'], '')

    def test_schedule_state_skips_unscheduled_window_day(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('1000.00'),
            sms_settings=self._settings(),
            reference_date=date(2026, 5, 26),
        )

        self.assertFalse(state['eligible_today'])
        self.assertEqual(state['skip_reason'], 'outside_sms_window')
        self.assertEqual(state['next_sms_date'], date(2026, 5, 27))

    def test_schedule_state_skips_paid_or_credit_covered(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('0.00'),
            sms_settings=self._settings(),
            reference_date=date(2026, 5, 25),
        )

        self.assertFalse(state['eligible_today'])
        self.assertEqual(state['skip_reason'], 'paid_or_credit_covered')

    def test_schedule_state_skips_after_due_when_disabled(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('1000.00'),
            sms_settings=self._settings(),
            reference_date=date(2026, 5, 30),
        )

        self.assertFalse(state['eligible_today'])
        self.assertEqual(state['skip_reason'], 'after_due_date')

    def test_schedule_state_allows_after_due_interval_when_enabled(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('1000.00'),
            sms_settings=self._settings_with_after_due(),
            reference_date=date(2026, 5, 30),
        )

        self.assertTrue(state['eligible_today'])
        self.assertEqual(state['skip_reason'], '')

    def test_schedule_state_skips_after_due_off_interval_day(self):
        subscriber = self._subscriber()
        snapshot = SimpleNamespace(status='frozen', pk=None, subscriber=subscriber)

        state = get_billing_sms_schedule_state(
            snapshot=snapshot,
            subscriber=subscriber,
            due_date=date(2026, 5, 28),
            total_due=Decimal('1000.00'),
            sms_settings=self._settings_with_after_due(),
            reference_date=date(2026, 5, 29),
        )

        self.assertFalse(state['eligible_today'])
        self.assertEqual(state['skip_reason'], 'outside_sms_window')
        self.assertEqual(state['next_sms_date'], date(2026, 5, 30))
