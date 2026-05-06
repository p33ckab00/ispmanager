import re
from django.db import models
from django.utils import timezone
from apps.routers.models import Router


def normalize_phone_digits(phone):
    digits = re.sub(r'\D+', '', phone or '')
    if len(digits) == 11 and digits.startswith('09'):
        return f"63{digits[1:]}"
    if len(digits) == 10 and digits.startswith('9'):
        return f"63{digits}"
    return digits


class Plan(models.Model):
    name = models.CharField(max_length=100)
    speed_down_mbps = models.FloatField(default=0)
    speed_up_mbps = models.FloatField(default=0)
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - PHP {self.monthly_rate}"


class Subscriber(models.Model):
    SERVICE_CHOICES = [
        ('pppoe', 'PPPoE'),
        ('hotspot', 'Hotspot'),
        ('dhcp', 'DHCP / IPoE'),
        ('static', 'Static'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
        ('disconnected', 'Disconnected'),
        ('deceased', 'Deceased'),
        ('archived', 'Archived'),
    ]

    APPLY_MODE_CHOICES = [
        ('next_only', 'Next Invoice Only'),
        ('all_unpaid', 'All Unpaid From Effective Date'),
        ('manual', 'Choose Manually'),
    ]

    BILLING_TYPE_CHOICES = [
        ('postpaid', 'Postpaid'),
        ('prepaid', 'Prepaid'),
    ]

    # MikroTik-owned fields (updated on every sync)
    router = models.ForeignKey(
        Router, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='subscribers'
    )
    username = models.CharField(max_length=100, unique=True)
    mt_password = models.CharField(max_length=255, blank=True)
    mt_profile = models.CharField(max_length=100, blank=True)
    service_type = models.CharField(max_length=20, choices=SERVICE_CHOICES, default='pppoe')
    mac_address = models.CharField(max_length=20, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mt_status = models.CharField(max_length=20, default='unknown')
    last_synced = models.DateTimeField(null=True, blank=True)

    # Admin-owned fields
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    normalized_phone = models.CharField(max_length=20, blank=True, db_index=True, editable=False)
    address = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    sms_opt_out = models.BooleanField(default=False)

    # Billing fields
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    billing_effective_from = models.DateField(null=True, blank=True)
    cutoff_day = models.IntegerField(
        null=True,
        blank=True,
        help_text='Optional day of month for billing cutoff (1-31). Leave blank to use billing settings.'
    )
    billing_type = models.CharField(
        max_length=20,
        choices=BILLING_TYPE_CHOICES,
        default='postpaid',
        help_text='Postpaid bills after service use; prepaid bills before service use.'
    )
    billing_due_days = models.IntegerField(
        null=True,
        blank=True,
        help_text='Optional per-subscriber due offset in days after cutoff.'
    )
    is_billable = models.BooleanField(
        default=True,
        help_text='If disabled, invoices and snapshots will not be generated for this subscriber.'
    )
    suspension_hold_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Admin-approved extension of service access for overdue accounts.'
    )
    suspension_hold_reason = models.TextField(blank=True)
    suspension_hold_by = models.CharField(max_length=100, blank=True)
    suspension_hold_created_at = models.DateTimeField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True, help_text='Service start date')

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)

    # Deceased fields
    deceased_date = models.DateField(null=True, blank=True)
    deceased_note = models.TextField(blank=True)

    # Disconnection fields
    disconnected_date = models.DateField(null=True, blank=True)
    disconnected_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['username']
        permissions = [
            ('manage_subscriber_billing', 'Can manage subscriber billing fields'),
            ('manage_subscriber_lifecycle', 'Can suspend, reconnect, disconnect, mark deceased, and archive subscribers'),
            ('import_subscribers', 'Can sync or import subscribers from routers'),
        ]

    def __str__(self):
        return f"{self.username} ({self.full_name or 'No name'})"

    def save(self, *args, **kwargs):
        self.normalized_phone = normalize_phone_digits(self.phone)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'phone' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'normalized_phone'}
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.full_name if self.full_name else self.username

    @property
    def effective_rate(self):
        if self.monthly_rate is not None:
            return self.monthly_rate
        if self.plan:
            return self.plan.monthly_rate
        return None

    @property
    def is_on_map(self):
        exclude = ('disconnected', 'deceased', 'archived')
        return (
            self.status not in exclude
            and self.latitude is not None
            and self.longitude is not None
        )

    @property
    def can_generate_billing(self):
        return self.is_billable and self.status in ('active', 'suspended')

    @property
    def has_active_suspension_hold(self):
        return bool(self.suspension_hold_until and self.suspension_hold_until > timezone.now())


