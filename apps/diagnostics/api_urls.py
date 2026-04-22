from django.urls import path

from apps.diagnostics import api_views


urlpatterns = [
    path('health/', api_views.DiagnosticsHealthView.as_view(), name='api-diagnostics-health'),
]
