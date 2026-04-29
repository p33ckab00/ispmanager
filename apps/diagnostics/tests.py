from unittest.mock import patch

from django.test import TestCase

from apps.diagnostics.models import DiagnosticsIncident
from apps.diagnostics.services import get_incident_resolution_context, resolve_incident
from apps.notifications.models import Notification
from apps.settings_app.models import SMSSettings, TelegramSettings
from apps.sms.models import SMSLog


class DiagnosticsIncidentResolutionTests(TestCase):
    def _telegram_incident(self):
        return DiagnosticsIncident.objects.create(
            key='messaging.telegram.failed_last_24h',
            source='messaging',
            severity='warning',
            title='Telegram delivery failures detected',
            detail='1 Telegram notification failed in the last 24 hours.',
            status='active',
        )

    def _sms_incident(self):
        return DiagnosticsIncident.objects.create(
            key='messaging.sms.failed_today',
            source='messaging',
            severity='warning',
            title='SMS failures detected today',
            detail='1 SMS message failed today.',
            status='active',
        )

    def test_telegram_incident_has_self_heal_and_manual_guide(self):
        incident = self._telegram_incident()

        context = get_incident_resolution_context(incident)

        self.assertTrue(context['self_heal']['available'])
        self.assertEqual(context['self_heal']['button_label'], 'Run Self-Heal')
        self.assertEqual(context['manual_guide']['title'], 'Fix Telegram delivery failures')
        self.assertIn(
            '/settings/telegram/',
            {link['href'] for link in context['manual_guide']['links']},
        )

    @patch('apps.notifications.telegram.send_telegram', return_value=(True, None))
    @patch('apps.diagnostics.services.build_diagnostics_snapshot', return_value={'alerts': []})
    def test_telegram_self_heal_retries_failed_notifications_and_resolves(self, _snapshot, _send):
        TelegramSettings.objects.create(
            pk=1,
            bot_token='token',
            chat_id='12345',
            enable_notifications=True,
        )
        incident = self._telegram_incident()
        notification = Notification.objects.create(
            event_type='system',
            channel='telegram',
            title='Scheduler Error',
            message='Example failure',
            status='failed',
            error='timeout',
            delivery_state='failed',
        )

        result = resolve_incident(incident, resolution_note='Retried Telegram failures.')

        self.assertTrue(result['resolved'])
        notification.refresh_from_db()
        incident.refresh_from_db()
        self.assertEqual(notification.status, 'sent')
        self.assertEqual(notification.retry_count, 1)
        self.assertEqual(incident.status, 'resolved')

    @patch('apps.notifications.telegram.send_telegram', return_value=(False, 'invalid token'))
    @patch(
        'apps.diagnostics.services.build_diagnostics_snapshot',
        return_value={'alerts': [{'key': 'messaging.telegram.failed_last_24h'}]},
    )
    def test_telegram_self_heal_keeps_incident_active_when_retry_still_fails(self, _snapshot, _send):
        TelegramSettings.objects.create(
            pk=1,
            bot_token='bad-token',
            chat_id='12345',
            enable_notifications=True,
        )
        incident = self._telegram_incident()
        notification = Notification.objects.create(
            event_type='system',
            channel='telegram',
            title='Scheduler Error',
            message='Example failure',
            status='failed',
            error='timeout',
            delivery_state='failed',
        )

        result = resolve_incident(incident, resolution_note='Retried Telegram failures.')

        self.assertFalse(result['resolved'])
        notification.refresh_from_db()
        incident.refresh_from_db()
        self.assertEqual(notification.status, 'failed')
        self.assertEqual(notification.retry_count, 1)
        self.assertEqual(notification.error, 'invalid token')
        self.assertEqual(incident.status, 'active')

    @patch('apps.sms.semaphore.send_sms', return_value=[{'status': 'Queued'}])
    @patch('apps.diagnostics.services.build_diagnostics_snapshot', return_value={'alerts': []})
    def test_sms_self_heal_retries_failed_non_otp_logs_and_resolves(self, _snapshot, _send):
        SMSSettings.objects.create(pk=1, semaphore_api_key='sms-key')
        incident = self._sms_incident()
        log = SMSLog.objects.create(
            phone='09171234567',
            message='Billing reminder',
            sms_type='billing',
            status='failed',
            error_message='timeout',
        )

        result = resolve_incident(incident, resolution_note='Retried failed SMS.')

        self.assertTrue(result['resolved'])
        log.refresh_from_db()
        incident.refresh_from_db()
        self.assertEqual(log.status, 'sent')
        self.assertEqual(log.error_message, '')
        self.assertEqual(incident.status, 'resolved')

    @patch('apps.sms.semaphore.send_sms', return_value=[{'status': 'Queued'}])
    @patch(
        'apps.diagnostics.services.build_diagnostics_snapshot',
        return_value={'alerts': [{'key': 'messaging.sms.failed_today'}]},
    )
    def test_sms_self_heal_does_not_retry_otp_logs(self, _snapshot, _send):
        SMSSettings.objects.create(pk=1, semaphore_api_key='sms-key')
        incident = self._sms_incident()
        log = SMSLog.objects.create(
            phone='09171234567',
            message='Your login code is 123456',
            sms_type='otp',
            status='failed',
            error_message='timeout',
        )

        result = resolve_incident(incident, resolution_note='Retried failed SMS.')

        self.assertFalse(result['resolved'])
        _send.assert_not_called()
        log.refresh_from_db()
        incident.refresh_from_db()
        self.assertEqual(log.status, 'failed')
        self.assertEqual(incident.status, 'active')
