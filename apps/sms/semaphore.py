import requests


SEMAPHORE_API_URL = 'https://api.semaphore.co/api/v4/messages'


def send_sms(number, message, sender_name=None):
    from apps.settings_app.models import SMSSettings
    settings = SMSSettings.get_settings()

    api_key = settings.semaphore_api_key
    if not api_key:
        raise ValueError('Semaphore API key not configured. Go to Settings > SMS.')

    sender = sender_name or settings.sender_name or 'ISPManager'

    payload = {
        'apikey': api_key,
        'number': number,
        'message': message,
        'sendername': sender,
    }

    response = requests.post(SEMAPHORE_API_URL, data=payload, timeout=15)

    if response.status_code != 200:
        raise RuntimeError(f"Semaphore API error {response.status_code}: {response.text}")

    return response.json()


def send_bulk_sms(recipients, message, sender_name=None):
    results = []
    for number in recipients:
        try:
            result = send_sms(number, message, sender_name)
            results.append({'number': number, 'ok': True, 'result': result})
        except Exception as e:
            results.append({'number': number, 'ok': False, 'error': str(e)})
    return results
