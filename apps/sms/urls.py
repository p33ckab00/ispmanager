from django.urls import path
from apps.sms import views

urlpatterns = [
    path('', views.sms_dashboard, name='sms-dashboard'),
    path('log/', views.sms_log, name='sms-log'),
    path('send/', views.sms_send, name='sms-send'),
]
