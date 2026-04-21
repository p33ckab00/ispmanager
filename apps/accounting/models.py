from django.db import models
from apps.billing.models import Payment


class IncomeRecord(models.Model):
    SOURCE_CHOICES = [
        ('billing', 'Billing Payment'),
        ('connection_fee', 'Connection Fee'),
        ('installation', 'Installation Fee'),
        ('other', 'Other Income'),
    ]

    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default='billing')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=255, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='income_record')
    recorded_by = models.CharField(max_length=100, default='system')
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Income: {self.description} - PHP {self.amount}"


class ExpenseRecord(models.Model):
    CATEGORY_CHOICES = [
        ('bandwidth', 'Bandwidth / Upstream'),
        ('equipment', 'Equipment'),
        ('maintenance', 'Maintenance'),
        ('salary', 'Salary'),
        ('utilities', 'Utilities'),
        ('office', 'Office Expenses'),
        ('other', 'Other Expense'),
    ]

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='other')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=255, blank=True)
    vendor = models.CharField(max_length=100, blank=True)
    recorded_by = models.CharField(max_length=100, default='admin')
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Expense: {self.description} - PHP {self.amount}"
