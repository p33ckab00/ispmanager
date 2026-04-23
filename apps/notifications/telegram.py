import logging
import time

import requests
from django.utils import timezone
from apps.settings_app.models import TelegramSettings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10
MAX_SEND_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _sleep_before_retry(attempt):
    if attempt >= MAX_SEND_ATTEMPTS:
        return
    time.sleep(2 ** (attempt - 1))


def send_telegram(message):
    settings = TelegramSettings.get_settings()

    if not settings.enable_notifications:
        return False, 'Telegram notifications disabled.'

    if not settings.bot_token or not settings.chat_id:
        return False, 'Telegram bot token or chat ID not configured.'

    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    payload = {
        'chat_id': settings.chat_id,
        'text': message,
        'parse_mode': 'HTML',
    }

    last_error = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return True, None

            last_error = f"Telegram API error: {response.text}"
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_SEND_ATTEMPTS:
                return False, last_error

            logger.warning(
                "Telegram send attempt %s/%s returned %s; retrying.",
                attempt,
                MAX_SEND_ATTEMPTS,
                response.status_code,
            )
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
            if attempt >= MAX_SEND_ATTEMPTS:
                return False, last_error

            logger.warning(
                "Telegram send attempt %s/%s failed with a transient request error; retrying: %s",
                attempt,
                MAX_SEND_ATTEMPTS,
                exc,
            )

        _sleep_before_retry(attempt)

    return False, last_error or 'Telegram send failed.'


def notify(event_type, title, message, check_setting=None):
    from apps.notifications.models import Notification
    from apps.settings_app.models import TelegramSettings

    settings = TelegramSettings.get_settings()

    if check_setting and not getattr(settings, check_setting, True):
        return Notification.objects.create(
            event_type=event_type,
            channel='telegram',
            title=title,
            message=message,
            status='pending',
            error='Skipped because this event type is disabled in Telegram settings.',
            delivery_state='skipped',
            telegram_sent=False,
            last_attempt_at=timezone.now(),
        )

    full_message = f"<b>{title}</b>\n{message}"
    ok, err = send_telegram(full_message)

    notif = Notification.objects.create(
        event_type=event_type,
        channel='telegram',
        title=title,
        message=message,
        status='sent' if ok else 'failed',
        error=err or '',
        retry_count=1,
        last_attempt_at=timezone.now(),
        delivery_state='delivered' if ok else 'failed',
        telegram_sent=ok,
    )

    return notif


EVENTS = {
    'new_subscriber': 'notify_new_subscriber',
    'subscriber_status': 'notify_subscriber_status_change',
    'router_status': 'notify_router_status',
    'billing_generated': 'notify_billing_generated',
    'payment_received': 'notify_payment_received',
    'sms_sent': 'notify_sms_sent',
    'plan_change': 'notify_plan_change',
    'settings_change': 'notify_settings_change',
    'api_error': 'notify_api_errors',
    'system': None,
}


def notify_event(event_type, title, message):
    setting_key = EVENTS.get(event_type)
    return notify(event_type, title, message, check_setting=setting_key)
