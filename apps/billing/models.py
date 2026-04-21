import secrets
import string
from decimal import Decimal
from django.db import models
from django.utils import timezone


def generate_token():
    return secrets.token_hex(16)


def generate_short_code():
    chars = string.ascii_letters + string.digits
    while True:
        code = ''.join(secrets.choice(chars) for _ in range(6))
        if not Invoice.objects.filter(short_code=code).exists():
            return code


class Invoice(models.Model):
    """
    Real receivable ledger row. One per billing cycle per subscriber.
    Never rewritten after creation. Payment allocations post against this.
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('voided', 'Voided'),
        ('waived', 'Waived'),
    ]

    VOID_REASON_CHOICES = [
        ('subscriber_deceased', 'Subscriber Deceased'),
        ('admin_adjustment', 'Admin Adjustment'),
        ('duplicate', 'Duplicate Invoice'),
        ('other', 'Other'),
    ]

    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    invoice_number = models.CharField(max_length=30, unique=True, blank=True)
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    plan_snapshot = models.CharField(max_length=100, blank=True)
    rate_snapshot = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    token = models.CharField(max_length=32, unique=True, blank=True)
    short_code = models.CharField(max_length=8, unique=True, blank=True)
    void_reason = models.CharField(max_length=30, choices=VOID_REASON_CHOICES, blank=True)
    void_note = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_start']

    def __str__(self):
        return f"{self.invoice_number} - {self.subscriber.username}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = generate_token()
        if not self.short_code:
            self.short_code = generate_short_code()
        if not self.invoice_number:
            from django.utils.timezone import now
            dt = now()
            seq = Invoice.objects.filter(
                created_at__year=dt.year,
                created_at__month=dt.month
            ).count() + 1
            self.invoice_number = f"INV-{dt.strftime('%Y%m')}-{seq:04d}"
        if not self.plan_snapshot and self.subscriber_id:
            try:
                if self.subscriber.plan:
                    self.plan_snapshot = self.subscriber.plan.name
            except Exception:
                pass
        super().save(*args, **kwargs)

    @property
    def remaining_balance(self):
        return self.amount - self.amount_paid

    @property
    def is_overdue(self):
        from datetime import date
        return self.status in ('open', 'partial') and self.due_date < date.today()

    def get_billing_url(self):
        return f"/b/{self.short_code}/"

    def get_full_billing_url(self):
        return f"/billing/view/{self.token}/"


class Payment(models.Model):
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('gcash', 'GCash'),
        ('bank', 'Bank Transfer'),
        ('maya', 'Maya'),
        ('other', 'Other'),
    ]

    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='cash')
    reference = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.CharField(max_length=100, default='admin')
    paid_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_at']

    def __str__(self):
        return f"Payment PHP {self.amount} from {self.subscriber.username} on {self.paid_at.date()}"

    @property
    def unallocated_amount(self):
        allocated = self.allocations.aggregate(
            total=models.Sum('amount_allocated')
        )['total'] or Decimal('0.00')
        return self.amount - allocated


class PaymentAllocation(models.Model):
    """
    Tracks which payment covers which invoice and how much.
    Oldest invoice first allocation.
    """
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='allocations')
    amount_allocated = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        unique_together = ('payment', 'invoice')

    def __str__(self):
        return f"{self.payment} -> {self.invoice.invoice_number}: PHP {self.amount_allocated}"


class BillingSnapshot(models.Model):
    """
    Client-facing statement. Frozen at creation. Separate from Invoice ledger.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('frozen', 'Frozen'),
    ]

    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.CASCADE,
        related_name='billing_snapshots'
    )
    snapshot_number = models.CharField(max_length=30, unique=True, blank=True)
    cutoff_date = models.DateField()
    issue_date = models.DateField()
    due_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    current_cycle_amount = models.DecimalField(max_digits=10, decimal_places=2)
    previous_balance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    credit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_due_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    source = models.CharField(max_length=20, default='scheduler')
    frozen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, default='system')

    class Meta:
        ordering = ['-cutoff_date']

    def __str__(self):
        return f"{self.snapshot_number} - {self.subscriber.username}"

    def save(self, *args, **kwargs):
        if not self.snapshot_number:
            from django.utils.timezone import now
            dt = now()
            seq = BillingSnapshot.objects.filter(
                created_at__year=dt.year,
                created_at__month=dt.month
            ).count() + 1
            self.snapshot_number = f"BILL-{dt.strftime('%Y%m%d')}-{seq:04d}"
        if not self.total_due_amount:
            self.total_due_amount = (
                self.current_cycle_amount
                + self.previous_balance_amount
                - self.credit_amount
            )
        super().save(*args, **kwargs)

    def freeze(self, frozen_by='system'):
        self.status = 'frozen'
        self.frozen_at = timezone.now()
        self.created_by = frozen_by
        self.save(update_fields=['status', 'frozen_at', 'created_by'])

    @property
    def is_frozen(self):
        return self.status == 'frozen'


class BillingSnapshotItem(models.Model):
    """
    Line items inside a BillingSnapshot. Explains what makes up the total.
    """
    ITEM_TYPE_CHOICES = [
        ('current_charge', 'Current Cycle Charge'),
        ('previous_balance', 'Previous Balance'),
        ('credit', 'Credit'),
        ('adjustment', 'Adjustment'),
    ]

    snapshot = models.ForeignKey(BillingSnapshot, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    label = models.CharField(max_length=255)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.snapshot.snapshot_number} - {self.label}"
