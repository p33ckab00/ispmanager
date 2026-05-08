from django.conf import settings
from django.db import models


class BackupJob(models.Model):
    JOB_TYPE_CHOICES = [
        ('export', 'DB Export / Backup'),
        ('import_validation', 'Import Validation'),
        ('restore_test', 'Restore Test'),
    ]

    PROFILE_CHOICES = [
        ('full', 'Full Database'),
        ('business_critical', 'Business Critical'),
        ('subscribers', 'Subscribers'),
        ('billing_payments', 'Billing and Payments'),
        ('accounting', 'Accounting'),
        ('network_nms', 'Network and NMS'),
        ('settings_content', 'Settings and Content'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    job_type = models.CharField(max_length=30, choices=JOB_TYPE_CHOICES, default='export')
    profile = models.CharField(max_length=40, choices=PROFILE_CHOICES, default='full')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    file_name = models.CharField(max_length=255, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    file_size_bytes = models.BigIntegerField(default=0)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    compression = models.CharField(max_length=20, blank=True)
    pg_dump_format = models.CharField(max_length=20, blank=True)
    source_database = models.CharField(max_length=255, blank=True)
    summary_json = models.JSONField(default=dict, blank=True)
    error_report = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('run_database_backup', 'Can run database backups'),
            ('download_database_backup', 'Can download database backup files'),
            ('delete_database_backup', 'Can delete database backup files'),
            ('validate_database_backup', 'Can validate database backup imports'),
            ('run_restore_test', 'Can run backup restore tests'),
        ]

    def __str__(self):
        return f"{self.get_job_type_display()} - {self.get_profile_display()} - {self.get_status_display()}"
