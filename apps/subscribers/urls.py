from django.urls import path
from apps.subscribers import views

urlpatterns = [
    path('', views.subscriber_list, name='subscriber-list'),
    path('add/', views.subscriber_add, name='subscriber-add'),
    path('sync/', views.subscriber_sync, name='subscriber-sync'),
    path('<int:pk>/', views.subscriber_detail, name='subscriber-detail'),
    path('<int:pk>/edit/', views.subscriber_edit, name='subscriber-edit'),
    path('<int:pk>/send-billing-sms/', views.subscriber_send_billing_sms, name='subscriber-send-billing-sms'),
    path('<int:pk>/rate/', views.subscriber_rate_change, name='subscriber-rate-change'),
    path('<int:pk>/palugit/', views.subscriber_palugit, name='subscriber-palugit'),
    path('<int:pk>/palugit/remove/', views.subscriber_palugit_remove, name='subscriber-palugit-remove'),
    path('<int:pk>/suspend/', views.subscriber_suspend, name='subscriber-suspend'),
    path('<int:pk>/reconnect/', views.subscriber_reconnect, name='subscriber-reconnect'),
    path('<int:pk>/disconnect/', views.subscriber_disconnect, name='subscriber-disconnect'),
    path('<int:pk>/deceased/', views.subscriber_deceased, name='subscriber-deceased'),
    path('<int:pk>/archive/', views.subscriber_archive, name='subscriber-archive'),
    path('<int:pk>/usage-chart/', views.subscriber_usage_chart, name='subscriber-usage-chart'),
    path('<int:pk>/assign-node/', views.subscriber_assign_node, name='subscriber-assign-node'),
    path('plans/', views.plan_list, name='plan-list'),
    path('plans/add/', views.plan_add, name='plan-add'),
    path('plans/<int:pk>/edit/', views.plan_edit, name='plan-edit'),
    path('portal/', views.portal_request_otp, name='portal-request-otp'),
    path('portal/verify/', views.portal_verify_otp, name='portal-verify-otp'),
    path('portal/dashboard/', views.portal_dashboard, name='portal-dashboard'),
    path('portal/logout/', views.portal_logout, name='portal-logout'),
]
