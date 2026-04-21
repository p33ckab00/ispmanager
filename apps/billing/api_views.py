from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.billing.models import Invoice, Payment, BillingSnapshot
from apps.billing.serializers import InvoiceSerializer, PaymentSerializer, BillingSnapshotSerializer
from apps.billing.services import generate_invoices_for_all, mark_overdue_invoices


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceSerializer

    def get_queryset(self):
        qs = Invoice.objects.select_related('subscriber').all()
        s = self.request.query_params.get('status')
        if s:
            qs = qs.filter(status=s)
        return qs


class InvoiceDetailView(generics.RetrieveAPIView):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer


class SnapshotListView(generics.ListAPIView):
    serializer_class = BillingSnapshotSerializer
    queryset = BillingSnapshot.objects.all()


class GenerateInvoicesView(APIView):
    def post(self, request):
        created, skipped, errors = generate_invoices_for_all()
        return Response({'created': created, 'skipped': skipped, 'errors': errors})


class MarkOverdueView(APIView):
    def post(self, request):
        count = mark_overdue_invoices()
        return Response({'marked_overdue': count})
