from django.urls import path
from apps.core import api_views

urlpatterns = [
    path('setup-status/', api_views.SetupStatusView.as_view(), name='api-setup-status'),
    path('audit-logs/', api_views.AuditLogListView.as_view(), name='api-audit-logs'),
]
