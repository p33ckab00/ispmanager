import random
import string
from django.utils import timezone
from datetime import timedelta
from apps.subscribers.models import Subscriber, SubscriberOTP


def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))


def create_otp(subscriber):
    code = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=10)

    SubscriberOTP.objects.filter(
        subscriber=subscriber,
        is_used=False,
    ).update(is_used=True)

    otp = SubscriberOTP.objects.create(
        subscriber=subscriber,
        phone=subscriber.phone,
        code=code,
        expires_at=expires_at,
    )
    return otp


def verify_otp(phone, code):
    try:
        subscriber = Subscriber.objects.get(phone=phone)
    except Subscriber.DoesNotExist:
        return None, 'No subscriber found with this phone number.'

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
