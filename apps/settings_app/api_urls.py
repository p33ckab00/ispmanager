from django.urls import path
from apps.settings_app import api_views

urlpatterns = [
    path('billing/', api_views.BillingSettingsAPIView.as_view(), name='api-settings-billing'),
    path('sms/', api_views.SMSSettingsAPIView.as_view(), name='api-settings-sms'),
    path('telegram/', api_views.TelegramSettingsAPIView.as_view(), name='api-settings-telegram'),
    path('router/', api_views.RouterSettingsAPIView.as_view(), name='api-settings-router'),
]
