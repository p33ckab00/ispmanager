from django.conf import settings
from django.db import models
from django.utils import timezone


class DiagnosticsIncident(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
    ]

    key = models.CharField(max_length=150, unique=True)
    source = models.CharField(max_length=50, default='system')
    severity = models.CharField(max_length=20, default='warning')
    title = models.CharField(max_length=255)
    detail = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='acknowledged_diagnostics_incidents',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    current_payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', '-last_seen_at', '-first_seen_at']

    def __str__(self):
        return f"[{self.status}] {self.title}"


class DiagnosticsIncidentEvent(models.Model):
    EVENT_CHOICES = [
        ('detected', 'Detected'),
        ('updated', 'Updated'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
        ('reopened', 'Reopened'),
        ('manually_resolved', 'Manually Resolved'),
    ]

    incident = models.ForeignKey(
        DiagnosticsIncident,
        on_delete=models.CASCADE,
        related_name='events',
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    message = models.TextField()
    payload_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='diagnostics_incident_events',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.incident.key} - {self.event_type}"


class DiagnosticsServiceSnapshot(models.Model):
    STATUS_CHOICES = [
        ('healthy', 'Healthy'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('unsupported', 'Unsupported'),
        ('unknown', 'Unknown'),
    ]

    service_name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unknown')
    is_present = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=False)
    detail = models.TextField(blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['service_name']

    def __str__(self):
        return f"{self.service_name} ({self.status})"
