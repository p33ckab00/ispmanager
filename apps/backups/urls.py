from django.urls import path

from apps.backups import views


urlpatterns = [
    path('', views.dashboard, name='backups-dashboard'),
    path('run/full/', views.run_full_backup, name='backups-run-full'),
    path('run/partial/<str:profile>/', views.run_partial_backup, name='backups-run-partial'),
    path('validate-upload/', views.validate_backup_upload_view, name='backups-validate-upload'),
    path('retention/cleanup/', views.cleanup_retention, name='backups-cleanup-retention'),
    path('<int:pk>/download/', views.download_backup, name='backups-download'),
    path('<int:pk>/verify/', views.verify_backup, name='backups-verify'),
    path('<int:pk>/delete/', views.delete_backup, name='backups-delete'),
]
