from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from apps.billing.models import Payment


MONEY_ZERO = Decimal('0.00')


class AccountingEntity(models.Model):
    TAXPAYER_TYPE_CHOICES = [
        ('sole_proprietor', 'Sole Proprietor'),
        ('corporation', 'Corporation'),
    ]
    TAX_CLASSIFICATION_CHOICES = [
        ('non_vat', 'Non-VAT'),
        ('vat', 'VAT'),
    ]

    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    tin = models.CharField(max_length=50, blank=True)
    branch_code = models.CharField(max_length=10, default='00000')
    registered_address = models.TextField(blank=True)
    taxpayer_type = models.CharField(
        max_length=30,
        choices=TAXPAYER_TYPE_CHOICES,
        default='sole_proprietor',
    )
    tax_classification = models.CharField(
        max_length=20,
        choices=TAX_CLASSIFICATION_CHOICES,
        default='non_vat',
    )
    currency = models.CharField(max_length=3, default='PHP')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=Q(is_active=True),
                name='accounting_one_active_entity',
            ),
        ]
        permissions = [
            ('manage_accounting_setup', 'Can manage Accounting v2 setup'),
        ]

    def __str__(self):
        return self.legal_name or self.name


class AccountingSettings(models.Model):
    SETUP_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('foundation_ready', 'Foundation Ready'),
        ('live', 'Live'),
    ]
    COMPLIANCE_MODE_CHOICES = [
        ('loose_leaf_guides', 'Loose-leaf books and filing guides'),
        ('cas_disabled', 'CAS/CBA mode disabled'),
        ('eis_disabled', 'EIS mode disabled'),
    ]

    entity = models.OneToOneField(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='settings',
    )
    compliance_mode = models.CharField(
        max_length=40,
        choices=COMPLIANCE_MODE_CHOICES,
        default='loose_leaf_guides',
    )
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=1)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)
    setup_status = models.CharField(
        max_length=30,
        choices=SETUP_STATUS_CHOICES,
        default='not_started',
    )
    current_template_key = models.CharField(max_length=80, blank=True)
    setup_completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Accounting settings'

    def mark_foundation_ready(self, template_key=''):
        self.setup_status = 'foundation_ready'
        self.current_template_key = template_key or self.current_template_key
        self.setup_completed_at = self.setup_completed_at or timezone.now()
        self.save(update_fields=[
            'setup_status',
            'current_template_key',
            'setup_completed_at',
            'updated_at',
        ])

    def __str__(self):
        return f"Accounting settings for {self.entity}"


class AccountingPeriod(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('locked', 'Locked'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='periods',
    )
    name = models.CharField(max_length=80)
    fiscal_year = models.PositiveIntegerField()
    period_number = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['entity', 'start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'fiscal_year', 'period_number'],
                name='accounting_unique_period_number',
            ),
            models.UniqueConstraint(
                fields=['entity', 'start_date', 'end_date'],
                name='accounting_unique_period_dates',
            ),
        ]
        permissions = [
            ('manage_accounting_periods', 'Can manage accounting periods'),
        ]

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError('Accounting period end date cannot be before start date.')
        if self.period_number and not 1 <= self.period_number <= 12:
            raise ValidationError('Accounting period number must be between 1 and 12.')

    def contains(self, value):
        return self.start_date <= value <= self.end_date

    def __str__(self):
        return f"{self.entity} - {self.name}"


class ChartOfAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('asset', 'Asset'),
        ('liability', 'Liability'),
        ('equity', 'Equity'),
        ('revenue', 'Revenue'),
        ('direct_cost', 'Direct Cost'),
        ('expense', 'Expense'),
        ('other_income', 'Other Income'),
        ('other_expense', 'Other Expense'),
    ]
    NORMAL_BALANCE_CHOICES = [
        ('debit', 'Debit'),
        ('credit', 'Credit'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='accounts',
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=30, choices=ACCOUNT_TYPE_CHOICES)
    normal_balance = models.CharField(max_length=10, choices=NORMAL_BALANCE_CHOICES)
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['entity', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'code'],
                name='accounting_unique_account_code',
            ),
        ]
        permissions = [
            ('manage_chartofaccount', 'Can manage chart of accounts'),
        ]

    def clean(self):
        if self.parent_id and self.entity_id and self.parent.entity_id != self.entity_id:
            raise ValidationError('Parent account must belong to the same accounting entity.')

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('reviewed', 'Reviewed'),
        ('locked', 'Locked'),
        ('reversed', 'Reversed'),
        ('voided', 'Voided'),
    ]
    SOURCE_TYPE_CHOICES = [
        ('manual', 'Manual'),
        ('billing', 'Billing'),
        ('payment', 'Payment'),
        ('expense', 'Expense'),
        ('opening_balance', 'Opening Balance'),
        ('adjustment', 'Adjustment'),
    ]
    IMMUTABLE_STATUSES = ('posted', 'reviewed', 'locked', 'reversed', 'voided')

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='journal_entries',
    )
    period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name='journal_entries',
    )
    entry_number = models.CharField(max_length=40)
    entry_date = models.DateField()
    description = models.CharField(max_length=255)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPE_CHOICES, default='manual')
    source_document_number = models.CharField(max_length=120, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_journal_entries',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_journal_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-entry_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'entry_number'],
                name='accounting_unique_journal_entry_number',
            ),
        ]
        permissions = [
            ('post_journalentry', 'Can post journal entries'),
        ]

    def clean(self):
        if self.period_id and self.entity_id and self.period.entity_id != self.entity_id:
            raise ValidationError('Journal period must belong to the same accounting entity.')
        if self.period_id and self.entry_date and not self.period.contains(self.entry_date):
            raise ValidationError('Journal entry date must fall inside the accounting period.')

    def _assert_mutable(self):
        if not self.pk:
            return
        old_status = (
            JournalEntry.objects
            .filter(pk=self.pk)
            .values_list('status', flat=True)
            .first()
        )
        if old_status in self.IMMUTABLE_STATUSES:
            raise ValidationError('Posted, locked, reversed, reviewed, and voided journal entries are read-only.')

    def save(self, *args, **kwargs):
        self._assert_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in self.IMMUTABLE_STATUSES:
            raise ValidationError('Posted, locked, reversed, reviewed, and voided journal entries cannot be deleted.')
        return super().delete(*args, **kwargs)

    def totals(self):
        totals = self.lines.aggregate(
            debit_total=Sum('debit'),
            credit_total=Sum('credit'),
        )
        return {
            'debit': totals['debit_total'] or MONEY_ZERO,
            'credit': totals['credit_total'] or MONEY_ZERO,
        }

    def is_balanced(self):
        totals = self.totals()
        return self.lines.exists() and totals['debit'] == totals['credit']

    def __str__(self):
        return f"{self.entry_number} - {self.description}"


class JournalLine(models.Model):
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='journal_lines',
    )
    line_number = models.PositiveSmallIntegerField(default=1)
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)

    class Meta:
        ordering = ['journal_entry', 'line_number', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['journal_entry', 'line_number'],
                name='accounting_unique_journal_line_number',
            ),
            models.CheckConstraint(
                check=(
                    Q(debit__gt=0, credit=MONEY_ZERO)
                    | Q(credit__gt=0, debit=MONEY_ZERO)
                ),
                name='accounting_journal_line_one_side',
            ),
        ]

    def clean(self):
        debit = self.debit or MONEY_ZERO
        credit = self.credit or MONEY_ZERO
        if (debit > MONEY_ZERO and credit > MONEY_ZERO) or (debit <= MONEY_ZERO and credit <= MONEY_ZERO):
            raise ValidationError('Journal line must have either a debit or a credit amount, not both.')
        if (
            self.account_id
            and self.journal_entry_id
            and self.account.entity_id != self.journal_entry.entity_id
        ):
            raise ValidationError('Journal line account must belong to the same accounting entity.')

    def _assert_journal_mutable(self):
        if not self.journal_entry_id:
            return
        if JournalEntry.objects.filter(
            pk=self.journal_entry_id,
            status__in=JournalEntry.IMMUTABLE_STATUSES,
        ).exists():
            raise ValidationError('Lines for posted, locked, reversed, reviewed, and voided journals are read-only.')

    def save(self, *args, **kwargs):
        self._assert_journal_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_journal_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        side = 'Dr' if self.debit else 'Cr'
        amount = self.debit or self.credit
        return f"{side} {self.account.code} {amount}"


