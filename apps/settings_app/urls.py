from django.urls import path
from apps.settings_app import views

urlpatterns = [
    path('', views.settings_index, name='settings-index'),
    path('system/', views.system_info, name='settings-system-info'),
    path('billing/', views.billing_settings, name='settings-billing'),
    path('sms/', views.sms_settings, name='settings-sms'),
    path('telegram/', views.telegram_settings, name='settings-telegram'),
    path('router/', views.router_settings, name='settings-router'),
    path('subscriber/', views.subscriber_settings, name='settings-subscriber'),
    path('usage/', views.usage_settings, name='settings-usage'),
]
