from django.urls import path

from apps.data_exchange import views


urlpatterns = [
    path('', views.dashboard, name='data-exchange-dashboard'),
    path('import/subscribers/', views.import_subscribers, name='data-exchange-import-subscribers'),
    path('import/payments/', views.import_payments, name='data-exchange-import-payments'),
    path('export/<str:dataset>/', views.export_dataset, name='data-exchange-export'),
    path('templates/<str:dataset>/', views.download_template, name='data-exchange-template'),
]
