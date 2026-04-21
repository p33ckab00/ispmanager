from django.urls import path
from apps.billing import api_views

urlpatterns = [
    path('invoices/', api_views.InvoiceListView.as_view(), name='api-invoice-list'),
    path('invoices/<int:pk>/', api_views.InvoiceDetailView.as_view(), name='api-invoice-detail'),
    path('invoices/generate/', api_views.GenerateInvoicesView.as_view(), name='api-generate-invoices'),
    path('snapshots/', api_views.SnapshotListView.as_view(), name='api-snapshot-list'),
    path('mark-overdue/', api_views.MarkOverdueView.as_view(), name='api-billing-overdue'),
]
