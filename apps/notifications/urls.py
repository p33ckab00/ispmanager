from django.urls import path
from apps.notifications import views

urlpatterns = [
    path('', views.notification_list, name='notification-list'),
    path('telegram/test/', views.telegram_test, name='telegram-test'),
]
