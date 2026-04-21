from rest_framework import serializers
from apps.billing.models import Invoice, Payment, PaymentAllocation, BillingSnapshot, BillingSnapshotItem


class PaymentAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.SerializerMethodField()

    class Meta:
        model = PaymentAllocation
        fields = ['id', 'invoice', 'invoice_number', 'amount_allocated', 'created_at']

    def get_invoice_number(self, obj):
        return obj.invoice.invoice_number


class PaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    subscriber_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'subscriber', 'subscriber_name', 'amount', 'method',
                  'reference', 'notes', 'recorded_by', 'paid_at', 'created_at', 'allocations']

    def get_subscriber_name(self, obj):
        return obj.subscriber.display_name


class InvoiceSerializer(serializers.ModelSerializer):
    subscriber_name = serializers.SerializerMethodField()
    remaining_balance = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()
    billing_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'subscriber', 'subscriber_name',
            'period_start', 'period_end', 'due_date',
            'amount', 'amount_paid', 'remaining_balance',
            'status', 'plan_snapshot', 'rate_snapshot',
            'short_code', 'notes', 'void_reason',
            'billing_url', 'is_overdue', 'created_at', 'updated_at',
        ]
        read_only_fields = ['token', 'short_code', 'invoice_number']

    def get_subscriber_name(self, obj):
        return obj.subscriber.display_name

    def get_billing_url(self, obj):
        return obj.get_billing_url()


class BillingSnapshotItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingSnapshotItem
        fields = '__all__'


class BillingSnapshotSerializer(serializers.ModelSerializer):
    subscriber_name = serializers.SerializerMethodField()
    items = BillingSnapshotItemSerializer(many=True, read_only=True)

    class Meta:
        model = BillingSnapshot
        fields = [
            'id', 'snapshot_number', 'subscriber', 'subscriber_name',
            'cutoff_date', 'issue_date', 'due_date',
            'period_start', 'period_end',
            'current_cycle_amount', 'previous_balance_amount',
            'credit_amount', 'total_due_amount',
            'status', 'source', 'frozen_at', 'created_at', 'items',
        ]

    def get_subscriber_name(self, obj):
        return obj.subscriber.display_name
