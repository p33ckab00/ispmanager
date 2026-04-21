from django.db import models


class Notification(models.Model):
    CHANNEL_CHOICES = [
        ('telegram', 'Telegram'),
        ('system', 'System'),
    ]

    TYPE_CHOICES = [
        ('new_subscriber', 'New Subscriber'),
        ('subscriber_status', 'Subscriber Status Change'),
        ('router_status', 'Router Status'),
        ('billing_generated', 'Billing Generated'),
        ('payment_received', 'Payment Received'),
        ('sms_sent', 'SMS Sent'),
        ('plan_change', 'Plan Change'),
        ('settings_change', 'Settings Change'),
        ('api_error', 'API Error'),
        ('system', 'System'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    event_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='telegram')
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivery_state = models.CharField(max_length=20, default='pending')
    telegram_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type}] {self.title}"
