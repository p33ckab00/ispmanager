from django.urls import path
from apps.routers import api_views

urlpatterns = [
    path('', api_views.RouterListCreateView.as_view(), name='api-router-list'),
    path('<int:pk>/', api_views.RouterDetailView.as_view(), name='api-router-detail'),
    path('<int:pk>/sync/', api_views.RouterSyncView.as_view(), name='api-router-sync'),
    path('<int:pk>/interfaces/', api_views.RouterInterfaceListView.as_view(), name='api-router-interfaces'),
    path('<int:router_pk>/interfaces/<int:iface_pk>/traffic/', api_views.InterfaceTrafficView.as_view(), name='api-interface-traffic'),
    path('test-connection/', api_views.TestConnectionView.as_view(), name='api-test-connection'),
]
