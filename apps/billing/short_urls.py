from django.urls import path
from apps.billing import views

urlpatterns = [
    path('', views.billing_short_url, name='billing-short-url'),
]
