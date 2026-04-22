from django.urls import path
from apps.core import views

urlpatterns = [
    path('setup/', views.setup_wizard, name='setup'),
]
