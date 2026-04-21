from django.db import models
from django.contrib.auth.models import User


class SystemSetup(models.Model):
    is_configured = models.BooleanField(default=False)
    isp_name = models.CharField(max_length=255, blank=True)
    isp_address = models.TextField(blank=True)
    isp_phone = models.CharField(max_length=50, blank=True)
    isp_email = models.EmailField(blank=True)
    isp_logo = models.ImageField(upload_to='system/', blank=True, null=True)
    configured_at = models.DateTimeField(auto_now_add=True)
    configured_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = 'System Setup'

    def __str__(self):
        return f"Setup - {'Configured' if self.is_configured else 'Pending'}"

    @classmethod
    def get_setup(cls):
        setup, _ = cls.objects.get_or_create(pk=1)
        return setup


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('sync', 'Sync'),
        ('send', 'Send'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    module = models.CharField(max_length=50)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.module}] {self.action} - {self.created_at}"

    @classmethod
    def log(cls, action, module, description, user=None, ip_address=None):
        cls.objects.create(
            user=user,
            action=action,
            module=module,
            description=description,
            ip_address=ip_address,
        )
