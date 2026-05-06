from dataclasses import dataclass
from datetime import timedelta
from ipaddress import ip_address
import secrets
import string

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from apps.settings_app.models import SubscriberSettings
from apps.subscribers.models import Subscriber, SubscriberOTP, normalize_phone_digits


GENERIC_OTP_REQUEST_MESSAGE = 'If the account is eligible, an OTP has been sent. Please check your phone.'
GENERIC_OTP_VERIFY_ERROR = 'Invalid, expired, or temporarily locked OTP.'
PORTAL_OTP_ELIGIBLE_STATUSES = ('active', 'suspended')


@dataclass
class OTPRequestResult:
    ok: bool = False
    otp: SubscriberOTP | None = None
    raw_code: str = ''
    error: str = ''
    expires_at: object | None = None
    resend_available_at: object | None = None
    locked_until: object | None = None
    throttled: bool = False


def _clamp(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def get_portal_otp_policy(settings_obj=None):
    settings_obj = settings_obj or SubscriberSettings.get_settings()
    return {
        'expiry_minutes': _clamp(
            getattr(settings_obj, 'portal_otp_expiry_minutes', 10),
            10,
            1,
            60,
        ),
        'resend_cooldown_seconds': _clamp(
            getattr(settings_obj, 'portal_otp_resend_cooldown_seconds', 60),
            60,
            10,
            3600,
        ),
        'max_verify_attempts': _clamp(
            getattr(settings_obj, 'portal_otp_max_verify_attempts', 5),
            5,
            1,
            20,
        ),
        'lockout_minutes': _clamp(
            getattr(settings_obj, 'portal_otp_lockout_minutes', 15),
            15,
            1,
            1440,
        ),
        'phone_hourly_limit': _clamp(
            getattr(settings_obj, 'portal_otp_phone_hourly_limit', 5),
            5,
            1,
            100,
        ),
        'ip_hourly_limit': _clamp(
            getattr(settings_obj, 'portal_otp_ip_hourly_limit', 30),
            30,
            1,
            1000,
        ),
    }


def generate_otp(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def normalize_request_ip(value):
    value = (value or '').split(',')[0].strip()
    if not value:
        return None
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    remote = request.META.get('REMOTE_ADDR')
    return normalize_request_ip(forwarded or remote)


def get_user_agent(request):
    return (request.META.get('HTTP_USER_AGENT') or '')[:1000]


def _latest_otp_for_phone(normalized_phone):
    if not normalized_phone:
        return None
    return SubscriberOTP.objects.filter(
        normalized_phone=normalized_phone,
    ).order_by('-created_at').first()


def _latest_active_otp_for_subscriber(subscriber_id):
    if not subscriber_id:
        return None
    return SubscriberOTP.objects.filter(
        subscriber_id=subscriber_id,
        is_used=False,
    ).order_by('-created_at').first()


def get_resend_available_at(normalized_phone, policy=None):
    policy = policy or get_portal_otp_policy()
    latest_otp = _latest_otp_for_phone(normalized_phone)
    if not latest_otp:
        return None
    return latest_otp.created_at + timedelta(seconds=policy['resend_cooldown_seconds'])


def get_otp_session_timing(subscriber_id=None, normalized_phone='', policy=None):
    policy = policy or get_portal_otp_policy()
    now = timezone.now()
    otp = _latest_active_otp_for_subscriber(subscriber_id) or _latest_otp_for_phone(normalized_phone)
    expires_at = otp.expires_at if otp and not otp.is_used else None
    resend_available_at = (
        otp.created_at + timedelta(seconds=policy['resend_cooldown_seconds'])
        if otp
        else None
    )
    seconds_remaining = (
        max(0, int((expires_at - now).total_seconds()))
        if expires_at
        else 0
    )
    resend_seconds_remaining = (
        max(0, int((resend_available_at - now).total_seconds()))
        if resend_available_at
        else 0
    )
    return {
        'expires_at': expires_at,
        'resend_available_at': resend_available_at,
        'seconds_remaining': seconds_remaining,
        'resend_seconds_remaining': resend_seconds_remaining,
        'can_resend': resend_seconds_remaining == 0,
    }


def _request_block_reason(normalized_phone, request_ip, policy, now=None):
    now = now or timezone.now()
    window_start = now - timedelta(hours=1)
    latest_otp = _latest_otp_for_phone(normalized_phone)

    if latest_otp and latest_otp.locked_until and latest_otp.locked_until > now:
        return True, 'locked', None, latest_otp.locked_until

    if latest_otp:
        resend_available_at = latest_otp.created_at + timedelta(
            seconds=policy['resend_cooldown_seconds'],
        )
        if resend_available_at > now:
            return True, 'cooldown', resend_available_at, None

    phone_attempts = SubscriberOTP.objects.filter(
        normalized_phone=normalized_phone,
        created_at__gte=window_start,
    ).count()
    if phone_attempts >= policy['phone_hourly_limit']:
        return True, 'phone_limit', None, None

    if request_ip:
        ip_attempts = SubscriberOTP.objects.filter(
            request_ip=request_ip,
            created_at__gte=window_start,
        ).count()
        if ip_attempts >= policy['ip_hourly_limit']:
            return True, 'ip_limit', None, None

    return False, '', None, None


def _blocked_request_result(error, resend_available_at=None, locked_until=None):
    return OTPRequestResult(
        ok=False,
        error=error,
        resend_available_at=resend_available_at,
        locked_until=locked_until,
        throttled=True,
    )


def record_portal_otp_request(phone, normalized_phone='', request_ip=None, user_agent='', policy=None,
                              channel='sms'):
    policy = policy or get_portal_otp_policy()
    normalized_phone = normalized_phone or normalize_phone_digits(phone)
    request_ip = normalize_request_ip(request_ip)
    now = timezone.now()
    blocked, error, resend_available_at, locked_until = _request_block_reason(
        normalized_phone,
        request_ip,
        policy,
        now=now,
    )
    if blocked:
        return _blocked_request_result(error, resend_available_at, locked_until)

    otp = SubscriberOTP.objects.create(
        subscriber=None,
        phone=phone[:30],
        normalized_phone=normalized_phone,
        code_hash='',
        channel=channel,
        destination=phone[:255],
        is_used=True,
        expires_at=now + timedelta(minutes=policy['expiry_minutes']),
        sent_at=None,
        request_ip=request_ip,
        request_user_agent=(user_agent or '')[:1000],
    )
    return OTPRequestResult(
        ok=False,
        otp=otp,
        expires_at=otp.expires_at,
        resend_available_at=otp.created_at + timedelta(seconds=policy['resend_cooldown_seconds']),
    )


def create_otp(subscriber, request_ip=None, user_agent='', policy=None, channel='sms'):
    policy = policy or get_portal_otp_policy()
    request_ip = normalize_request_ip(request_ip)
    now = timezone.now()
    normalized_phone = normalize_phone_digits(subscriber.phone)
    blocked, error, resend_available_at, locked_until = _request_block_reason(
        normalized_phone,
        request_ip,
        policy,
        now=now,
    )
    if blocked:
        return _blocked_request_result(error, resend_available_at, locked_until)

    raw_code = generate_otp()
    expires_at = now + timedelta(minutes=policy['expiry_minutes'])

    SubscriberOTP.objects.filter(
        subscriber=subscriber,
        is_used=False,
    ).update(is_used=True)

    otp = SubscriberOTP.objects.create(
        subscriber=subscriber,
        phone=subscriber.phone[:30],
        normalized_phone=normalized_phone,
        code_hash=make_password(raw_code),
        channel=channel,
        destination=subscriber.phone[:255],
        expires_at=expires_at,
        sent_at=now,
        request_ip=request_ip,
        request_user_agent=(user_agent or '')[:1000],
    )
    return OTPRequestResult(
        ok=True,
        otp=otp,
        raw_code=raw_code,
        expires_at=expires_at,
        resend_available_at=otp.created_at + timedelta(seconds=policy['resend_cooldown_seconds']),
    )


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
        'pk', 'username', 'phone', 'status',
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


def verify_otp_for_subscriber(subscriber_id, code, policy=None):
    policy = policy or get_portal_otp_policy()
    now = timezone.now()
    try:
        subscriber = Subscriber.objects.get(pk=subscriber_id)
    except (Subscriber.DoesNotExist, TypeError, ValueError):
        return None, GENERIC_OTP_VERIFY_ERROR
    if subscriber.status not in PORTAL_OTP_ELIGIBLE_STATUSES:
        return None, GENERIC_OTP_VERIFY_ERROR

    otp = SubscriberOTP.objects.filter(
        subscriber=subscriber,
        is_used=False,
    ).order_by('-created_at').first()

    if (
        not otp
        or otp.expires_at <= now
        or (otp.locked_until and otp.locked_until > now)
        or not otp.code_hash
    ):
        return None, GENERIC_OTP_VERIFY_ERROR

    if check_password((code or '').strip(), otp.code_hash):
        otp.is_used = True
        otp.last_attempt_at = now
        otp.save(update_fields=['is_used', 'last_attempt_at'])
        return subscriber, None

    otp.verify_attempts += 1
    otp.last_attempt_at = now
    update_fields = ['verify_attempts', 'last_attempt_at']
    if otp.verify_attempts >= policy['max_verify_attempts']:
        otp.locked_until = now + timedelta(minutes=policy['lockout_minutes'])
        update_fields.append('locked_until')
    otp.save(update_fields=update_fields)
    return None, GENERIC_OTP_VERIFY_ERROR


def verify_otp(phone, code):
    subscriber, error, _ = find_portal_subscriber_by_phone(phone)
    if error:
        return None, GENERIC_OTP_VERIFY_ERROR
    return verify_otp_for_subscriber(subscriber.pk, code)
