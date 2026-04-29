from django.db import models


class GlobalSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key, default=''):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value, description=''):
        obj, _ = cls.objects.get_or_create(key=key)
        obj.value = value
        if description:
            obj.description = description
        obj.save()
        return obj


class BillingSettings(models.Model):
    SNAPSHOT_MODE_CHOICES = [
        ('auto', 'Auto - freeze immediately on cutoff'),
        ('draft', 'Draft - admin reviews before freezing'),
        ('manual', 'Manual - admin triggers snapshot'),
    ]

    BILLING_MODE_CHOICES = [
        ('legacy', 'Legacy Due Day'),
        ('cutoff_advance', 'Cutoff Advance Billing'),
    ]

    billing_day = models.IntegerField(default=1)
    due_days = models.IntegerField(default=7)
    grace_period_days = models.IntegerField(default=3)
    currency_symbol = models.CharField(max_length=10, default='PHP')
    enable_auto_generate = models.BooleanField(default=False)
    enable_auto_disconnect = models.BooleanField(default=False)
    billing_mode = models.CharField(max_length=20, choices=BILLING_MODE_CHOICES, default='cutoff_advance')
    billing_snapshot_mode = models.CharField(max_length=20, choices=SNAPSHOT_MODE_CHOICES, default='auto')
    draft_auto_freeze_hours = models.IntegerField(default=24)
    billing_due_offset_days = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Billing Settings'

    def __str__(self):
        return 'Billing Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SMSSettings(models.Model):
    semaphore_api_key = models.CharField(max_length=255, blank=True)
    sender_name = models.CharField(max_length=11, default='ISPManager')
    enable_billing_sms = models.BooleanField(default=False)
    billing_sms_schedule = models.CharField(max_length=50, default='08:00')
    billing_sms_days_before_due = models.IntegerField(default=3)
    billing_sms_repeat_interval_days = models.IntegerField(default=2)
    billing_sms_send_after_due = models.BooleanField(default=False)
    billing_sms_after_due_interval_days = models.IntegerField(default=2)
    billing_sms_template = models.TextField(
        default='Hi {name}, your bill of {currency}{amount} is due on {due_date}. Pay here: {link}'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SMS Settings'

    def __str__(self):
        return 'SMS Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TelegramSettings(models.Model):
    bot_token = models.CharField(max_length=255, blank=True)
    chat_id = models.CharField(max_length=100, blank=True)
    enable_notifications = models.BooleanField(default=False)
    notify_new_subscriber = models.BooleanField(default=True)
    notify_subscriber_status_change = models.BooleanField(default=True)
    notify_router_status = models.BooleanField(default=True)
    notify_billing_generated = models.BooleanField(default=True)
    notify_payment_received = models.BooleanField(default=True)
    notify_sms_sent = models.BooleanField(default=False)
    notify_plan_change = models.BooleanField(default=True)
    notify_settings_change = models.BooleanField(default=True)
    notify_api_errors = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Telegram Settings'

    def __str__(self):
        return 'Telegram Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RouterSettings(models.Model):
    default_api_port = models.IntegerField(default=8728)
    polling_interval_seconds = models.IntegerField(default=10)
    sync_on_startup = models.BooleanField(default=False)
    connection_timeout_seconds = models.IntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Router Settings'

    def __str__(self):
        return 'Router Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SubscriberSettings(models.Model):
    DISCONNECTED_BILLING_POLICY_CHOICES = [
        ('preserve_balance', 'Preserve existing balance'),
        ('final_invoice', 'Generate final invoice'),
        ('waive_open_balances', 'Waive open balances'),
    ]
    DISCONNECTED_CREDIT_POLICY_CHOICES = [
        ('preserve_credit', 'Preserve account credit'),
        ('mark_refund_due', 'Mark refund due'),
        ('forfeit_credit', 'Forfeit account credit'),
    ]

    mikrotik_auto_suspend = models.BooleanField(
        default=True,
        help_text='Automatically disable PPP secret on MikroTik when subscriber is suspended'
    )
    mikrotik_auto_reconnect = models.BooleanField(
        default=True,
        help_text='Automatically enable PPP secret on MikroTik when subscriber is reconnected'
    )
    auto_reconnect_after_full_payment = models.BooleanField(
        default=False,
        help_text='Automatically reconnect suspended subscribers after all open balances are fully paid'
    )
    disconnected_billing_policy = models.CharField(
        max_length=30,
        choices=DISCONNECTED_BILLING_POLICY_CHOICES,
        default='preserve_balance',
        help_text='Billing action to apply when a subscriber is marked disconnected'
    )
    disconnected_credit_policy = models.CharField(
        max_length=30,
        choices=DISCONNECTED_CREDIT_POLICY_CHOICES,
        default='preserve_credit',
        help_text='Credit action to apply when a disconnected subscriber has remaining account credit'
    )
    archive_after_days = models.IntegerField(
        default=90,
        help_text='Auto-archive disconnected/deceased subscribers after this many days'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Subscriber Settings'

    def __str__(self):
        return 'Subscriber Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UsageSettings(models.Model):
    enabled = models.BooleanField(default=True)
    sampler_interval_minutes = models.IntegerField(default=5)
    raw_retention_days = models.IntegerField(default=14)
    daily_retention_days = models.IntegerField(default=365)
    cutoff_snapshot_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Usage Settings'

    def __str__(self):
        return 'Usage Settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
