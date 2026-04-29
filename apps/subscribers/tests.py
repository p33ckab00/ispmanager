from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.settings_app.models import BillingSettings
from apps.subscribers.forms import ManualSubscriberForm, SubscriberAdminForm
from apps.subscribers.models import Subscriber
from apps.subscribers.services import get_subscriber_billing_readiness
from apps.subscribers.services import set_subscriber_mikrotik_access, transition_subscriber_status


class MikroTikServiceAccessTests(SimpleTestCase):
    def _subscriber(self, service_type, **overrides):
        data = {
            'router': object(),
            'username': 'client-001',
            'service_type': service_type,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'ip_address': '192.0.2.10',
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    @patch('apps.subscribers.services.mikrotik.set_ppp_secret_disabled', return_value=(True, None))
    def test_pppoe_access_uses_ppp_secret(self, helper):
        subscriber = self._subscriber('pppoe')

        ok, err = set_subscriber_mikrotik_access(subscriber, disabled=True)

        self.assertTrue(ok)
        self.assertIsNone(err)
        helper.assert_called_once_with(subscriber.router, subscriber.username, disabled=True)

    @patch('apps.subscribers.services.mikrotik.set_hotspot_user_disabled', return_value=(True, None))
    def test_hotspot_access_uses_hotspot_user(self, helper):
        subscriber = self._subscriber('hotspot')

        ok, err = set_subscriber_mikrotik_access(subscriber, disabled=False)

        self.assertTrue(ok)
        self.assertIsNone(err)
        helper.assert_called_once_with(subscriber.router, subscriber.username, disabled=False)

    @patch('apps.subscribers.services.mikrotik.set_dhcp_lease_disabled', return_value=(True, None))
    def test_dhcp_access_uses_lease_identifiers(self, helper):
        subscriber = self._subscriber('dhcp')

        ok, err = set_subscriber_mikrotik_access(subscriber, disabled=True)

        self.assertTrue(ok)
        self.assertIsNone(err)
        helper.assert_called_once_with(
            subscriber.router,
            username=subscriber.username,
            mac_address=subscriber.mac_address,
            ip_address=subscriber.ip_address,
            disabled=True,
        )

    def test_static_access_returns_explicit_policy_warning(self):
        subscriber = self._subscriber('static')

        ok, err = set_subscriber_mikrotik_access(subscriber, disabled=True)

        self.assertFalse(ok)
        self.assertIn('Static subscriber auto-suspend is not configured', err)


class SubscriberBillingReadinessTests(TestCase):
    def _billing_settings(self):
        return BillingSettings(billing_day=28)

    def test_ready_for_billing_can_still_need_sms_setup(self):
        subscriber = Subscriber(
            username='ready-no-phone',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )

        readiness = get_subscriber_billing_readiness(
            subscriber,
            billing_settings=self._billing_settings(),
            reference_date=date(2026, 5, 1),
        )

        self.assertTrue(readiness['billing_ready'])
        self.assertFalse(readiness['sms_ready'])
        self.assertIn('Missing phone number.', readiness['sms_issues'])

    def test_missing_rate_and_start_date_blocks_billing(self):
        subscriber = Subscriber(
            username='not-ready',
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )

        readiness = get_subscriber_billing_readiness(
            subscriber,
            billing_settings=self._billing_settings(),
            reference_date=date(2026, 5, 1),
        )

        self.assertFalse(readiness['billing_ready'])
        self.assertIn('Missing plan or monthly rate.', readiness['billing_issues'])
        self.assertIn('Missing service start date or billing effective date.', readiness['billing_issues'])


class ManualSubscriberFormTests(TestCase):
    def test_billable_manual_subscriber_requires_rate_and_start(self):
        form = ManualSubscriberForm(data={
            'username': 'manual-billable',
            'service_type': 'pppoe',
            'billing_type': 'postpaid',
            'status': 'active',
            'is_billable': 'on',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('Billable subscribers need a plan or monthly rate.', form.non_field_errors())

    def test_nonbillable_manual_subscriber_can_be_saved_for_onboarding(self):
        form = ManualSubscriberForm(data={
            'username': 'manual-onboarding',
            'service_type': 'pppoe',
            'billing_type': 'postpaid',
            'status': 'inactive',
        })

        self.assertTrue(form.is_valid(), form.errors.as_text())


class SubscriberStatusTransitionTests(TestCase):
    def test_generic_transition_rejects_terminal_status_changes(self):
        subscriber = Subscriber.objects.create(
            username='terminal-account',
            status='disconnected',
            disconnected_date=date(2026, 4, 29),
        )

        ok, err = transition_subscriber_status(
            subscriber,
            'active',
            changed_by='tester',
        )

        subscriber.refresh_from_db()
        self.assertFalse(ok)
        self.assertIn('dedicated workflow', err)
        self.assertEqual(subscriber.status, 'disconnected')

    def test_deactivate_transition_clears_active_palugit(self):
        subscriber = Subscriber.objects.create(
            username='deactivate-me',
            status='active',
            suspension_hold_until=timezone.make_aware(timezone.datetime(2026, 5, 1, 8, 0)),
            suspension_hold_reason='Promise to pay',
            suspension_hold_by='admin',
        )

        ok, err = transition_subscriber_status(
            subscriber,
            'inactive',
            changed_by='tester',
        )

        subscriber.refresh_from_db()
        self.assertEqual(subscriber.status, 'inactive')
        self.assertIsNone(subscriber.suspension_hold_until)
        self.assertEqual(subscriber.suspension_hold_reason, '')
        self.assertEqual(subscriber.suspension_hold_by, '')
        self.assertFalse(ok)
        self.assertIn('No router assigned', err)

    def test_admin_form_blocks_terminal_status_change(self):
        subscriber = Subscriber.objects.create(
            username='form-terminal',
            status='deceased',
            deceased_date=date(2026, 4, 29),
        )
        form = SubscriberAdminForm(
            data={
                'full_name': '',
                'phone': '',
                'address': '',
                'email': '',
                'cutoff_day': '',
                'billing_type': 'postpaid',
                'billing_due_days': '',
                'is_billable': '',
                'start_date': '',
                'status': 'active',
                'notes': '',
            },
            instance=subscriber,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('status', form.errors)
