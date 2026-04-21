from django.urls import path
from apps.diagnostics import views

urlpatterns = [
    path('', views.diagnostics_dashboard, name='diagnostics-dashboard'),
    path('routers/<int:pk>/ping/', views.router_ping, name='router-ping'),
    path('scheduler/', views.scheduler_status, name='scheduler-status'),
    path('scheduler/<str:job_id>/run/', views.run_job_now, name='scheduler-run-job'),
]
