from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from apps.notifications.telegram import send_telegram
from apps.settings_app.models import TelegramSettings


class TelegramSendTests(TestCase):
    def setUp(self):
        settings = TelegramSettings.get_settings()
        settings.enable_notifications = True
        settings.bot_token = 'test-token'
        settings.chat_id = '123456'
        settings.save()

    @patch('apps.notifications.telegram.time.sleep', return_value=None)
    @patch('apps.notifications.telegram.requests.post')
    def test_retries_transient_connection_errors(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            requests.exceptions.ConnectionError('Temporary failure in name resolution'),
            Mock(status_code=200),
        ]

        ok, err = send_telegram('hello')

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch('apps.notifications.telegram.time.sleep', return_value=None)
    @patch('apps.notifications.telegram.requests.post')
    def test_does_not_retry_non_retryable_api_error(self, mock_post, mock_sleep):
        mock_post.return_value = Mock(status_code=400, text='Bad Request')

        ok, err = send_telegram('hello')

        self.assertFalse(ok)
        self.assertEqual(err, 'Telegram API error: Bad Request')
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()
