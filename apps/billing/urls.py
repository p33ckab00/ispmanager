from django.urls import path
from apps.billing import views

urlpatterns = [
    path('', views.invoice_list, name='billing-list'),
    path('invoices/', views.invoice_list, name='invoice-list'),
    path('invoices/generate/', views.generate_invoices, name='generate-invoices'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice-detail'),
    path('snapshots/', views.snapshot_list, name='snapshot-list'),
    path('snapshots/<int:pk>/', views.snapshot_detail, name='snapshot-detail'),
    path('snapshots/<int:pk>/freeze/', views.snapshot_freeze, name='snapshot-freeze'),
    path('snapshots/<int:pk>/pdf/view/', views.snapshot_pdf_inline, name='snapshot-pdf-inline'),
    path('snapshots/<int:pk>/pdf/download/', views.snapshot_pdf_download, name='snapshot-pdf-download'),
    path('pay/<int:subscriber_pk>/', views.record_payment, name='billing-record-payment'),
    path('generate-snapshot/<int:subscriber_pk>/', views.generate_snapshot, name='generate-snapshot'),
    path('view/<str:token>/', views.billing_public_view, name='billing-public-view'),
]
