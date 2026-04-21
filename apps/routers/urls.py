from django.urls import path
from apps.routers import views

urlpatterns = [
    path('', views.router_list, name='router-list'),
    path('add/', views.router_add, name='router-add'),
    path('<int:pk>/', views.router_detail, name='router-detail'),
    path('<int:pk>/edit/', views.router_edit, name='router-edit'),
    path('<int:pk>/delete/', views.router_delete, name='router-delete'),
    path('<int:pk>/sync/', views.router_sync, name='router-sync'),
    path('<int:pk>/coordinates/', views.router_coordinates, name='router-coordinates'),
    path('<int:router_pk>/interfaces/<int:iface_pk>/', views.interface_detail, name='interface-detail'),
    path('<int:router_pk>/interfaces/<int:iface_pk>/traffic/', views.interface_traffic_poll, name='interface-traffic-poll'),
    path('test-connection/', views.test_connection_view, name='router-test-connection'),
]
