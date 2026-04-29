import random
import string
from django.utils import timezone
from datetime import timedelta
from apps.subscribers.models import Subscriber, SubscriberOTP, normalize_phone_digits


def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))


def create_otp(subscriber):
    code = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=10)
    normalized_phone = normalize_phone_digits(subscriber.phone)

    SubscriberOTP.objects.filter(
        subscriber=subscriber,
        is_used=False,
    ).update(is_used=True)

    otp = SubscriberOTP.objects.create(
        subscriber=subscriber,
        phone=subscriber.phone,
        normalized_phone=normalized_phone,
        code=code,
        expires_at=expires_at,
    )
    return otp


def find_portal_subscriber_by_phone(phone):
    normalized_phone = normalize_phone_digits(phone)
    if not normalized_phone or len(normalized_phone) < 10:
        return None, 'Enter a valid phone number.', normalized_phone

    matches = []
    subscribers = Subscriber.objects.exclude(
        phone='',
    ).exclude(
        status__in=['deceased', 'archived'],
    ).only(
        'pk', 'username', 'phone',
    ).order_by('username')

    for subscriber in subscribers.iterator():
        if normalize_phone_digits(subscriber.phone) != normalized_phone:
            continue
        matches.append(subscriber)
        if len(matches) >= 2:
            break

    if not matches:
        return None, 'No account found with this phone number.', normalized_phone
    if len(matches) > 1:
        return None, 'Multiple accounts use this phone number. Please contact support to update the account phone numbers.', normalized_phone

    return matches[0], None, normalized_phone


def verify_otp_for_subscriber(subscriber_id, code):
    try:
        subscriber = Subscriber.objects.get(pk=subscriber_id)
    except Subscriber.DoesNotExist:
        return None, 'No subscriber found for this OTP request.'

    otp = SubscriberOTP.objects.filter(
        subscriber=subscriber,
        code=code,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).first()

    if not otp:
        return None, 'Invalid or expired OTP.'

    otp.is_used = True
    otp.save()

    return subscriber, None


def verify_otp(phone, code):
    subscriber, error, _ = find_portal_subscriber_by_phone(phone)
    if error:
        return None, error
    return verify_otp_for_subscriber(subscriber.pk, code)
