from django.urls import path
from apps.subscribers import api_views

urlpatterns = [
    path('', api_views.SubscriberListView.as_view(), name='api-subscriber-list'),
    path('<int:pk>/', api_views.SubscriberDetailView.as_view(), name='api-subscriber-detail'),
    path('<int:pk>/rate-history/', api_views.RateHistoryView.as_view(), name='api-rate-history'),
    path('sync/', api_views.SyncSubscribersView.as_view(), name='api-subscriber-sync'),
    path('plans/', api_views.PlanListCreateView.as_view(), name='api-plan-list'),
    path('plans/<int:pk>/', api_views.PlanDetailView.as_view(), name='api-plan-detail'),
]
