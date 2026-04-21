from django.urls import path
from apps.core import views

urlpatterns = [
    path('', views.dashboard, name='home'),
    path('setup/', views.setup_wizard, name='setup'),
]