class SourceDocumentLink(models.Model):
    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='source_document_links',
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='source_links',
    )
    source_app = models.CharField(max_length=80)
    source_model = models.CharField(max_length=80)
    source_id = models.CharField(max_length=80)
    source_number = models.CharField(max_length=120, blank=True)
    document_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'source_app', 'source_model', 'source_id'],
                name='accounting_unique_source_document_link',
            ),
        ]

    def clean(self):
        if self.journal_entry_id and self.entity_id and self.journal_entry.entity_id != self.entity_id:
            raise ValidationError('Source document link must use a journal in the same accounting entity.')

    def __str__(self):
        return f"{self.source_app}.{self.source_model}:{self.source_id}"


class AccountingSourcePosting(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft Journal Created'),
        ('posted', 'Posted'),
        ('blocked', 'Blocked'),
        ('skipped', 'Skipped'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='source_postings',
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_posting_records',
    )
    source_app = models.CharField(max_length=80)
    source_model = models.CharField(max_length=80)
    source_id = models.CharField(max_length=80)
    source_number = models.CharField(max_length=120, blank=True)
    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounting_source_postings',
    )
    document_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='blocked')
    blocked_reason = models.TextField(blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-document_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source_app', 'source_model', 'source_id'],
                name='accounting_unique_source_posting',
            ),
        ]
        permissions = [
            ('review_accountingsourceposting', 'Can review accounting source postings'),
        ]

    def __str__(self):
        return f"{self.source_app}.{self.source_model}:{self.source_id} - {self.status}"


class CustomerWithholdingTaxClaim(models.Model):
    STATUS_CHOICES = [
        ('customer_claimed', 'Customer Claimed'),
        ('pending_2307', 'Pending 2307'),
        ('received', '2307 Received'),
        ('validated', 'Validated'),
        ('applied_to_return', 'Applied to Return'),
        ('disallowed', 'Disallowed'),
        ('canceled', 'Canceled'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='customer_withholding_claims',
    )
    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.CASCADE,
        related_name='customer_withholding_claims',
    )
    payment = models.ForeignKey(
        'billing.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_withholding_claims',
    )
    gross_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_withheld = models.DecimalField(max_digits=14, decimal_places=2)
    withholding_rate = models.DecimalField(max_digits=7, decimal_places=4, default=MONEY_ZERO)
    atc = models.CharField(max_length=30, blank=True)
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)
    payor_tin = models.CharField(max_length=50, blank=True)
    payor_name = models.CharField(max_length=255, blank=True)
    payor_address = models.TextField(blank=True)
    certificate_number = models.CharField(max_length=120, blank=True)
    certificate_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_2307')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-received_date', '-created_at']

    def clean(self):
        if self.tax_withheld and self.gross_amount and self.tax_withheld > self.gross_amount:
            raise ValidationError('Tax withheld cannot exceed the gross amount covered.')

    def __str__(self):
        return f"2307/CWT {self.subscriber} - PHP {self.tax_withheld}"


class CustomerWithholdingAllocation(models.Model):
    claim = models.ForeignKey(
        CustomerWithholdingTaxClaim,
        on_delete=models.CASCADE,
        related_name='allocations',
    )
    invoice = models.ForeignKey(
        'billing.Invoice',
        on_delete=models.CASCADE,
        related_name='customer_withholding_allocations',
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['claim', 'invoice'],
                name='accounting_unique_withholding_allocation',
            ),
        ]

    def clean(self):
        if self.amount and self.amount <= MONEY_ZERO:
            raise ValidationError('Withholding allocation amount must be greater than zero.')
        if self.claim_id and self.invoice_id and self.claim.subscriber_id != self.invoice.subscriber_id:
            raise ValidationError('Withholding claim and invoice must belong to the same subscriber.')

    def __str__(self):
        return f"{self.claim} -> {self.invoice.invoice_number}: PHP {self.amount}"


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
