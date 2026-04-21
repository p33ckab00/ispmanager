from django.db import models


class Notification(models.Model):
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
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error = models.TextField(blank=True)
    telegram_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type}] {self.title}"
