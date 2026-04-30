from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.core.models import AuditLog
from apps.nms.models import ServiceAttachment
from apps.settings_app.models import BillingSettings
from apps.subscribers.forms import ManualSubscriberForm, SubscriberAdminForm
from apps.subscribers.models import NetworkNode, Subscriber, SubscriberNode, SubscriberOTP, normalize_phone_digits
from apps.subscribers.otp import create_otp, find_portal_subscriber_by_phone, verify_otp_for_subscriber
from apps.subscribers.services import audit_subscriber_field_changes, get_subscriber_billing_readiness
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

    def test_duplicate_normalized_phone_marks_sms_not_ready(self):
        first = Subscriber.objects.create(
            username='phone-owner-a',
            phone='0917 123 4567',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )
        Subscriber.objects.create(
            username='phone-owner-b',
            phone='+63 917 123 4567',
            monthly_rate=Decimal('1000.00'),
            start_date=date(2026, 4, 29),
            cutoff_day=28,
            billing_type='postpaid',
            status='active',
            is_billable=True,
        )

        readiness = get_subscriber_billing_readiness(
            first,
            billing_settings=self._billing_settings(),
            reference_date=date(2026, 5, 1),
        )

        self.assertFalse(readiness['sms_ready'])
        self.assertIn('Phone number is shared with another subscriber.', readiness['sms_issues'])


class SubscriberPhoneNormalizationTests(TestCase):
    def test_subscriber_save_stores_normalized_phone(self):
        subscriber = Subscriber.objects.create(
            username='normal-phone',
            phone='+63 917 123 4567',
        )

        self.assertEqual(subscriber.normalized_phone, '639171234567')
        self.assertEqual(normalize_phone_digits(subscriber.phone), '639171234567')

    def test_portal_phone_lookup_accepts_formatting(self):
        subscriber = Subscriber.objects.create(
            username='portal-phone',
            phone='0917 123 4567',
        )

        match, error, normalized_phone = find_portal_subscriber_by_phone('+63 917 123 4567')

        self.assertEqual(match, subscriber)
        self.assertIsNone(error)
        self.assertEqual(normalized_phone, '639171234567')

    def test_portal_phone_lookup_blocks_duplicates(self):
        Subscriber.objects.create(username='portal-dup-a', phone='0917 123 4567')
        Subscriber.objects.create(username='portal-dup-b', phone='0917-123-4567')

        match, error, normalized_phone = find_portal_subscriber_by_phone('09171234567')

        self.assertIsNone(match)
        self.assertIn('Multiple accounts use this phone number', error)
        self.assertEqual(normalized_phone, '639171234567')

    def test_portal_phone_lookup_uses_stored_phone_not_stale_normalized_phone(self):
        subscriber = Subscriber.objects.create(
            username='portal-stale-phone',
            phone='09663067637',
        )
        Subscriber.objects.filter(pk=subscriber.pk).update(normalized_phone='639077613830')

        match, error, normalized_phone = find_portal_subscriber_by_phone('09663067637')
        stale_match, stale_error, stale_normalized_phone = find_portal_subscriber_by_phone('09077613830')

        subscriber.refresh_from_db()
        self.assertEqual(match, subscriber)
        self.assertIsNone(error)
        self.assertEqual(normalized_phone, '639663067637')
        self.assertEqual(subscriber.normalized_phone, '639077613830')
        self.assertIsNone(stale_match)
        self.assertEqual(stale_error, 'No account found with this phone number.')
        self.assertEqual(stale_normalized_phone, '639077613830')

        otp = create_otp(match)
        self.assertEqual(otp.normalized_phone, '639663067637')

    def test_otp_verification_uses_pending_subscriber_id(self):
        subscriber = Subscriber.objects.create(
            username='portal-otp',
            phone='0917 123 4567',
        )
        otp = create_otp(subscriber)

        verified, error = verify_otp_for_subscriber(subscriber.pk, otp.code)

        otp.refresh_from_db()
        self.assertEqual(verified, subscriber)
        self.assertIsNone(error)
        self.assertTrue(otp.is_used)
        self.assertEqual(otp.normalized_phone, '639171234567')


class SubscriberNodeAssignmentNmsTests(TestCase):
    def test_basic_node_assignment_creates_first_nms_mapping(self):
        user = User.objects.create_superuser('assign-admin', 'assign@example.test', 'pass')
        subscriber = Subscriber.objects.create(username='assign-client', full_name='Assign Client')
        node = NetworkNode.objects.create(name='NAP-Assign', node_type='splice_box')
        self.client.force_login(user)

        response = self.client.post(
            f'/subscribers/{subscriber.pk}/assign-node/',
            {
                'node_id': str(node.pk),
                'port_label': 'PON-1/1',
            },
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SubscriberNode.objects.filter(
                subscriber=subscriber,
                node=node,
                port_label='PON-1/1',
            ).exists()
        )
        attachment = ServiceAttachment.objects.get(subscriber=subscriber)
        self.assertEqual(attachment.node, node)
        self.assertEqual(attachment.endpoint_label, 'PON-1/1')
        self.assertEqual(attachment.status, 'active')


class SubscriberFieldAuditTests(TestCase):
    def test_field_change_audit_logs_before_and_after_values(self):
        user = User.objects.create_user(username='auditor', password='secret')
        before = Subscriber.objects.create(
            username='audit-client',
            full_name='Old Name',
            cutoff_day=28,
        )
        after = Subscriber.objects.get(pk=before.pk)
        after.full_name = 'New Name'
        after.cutoff_day = 30

        logged = audit_subscriber_field_changes(
            before,
            after,
            ['full_name', 'cutoff_day'],
            user=user,
        )

        descriptions = list(AuditLog.objects.values_list('description', flat=True))
        self.assertEqual(logged, 2)
        self.assertTrue(any("Full name from 'Old Name' to 'New Name'" in item for item in descriptions))
        self.assertTrue(any("Cutoff day from '28' to '30'" in item for item in descriptions))


class SubscriberPermissionTests(TestCase):
    def test_suspend_requires_lifecycle_permission(self):
        user = User.objects.create_user(username='viewer', password='secret')
        subscriber = Subscriber.objects.create(username='permission-client', status='active')
        self.client.force_login(user)

        response = self.client.post(f'/subscribers/{subscriber.pk}/suspend/')

        subscriber.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(subscriber.status, 'active')

    def test_edit_requires_change_permission(self):
        user = User.objects.create_user(username='viewer-edit', password='secret')
        subscriber = Subscriber.objects.create(username='permission-edit', status='active')
        self.client.force_login(user)

        response = self.client.get(f'/subscribers/{subscriber.pk}/edit/')

        self.assertEqual(response.status_code, 302)

    def test_edit_with_change_permission_allows_profile_page(self):
        user = User.objects.create_user(username='editor', password='secret')
        permission = Permission.objects.get(codename='change_subscriber')
        user.user_permissions.add(permission)
        subscriber = Subscriber.objects.create(username='permission-edit-ok', status='active')
        self.client.force_login(user)

        response = self.client.get(f'/subscribers/{subscriber.pk}/edit/')

        self.assertEqual(response.status_code, 200)


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
