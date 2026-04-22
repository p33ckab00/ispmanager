from django.contrib.auth.models import User
from django.db import models


class DataExchangeJob(models.Model):
    JOB_TYPE_CHOICES = [
        ('import', 'Import'),
        ('export', 'Export'),
    ]

    DATASET_CHOICES = [
        ('subscribers', 'Subscribers'),
        ('invoices', 'Invoices'),
        ('payments', 'Payments'),
        ('expenses', 'Expenses'),
    ]

    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    dataset = models.CharField(max_length=30, choices=DATASET_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    file_name = models.CharField(max_length=255, blank=True)
    is_dry_run = models.BooleanField(default=False)
    total_rows = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    summary_json = models.JSONField(default=dict, blank=True)
    error_report = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_job_type_display()} {self.get_dataset_display()} @ {self.created_at:%Y-%m-%d %H:%M}"