class RateHistory(models.Model):
    """
    Tracks every rate/plan change with effective date and apply mode.
    Source of truth for billing snapshot pricing.
    """
    APPLY_MODE_CHOICES = [
        ('next_only', 'Next Invoice Only'),
        ('all_unpaid', 'All Unpaid From Effective Date'),
        ('manual', 'Choose Manually'),
    ]

    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name='rate_history')
    old_plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    old_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    effective_date = models.DateField()
    apply_mode = models.CharField(max_length=20, choices=APPLY_MODE_CHOICES, default='next_only')
    changed_by = models.CharField(max_length=100, default='admin')
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_date', '-created_at']

    def __str__(self):
        return f"{self.subscriber.username} rate change on {self.effective_date}"

    @classmethod
    def get_effective_rate(cls, subscriber, as_of_date=None):
        """
        Returns the rate that was active on as_of_date.
        Falls back to subscriber.monthly_rate or plan.monthly_rate.
        """
        from datetime import date
        as_of_date = as_of_date or date.today()

        entry = cls.objects.filter(
            subscriber=subscriber,
            effective_date__lte=as_of_date,
            new_rate__isnull=False,
        ).order_by('-effective_date', '-created_at').first()

        if entry:
            return entry.new_rate

        return subscriber.effective_rate


class SubscriberOTP(models.Model):
    CHANNEL_CHOICES = [
        ('sms', 'SMS'),
        ('email', 'Email'),
    ]

    subscriber = models.ForeignKey(
        Subscriber,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='otps',
    )
    phone = models.CharField(max_length=30)
    normalized_phone = models.CharField(max_length=20, blank=True, db_index=True)
    code_hash = models.CharField(max_length=128, blank=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='sms')
    destination = models.CharField(max_length=255, blank=True)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    request_user_agent = models.TextField(blank=True)
    verify_attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['normalized_phone', 'created_at']),
            models.Index(fields=['request_ip', 'created_at']),
        ]

    def __str__(self):
        return f"OTP for {self.phone}"

    def save(self, *args, **kwargs):
        self.normalized_phone = normalize_phone_digits(self.phone)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'phone' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'normalized_phone'}
        super().save(*args, **kwargs)


# ── Usage Tracking ─────────────────────────────────────────────────────────────

class SubscriberUsageSample(models.Model):
    """Raw 5-minute samples. Kept 14 days."""
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name='usage_samples')
    session_key = models.CharField(max_length=100, blank=True)
    rx_bytes = models.BigIntegerField(default=0)
    tx_bytes = models.BigIntegerField(default=0)
    rx_delta = models.BigIntegerField(default=0)
    tx_delta = models.BigIntegerField(default=0)
    uptime_seconds = models.BigIntegerField(default=0)
    is_reset = models.BooleanField(default=False)
    sampled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sampled_at']
        indexes = [
            models.Index(fields=['subscriber', 'sampled_at']),
        ]

    def __str__(self):
        return f"{self.subscriber.username} @ {self.sampled_at}"


class SubscriberUsageDaily(models.Model):
    """Daily rollup. Kept 1 year."""
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name='usage_daily')
    date = models.DateField()
    rx_bytes = models.BigIntegerField(default=0)
    tx_bytes = models.BigIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    reset_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('subscriber', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.subscriber.username} on {self.date}"

    @property
    def rx_gb(self):
        return round(self.rx_bytes / (1024 ** 3), 3)

    @property
    def tx_gb(self):
        return round(self.tx_bytes / (1024 ** 3), 3)

    @property
    def total_gb(self):
        return round(self.total_bytes / (1024 ** 3), 3)


class SubscriberUsageCutoffSnapshot(models.Model):
    """Usage frozen at billing cutoff. Kept forever."""
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name='usage_cutoff_snapshots')
    cutoff_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    rx_bytes = models.BigIntegerField(default=0)
    tx_bytes = models.BigIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('subscriber', 'cutoff_date')
        ordering = ['-cutoff_date']

    def __str__(self):
        return f"{self.subscriber.username} cutoff {self.cutoff_date}"

    @property
    def total_gb(self):
        return round(self.total_bytes / (1024 ** 3), 2)


# ── NAP / Network Node ─────────────────────────────────────────────────────────

class NetworkNode(models.Model):
    """Physical distribution point: OLT, Cabinet, AP, Splice Box, etc."""
    TYPE_CHOICES = [
        ('router_site', 'Router Site'),
        ('olt', 'OLT'),
        ('cabinet', 'Distribution Cabinet'),
        ('access_point', 'Access Point'),
        ('splice_box', 'Splice / Junction Box'),
        ('pisowifi', 'PisoWifi Node'),
        ('other', 'Other'),
    ]

    SYSTEM_ROLE_CHOICES = [
        ('', 'Manual Field Node'),
        ('router_root', 'Router Root'),
    ]

    router = models.ForeignKey(Router, on_delete=models.SET_NULL, null=True, blank=True, related_name='network_nodes')
    name = models.CharField(max_length=100)
    node_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    system_role = models.CharField(max_length=30, choices=SYSTEM_ROLE_CHOICES, blank=True)
    is_system = models.BooleanField(default=False)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    port_count = models.IntegerField(default=0, help_text='Max subscriber ports')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['router', 'system_role'],
                condition=models.Q(system_role='router_root'),
                name='uniq_nms_router_root_node',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_node_type_display()})"


class SubscriberNode(models.Model):
    """Links a subscriber to a NetworkNode (NAP assignment)."""
    subscriber = models.OneToOneField(Subscriber, on_delete=models.CASCADE, related_name='node_assignment')
    node = models.ForeignKey(NetworkNode, on_delete=models.CASCADE, related_name='subscribers')
    port_label = models.CharField(max_length=50, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subscriber.username} -> {self.node.name}"
