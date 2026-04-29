from django.db import models
from apps.subscribers.models import Subscriber


class SMSLog(models.Model):
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ]

    TYPE_CHOICES = [
        ('billing', 'Billing'),
        ('otp', 'OTP'),
        ('bulk', 'Bulk'),
        ('manual', 'Manual'),
    ]

    subscriber = models.ForeignKey(Subscriber, on_delete=models.SET_NULL, null=True, blank=True, related_name='sms_logs')
    billing_snapshot = models.ForeignKey(
        'billing.BillingSnapshot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_logs'
    )
    phone = models.CharField(max_length=20)
    message = models.TextField()
    sms_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='manual')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reminder_stage = models.IntegerField(default=0)
    reminder_run_date = models.DateField(null=True, blank=True)
    billing_due_date = models.DateField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    sent_by = models.CharField(max_length=100, default='system')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['billing_snapshot', 'sms_type', 'reminder_run_date']),
        ]

    def __str__(self):
        return f"SMS to {self.phone} - {self.status}"


class SMSTemplate(models.Model):
    name = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
