from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from apps.billing.models import Payment


MONEY_ZERO = Decimal('0.00')
CUTOVER_LOCKED_STATUSES = ('approved', 'live')


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
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_accounting_periods',
    )
    closing_journal_entry = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_periods',
    )
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
        ('closing', 'Closing Entry'),
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


class AccountingReportArchive(models.Model):
    FORMAT_CHOICES = [
        ('csv', 'CSV'),
        ('xlsx', 'XLSX'),
        ('pdf', 'PDF'),
        ('manifest', 'Manifest'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='report_archives',
    )
    report_name = models.CharField(max_length=120)
    export_format = models.CharField(max_length=20, choices=FORMAT_CHOICES)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    canonical_filename = models.CharField(max_length=255)
    canonical_sha256 = models.CharField(max_length=64)
    canonical_size = models.PositiveIntegerField(default=0)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.PositiveIntegerField(default=0)
    archive_file = models.FileField(upload_to='accounting/report_archives/files/', blank=True)
    package_file = models.FileField(upload_to='accounting/report_archives/packages/', blank=True)
    package_sha256 = models.CharField(max_length=64, blank=True)
    package_size = models.PositiveIntegerField(default=0)
    row_count = models.PositiveIntegerField(default=0)
    filters = models.JSONField(default=dict, blank=True)
    columns = models.JSONField(default=list, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounting_report_archives',
    )
    generated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at', '-created_at']
        permissions = [
            ('view_accounting_report_archive', 'Can view accounting report archives'),
        ]

    def save(self, *args, **kwargs):
        if self.pk and AccountingReportArchive.objects.filter(pk=self.pk).exists():
            raise ValidationError('Accounting report archive records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Accounting report archive records cannot be deleted.')

    def __str__(self):
        return f"{self.report_name} {self.export_format} {self.generated_at:%Y-%m-%d %H:%M}"


class AccountingReportPreset(models.Model):
    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='report_presets',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='accounting_report_presets',
    )
    report_key = models.CharField(max_length=80)
    name = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['report_key', 'name', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'user', 'report_key', 'name'],
                name='accounting_unique_report_preset_name',
            ),
        ]

    def __str__(self):
        return f"{self.report_key}: {self.name}"


class APVendor(models.Model):
    TAX_CLASSIFICATION_CHOICES = [
        ('unknown', 'Unknown'),
        ('non_vat', 'Non-VAT'),
        ('vat', 'VAT'),
        ('vat_exempt', 'VAT Exempt'),
        ('zero_rated', 'Zero-Rated'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='ap_vendors',
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=255)
    registered_name = models.CharField(max_length=255, blank=True)
    tin = models.CharField(max_length=50, blank=True)
    registered_address = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    tax_classification = models.CharField(
        max_length=20,
        choices=TAX_CLASSIFICATION_CHOICES,
        default='unknown',
    )
    default_expense_account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ap_vendors_as_default_expense',
    )
    default_ap_account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ap_vendors_as_default_payable',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'code'],
                name='accounting_unique_ap_vendor_code',
            ),
        ]
        permissions = [
            ('manage_apvendor', 'Can manage AP vendors'),
        ]

    def clean(self):
        for field_name in ('default_expense_account', 'default_ap_account'):
            account = getattr(self, field_name, None)
            if account and self.entity_id and account.entity_id != self.entity_id:
                raise ValidationError('AP vendor default accounts must belong to the same accounting entity.')
        if (
            self.default_expense_account_id
            and self.default_expense_account.account_type not in ('direct_cost', 'expense', 'other_expense', 'asset')
        ):
            raise ValidationError('Default expense account must be an expense, direct cost, other expense, or asset account.')
        if self.default_ap_account_id and self.default_ap_account.account_type != 'liability':
            raise ValidationError('Default AP account must be a liability account.')

    @property
    def display_name(self):
        return self.registered_name or self.name

    def __str__(self):
        return f"{self.code} - {self.display_name}"


class APVendorBill(models.Model):
    TAX_TREATMENT_CHOICES = [
        ('non_vat', 'Non-VAT'),
        ('vat', 'VAT'),
        ('vat_exempt', 'VAT Exempt'),
        ('zero_rated', 'Zero-Rated'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft Journal'),
        ('open', 'Open'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('void_pending', 'Void Pending'),
        ('voided', 'Voided'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='ap_vendor_bills',
    )
    vendor = models.ForeignKey(
        APVendor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='bills',
    )
    vendor_name = models.CharField(max_length=255)
    bill_number = models.CharField(max_length=120)
    document_date = models.DateField()
    due_date = models.DateField()
    expense_account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='ap_vendor_bills_as_expense',
    )
    ap_account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='ap_vendor_bills_as_payable',
    )
    tax_treatment = models.CharField(max_length=20, choices=TAX_TREATMENT_CHOICES, default='non_vat')
    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    input_vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ap_vendor_bills',
    )
    void_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_ap_vendor_bills',
    )
    void_reason = models.CharField(max_length=255, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_ap_vendor_bills',
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ap_vendor_bills',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-document_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'vendor_name', 'bill_number'],
                name='accounting_unique_ap_vendor_bill',
            ),
        ]
        permissions = [
            ('manage_apvendorbill', 'Can manage AP vendor bills'),
        ]

    def clean(self):
        if self.amount is not None and self.amount <= MONEY_ZERO:
            raise ValidationError('AP vendor bill amount must be greater than zero.')
        if self.base_amount is not None and self.base_amount <= MONEY_ZERO:
            raise ValidationError('AP vendor bill base amount must be greater than zero.')
        if self.input_vat_amount is not None and self.input_vat_amount < MONEY_ZERO:
            raise ValidationError('AP vendor bill input VAT cannot be negative.')
        if self.amount is not None and self.base_amount is not None and self.input_vat_amount is not None:
            if self.amount != self.base_amount + self.input_vat_amount:
                raise ValidationError('AP vendor bill gross amount must equal base amount plus input VAT.')
        if self.tax_treatment != 'vat' and self.input_vat_amount != MONEY_ZERO:
            raise ValidationError('Only VAT AP vendor bills may carry input VAT.')
        if self.tax_treatment == 'vat' and self.input_vat_amount <= MONEY_ZERO:
            raise ValidationError('VAT AP vendor bills must carry input VAT.')
        if self.input_vat_amount > MONEY_ZERO and self.entity_id and self.entity.tax_classification != 'vat':
            raise ValidationError('Input VAT is available only for VAT accounting entities.')
        if self.due_date and self.document_date and self.due_date < self.document_date:
            raise ValidationError('AP vendor bill due date cannot be before document date.')
        for field_name in ('expense_account', 'ap_account'):
            account = getattr(self, field_name, None)
            if account and self.entity_id and account.entity_id != self.entity_id:
                raise ValidationError('AP vendor bill accounts must belong to the same accounting entity.')
        if self.vendor_id and self.entity_id and self.vendor.entity_id != self.entity_id:
            raise ValidationError('AP vendor bill vendor must belong to the same accounting entity.')
        if self.expense_account_id and self.expense_account.account_type not in ('direct_cost', 'expense', 'other_expense', 'asset'):
            raise ValidationError('Expense account must be an expense, direct cost, other expense, or asset account.')
        if self.ap_account_id and self.ap_account.account_type != 'liability':
            raise ValidationError('AP account must be a liability account.')
        if self.journal_entry_id and self.entity_id and self.journal_entry.entity_id != self.entity_id:
            raise ValidationError('AP vendor bill journal must belong to the same accounting entity.')
        if self.void_journal_entry_id and self.entity_id and self.void_journal_entry.entity_id != self.entity_id:
            raise ValidationError('AP vendor bill void journal must belong to the same accounting entity.')

    @property
    def is_posted(self):
        return bool(self.journal_entry_id and self.journal_entry.status == 'posted')

    @property
    def posted_payment_total(self):
        total = (
            self.payments
            .filter(journal_entry__status='posted')
            .exclude(void_journal_entry__status='posted')
            .aggregate(total=Sum('amount'))['total']
        )
        return total or MONEY_ZERO

    @property
    def remaining_balance(self):
        if not self.is_posted or self.status == 'voided':
            return MONEY_ZERO
        return max((self.amount or MONEY_ZERO) - self.posted_payment_total, MONEY_ZERO)

    def __str__(self):
        return f"{self.vendor_name} {self.bill_number} - PHP {self.amount}"


class APVendorPayment(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft Journal'),
        ('posted', 'Posted'),
        ('void_pending', 'Void Pending'),
        ('voided', 'Voided'),
    ]
    SETTLEMENT_STATUS_CHOICES = [
        ('unmatched', 'Unmatched'),
        ('matched', 'Matched'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='ap_vendor_payments',
    )
    bill = models.ForeignKey(
        APVendorBill,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    payment_date = models.DateField()
    cash_account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='ap_vendor_payments_as_cash',
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ap_vendor_payments',
    )
    void_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_ap_vendor_payments',
    )
    void_reason = models.CharField(max_length=255, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_ap_vendor_payments',
    )
    settlement_status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUS_CHOICES,
        default='unmatched',
    )
    settlement_date = models.DateField(null=True, blank=True)
    settlement_reference = models.CharField(max_length=120, blank=True)
    settlement_note = models.CharField(max_length=255, blank=True)
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='matched_ap_vendor_payments',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ap_vendor_payments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def clean(self):
        if self.amount is not None and self.amount <= MONEY_ZERO:
            raise ValidationError('AP vendor payment amount must be greater than zero.')
        if self.entity_id and self.bill_id and self.bill.entity_id != self.entity_id:
            raise ValidationError('AP vendor payment bill must belong to the same accounting entity.')
        if self.cash_account_id and self.entity_id and self.cash_account.entity_id != self.entity_id:
            raise ValidationError('AP vendor payment cash account must belong to the same accounting entity.')
        if self.cash_account_id and self.cash_account.account_type != 'asset':
            raise ValidationError('AP vendor payment cash account must be an asset account.')
        if self.journal_entry_id and self.entity_id and self.journal_entry.entity_id != self.entity_id:
            raise ValidationError('AP vendor payment journal must belong to the same accounting entity.')
        if self.void_journal_entry_id and self.entity_id and self.void_journal_entry.entity_id != self.entity_id:
            raise ValidationError('AP vendor payment void journal must belong to the same accounting entity.')
        if self.settlement_status == 'matched':
            if not self.settlement_date or not self.settlement_reference:
                raise ValidationError('Matched AP vendor payments require settlement date and reference.')
            if self.settlement_date and self.payment_date and self.settlement_date < self.payment_date:
                raise ValidationError('Settlement date cannot be before payment date.')
        elif any([self.settlement_date, self.settlement_reference, self.settlement_note, self.matched_at, self.matched_by_id]):
            raise ValidationError('Unmatched AP vendor payments cannot keep settlement details.')

    @property
    def is_posted(self):
        return bool(self.journal_entry_id and self.journal_entry.status == 'posted')

    def __str__(self):
        return f"{self.bill.vendor_name} payment - PHP {self.amount}"


def ap_vendor_bill_attachment_upload_to(instance, filename):
    safe_name = Path(filename).name
    return f"accounting/ap_bills/{instance.entity_id}/{instance.bill_id}/{safe_name}"


class APVendorBillAttachment(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('supplier_invoice', 'Supplier Invoice'),
        ('receipt', 'Receipt'),
        ('statement', 'Statement'),
        ('supporting_document', 'Supporting Document'),
        ('other', 'Other'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='ap_vendor_bill_attachments',
    )
    bill = models.ForeignKey(
        APVendorBill,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default='supplier_invoice',
    )
    file = models.FileField(upload_to=ap_vendor_bill_attachment_upload_to)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_ap_vendor_bill_attachments',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        permissions = [
            ('manage_apvendorbillattachment', 'Can manage AP vendor bill attachments'),
        ]

    def clean(self):
        if self.bill_id and self.entity_id and self.bill.entity_id != self.entity_id:
            raise ValidationError('AP vendor bill attachment must use the same accounting entity as the bill.')

    def __str__(self):
        return f"{self.bill.bill_number} - {self.original_filename}"


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


class CutoverPlan(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('reconciling', 'Reconciling'),
        ('ready_for_review', 'Ready for Review'),
        ('approved', 'Approved'),
        ('live', 'Live'),
        ('voided', 'Voided'),
    ]
    SOURCE_POLICY_CHOICES = [
        ('opening_balances_only_pre_cutover', 'Opening balances only before cutover'),
        ('source_backfill_review_only', 'Pre-cutover source backfill for review only'),
        ('manual', 'Manual policy'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='cutover_plans',
    )
    cutover_date = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    source_policy = models.CharField(
        max_length=50,
        choices=SOURCE_POLICY_CHOICES,
        default='opening_balances_only_pre_cutover',
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prepared_cutover_plans',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_cutover_plans',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_cutover_plans',
    )
    notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    live_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-cutover_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['entity'],
                condition=~Q(status='voided'),
                name='accounting_one_active_cutover_plan',
            ),
        ]
        permissions = [
            ('manage_cutoverplan', 'Can manage Accounting v2 cutover plan'),
        ]

    def clean(self):
        if self.approved_at and self.status not in ('approved', 'live'):
            raise ValidationError('Only approved or live cutover plans can have an approval timestamp.')
        if self.live_at and self.status != 'live':
            raise ValidationError('Only live cutover plans can have a live timestamp.')

    def __str__(self):
        return f"{self.entity} cutover {self.cutover_date}"


class OpeningBalanceImport(models.Model):
    IMPORT_TYPE_CHOICES = [
        ('manual', 'Manual Entry'),
        ('csv', 'CSV Upload'),
        ('xlsx', 'XLSX Upload'),
        ('system_snapshot', 'System Snapshot'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('journal_created', 'Journal Created'),
        ('posted', 'Posted'),
        ('voided', 'Voided'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='opening_balance_imports',
    )
    cutover_plan = models.ForeignKey(
        CutoverPlan,
        on_delete=models.PROTECT,
        related_name='opening_balance_imports',
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_imports',
    )
    import_type = models.CharField(max_length=30, choices=IMPORT_TYPE_CHOICES, default='manual')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    source_filename = models.CharField(max_length=255, blank=True)
    source_hash = models.CharField(max_length=128, blank=True)
    total_debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    total_credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    validation_errors = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_opening_balance_imports',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_opening_balance_imports',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('manage_openingbalanceimport', 'Can manage opening balance imports'),
        ]

    @property
    def difference(self):
        return (self.total_debit or MONEY_ZERO) - (self.total_credit or MONEY_ZERO)

    @property
    def is_balanced(self):
        return self.lines.exists() and self.difference == MONEY_ZERO

    @property
    def has_locked_journal(self):
        return (
            self.journal_entry_id
            and self.journal_entry.status in JournalEntry.IMMUTABLE_STATUSES
        )

    def clean(self):
        if self.cutover_plan_id and self.entity_id and self.cutover_plan.entity_id != self.entity_id:
            raise ValidationError('Opening balance import must use the same entity as the cutover plan.')
        if self.journal_entry_id and self.entity_id and self.journal_entry.entity_id != self.entity_id:
            raise ValidationError('Opening balance journal must belong to the same entity.')
        if self.status == 'posted' and not self.journal_entry_id:
            raise ValidationError('Posted opening balance imports must be linked to a journal entry.')

    def _assert_mutable(self):
        if (
            self.cutover_plan_id
            and CutoverPlan.objects.filter(
                pk=self.cutover_plan_id,
                status__in=CUTOVER_LOCKED_STATUSES,
            ).exists()
        ):
            raise ValidationError('Approved or live cutover plans are locked.')
        if not self.pk:
            return
        old = (
            OpeningBalanceImport.objects
            .select_related('journal_entry')
            .filter(pk=self.pk)
            .first()
        )
        if old and (old.status in ('journal_created', 'posted', 'voided') or old.journal_entry_id):
            raise ValidationError('Opening balance imports linked to a journal are read-only.')

    def save(self, *args, **kwargs):
        self._assert_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in ('journal_created', 'posted', 'voided') or self.journal_entry_id:
            raise ValidationError('Opening balance imports linked to a journal cannot be deleted.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.get_import_type_display()} opening balances for {self.cutover_plan.cutover_date}"


class OpeningBalanceLine(models.Model):
    LINE_TYPE_CHOICES = [
        ('gl_control', 'GL Control'),
        ('subscriber_ar', 'Subscriber AR'),
        ('customer_advance', 'Customer Advance'),
        ('cash', 'Cash'),
        ('bank', 'Bank'),
        ('wallet_gateway', 'Wallet / Gateway'),
        ('ap_vendor', 'AP Vendor'),
        ('inventory', 'Inventory'),
        ('fixed_asset', 'Fixed Asset'),
        ('accumulated_depreciation', 'Accumulated Depreciation'),
        ('tax', 'Tax'),
        ('loan', 'Loan'),
        ('equity', 'Equity'),
        ('other', 'Other'),
    ]
    VALIDATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('valid', 'Valid'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]

    import_batch = models.ForeignKey(
        OpeningBalanceImport,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='opening_balance_lines',
    )
    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='opening_balance_lines',
    )
    line_type = models.CharField(max_length=40, choices=LINE_TYPE_CHOICES, default='gl_control')
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_lines',
    )
    vendor_name = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    source_object_type = models.CharField(max_length=80, blank=True)
    source_object_id = models.CharField(max_length=80, blank=True)
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS_CHOICES,
        default='pending',
    )
    validation_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['import_batch', 'id']
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(debit__gt=0, credit=MONEY_ZERO)
                    | Q(credit__gt=0, debit=MONEY_ZERO)
                ),
                name='accounting_opening_balance_line_one_side',
            ),
        ]

    def clean(self):
        debit = self.debit or MONEY_ZERO
        credit = self.credit or MONEY_ZERO
        if (debit > MONEY_ZERO and credit > MONEY_ZERO) or (debit <= MONEY_ZERO and credit <= MONEY_ZERO):
            raise ValidationError('Opening balance line must have either a debit or a credit amount, not both.')
        if self.import_batch_id and self.entity_id and self.import_batch.entity_id != self.entity_id:
            raise ValidationError('Opening balance line must use the same entity as the import batch.')
        if self.account_id and self.entity_id and self.account.entity_id != self.entity_id:
            raise ValidationError('Opening balance line account must belong to the same entity.')
        if self.line_type in ('subscriber_ar', 'customer_advance') and not self.subscriber_id:
            raise ValidationError('Subscriber AR and customer advance opening lines require a subscriber.')
        if self.line_type == 'ap_vendor' and not self.vendor_name:
            raise ValidationError('AP vendor opening lines require a vendor name.')

    def _assert_import_mutable(self):
        if not self.import_batch_id:
            return
        import_batch = OpeningBalanceImport.objects.select_related('cutover_plan', 'journal_entry').get(pk=self.import_batch_id)
        if import_batch.cutover_plan.status in CUTOVER_LOCKED_STATUSES:
            raise ValidationError('Approved or live cutover plans are locked.')
        if import_batch.status in ('journal_created', 'posted', 'voided') or import_batch.journal_entry_id:
            raise ValidationError('Opening balance lines linked to a journal are read-only.')

    def save(self, *args, **kwargs):
        self._assert_import_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_import_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        side = 'Dr' if self.debit else 'Cr'
        amount = self.debit or self.credit
        return f"{side} {self.account.code} {amount}"


class CutoverReconciliationSnapshot(models.Model):
    STATUS_CHOICES = [
        ('generated', 'Generated'),
        ('reconciled', 'Reconciled'),
        ('voided', 'Voided'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='cutover_reconciliation_snapshots',
    )
    cutover_plan = models.ForeignKey(
        CutoverPlan,
        on_delete=models.PROTECT,
        related_name='reconciliation_snapshots',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generated')
    ar_source_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    ar_opening_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    ar_difference = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    advance_source_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    advance_opening_total = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    advance_difference = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    source_invoice_count = models.PositiveIntegerField(default=0)
    source_credit_subscriber_count = models.PositiveIntegerField(default=0)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_cutover_reconciliation_snapshots',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-generated_at', '-id']
        permissions = [
            ('manage_cutoverreconciliationsnapshot', 'Can manage Accounting v2 cutover reconciliation snapshots'),
        ]

    @property
    def all_matched(self):
        totals_match = self.ar_difference == MONEY_ZERO and self.advance_difference == MONEY_ZERO
        if not self.pk:
            return totals_match
        return totals_match and not self.subscriber_lines.exclude(status='matched').exists()

    def clean(self):
        if self.cutover_plan_id and self.entity_id and self.cutover_plan.entity_id != self.entity_id:
            raise ValidationError('Cutover reconciliation snapshot must use the same entity as the cutover plan.')

    def __str__(self):
        generated_at = self.generated_at.strftime('%Y-%m-%d %H:%M') if self.generated_at else 'unsaved'
        return f"{self.entity} reconciliation snapshot {generated_at}"


class CutoverSubscriberBalanceLine(models.Model):
    BALANCE_TYPE_CHOICES = [
        ('subscriber_ar', 'Subscriber AR'),
        ('customer_advance', 'Customer Advance'),
    ]
    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('missing_opening', 'Missing Opening Balance'),
        ('missing_source', 'Opening Without Source'),
        ('difference', 'Difference'),
    ]

    snapshot = models.ForeignKey(
        CutoverReconciliationSnapshot,
        on_delete=models.CASCADE,
        related_name='subscriber_lines',
    )
    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='cutover_subscriber_balance_lines',
    )
    subscriber = models.ForeignKey(
        'subscribers.Subscriber',
        on_delete=models.CASCADE,
        related_name='cutover_balance_lines',
    )
    balance_type = models.CharField(max_length=30, choices=BALANCE_TYPE_CHOICES)
    source_balance = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    difference = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    source_count = models.PositiveIntegerField(default=0)
    opening_line_count = models.PositiveIntegerField(default=0)
    source_references = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='matched')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['balance_type', 'subscriber__username', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['snapshot', 'subscriber', 'balance_type'],
                name='accounting_unique_cutover_subscriber_balance_line',
            ),
        ]

    def clean(self):
        if self.snapshot_id and self.entity_id and self.snapshot.entity_id != self.entity_id:
            raise ValidationError('Subscriber balance line must use the same entity as the snapshot.')

    def __str__(self):
        return f"{self.get_balance_type_display()} {self.subscriber}: {self.difference}"


class CutoverBalanceSchedule(models.Model):
    SCHEDULE_TYPE_CHOICES = [
        ('cash_on_hand', 'Cash on Hand'),
        ('bank_account', 'Bank Accounts'),
        ('wallet_gateway', 'Wallet / Gateway Clearing'),
        ('accounts_payable', 'Accounts Payable'),
        ('tax_balance', 'Tax Balances'),
        ('inventory', 'Inventory'),
        ('fixed_assets', 'Fixed Assets and Depreciation'),
        ('loans_payable', 'Loans Payable'),
        ('equity_balance', 'Equity Balances'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('needs_review', 'Needs Review'),
        ('reconciled', 'Reconciled'),
        ('voided', 'Voided'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='cutover_balance_schedules',
    )
    cutover_plan = models.ForeignKey(
        CutoverPlan,
        on_delete=models.PROTECT,
        related_name='balance_schedules',
    )
    schedule_type = models.CharField(max_length=30, choices=SCHEDULE_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    total_debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    total_credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    opening_total_debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    opening_total_credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    difference = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    validation_errors = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_cutover_balance_schedules',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_cutover_balance_schedules',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['cutover_plan', 'schedule_type']
        constraints = [
            models.UniqueConstraint(
                fields=['cutover_plan', 'schedule_type'],
                condition=~Q(status='voided'),
                name='accounting_unique_active_cutover_balance_schedule',
            ),
        ]
        permissions = [
            ('manage_cutoverbalanceschedule', 'Can manage Accounting v2 cutover balance schedules'),
        ]

    @property
    def all_matched(self):
        return self.status == 'reconciled' and self.difference == MONEY_ZERO

    def clean(self):
        if self.cutover_plan_id and self.entity_id and self.cutover_plan.entity_id != self.entity_id:
            raise ValidationError('Cutover balance schedule must use the same entity as the cutover plan.')

    def __str__(self):
        return f"{self.cutover_plan.cutover_date} - {self.get_schedule_type_display()}"


class CutoverBalanceScheduleLine(models.Model):
    VALIDATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('valid', 'Valid'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]

    schedule = models.ForeignKey(
        CutoverBalanceSchedule,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='cutover_balance_schedule_lines',
    )
    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='cutover_balance_schedule_lines',
    )
    label = models.CharField(max_length=255)
    reference = models.CharField(max_length=255, blank=True)
    counterparty_name = models.CharField(max_length=255, blank=True)
    statement_date = models.DateField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal('0.0000'))
    unit = models.CharField(max_length=40, blank=True)
    location = models.CharField(max_length=255, blank=True)
    asset_identifier = models.CharField(max_length=120, blank=True)
    acquisition_date = models.DateField(null=True, blank=True)
    useful_life_months = models.PositiveIntegerField(null=True, blank=True)
    maturity_date = models.DateField(null=True, blank=True)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=MONEY_ZERO)
    source_document_number = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS_CHOICES,
        default='pending',
    )
    validation_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['schedule', 'account__code', 'label', 'id']
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(debit__gt=0, credit=MONEY_ZERO)
                    | Q(credit__gt=0, debit=MONEY_ZERO)
                ),
                name='accounting_cutover_schedule_line_one_side',
            ),
        ]

    def clean(self):
        debit = self.debit or MONEY_ZERO
        credit = self.credit or MONEY_ZERO
        if (debit > MONEY_ZERO and credit > MONEY_ZERO) or (debit <= MONEY_ZERO and credit <= MONEY_ZERO):
            raise ValidationError('Schedule line must have either a debit or a credit amount, not both.')
        if self.schedule_id and self.entity_id and self.schedule.entity_id != self.entity_id:
            raise ValidationError('Schedule line must use the same entity as the schedule.')
        if self.account_id and self.entity_id and self.account.entity_id != self.entity_id:
            raise ValidationError('Schedule line account must belong to the same entity.')
        if self.schedule_id and self.schedule.schedule_type == 'accounts_payable' and not self.counterparty_name:
            raise ValidationError('Accounts payable schedule lines require a vendor or payee name.')
        if self.schedule_id and self.schedule.schedule_type == 'inventory':
            if (self.quantity or Decimal('0.0000')) <= Decimal('0.0000'):
                raise ValidationError('Inventory schedule lines require quantity.')
            if not self.unit:
                raise ValidationError('Inventory schedule lines require a unit of measure.')
        if self.schedule_id and self.schedule.schedule_type == 'loans_payable' and not self.counterparty_name:
            raise ValidationError('Loan schedule lines require a lender name.')

    def _assert_schedule_mutable(self):
        if not self.schedule_id:
            return
        if CutoverBalanceSchedule.objects.filter(pk=self.schedule_id, status='voided').exists():
            raise ValidationError('Voided cutover balance schedules are read-only.')
        if CutoverBalanceSchedule.objects.filter(
            pk=self.schedule_id,
            cutover_plan__status__in=CUTOVER_LOCKED_STATUSES,
        ).exists():
            raise ValidationError('Approved or live cutover plans are locked.')

    def save(self, *args, **kwargs):
        self._assert_schedule_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_schedule_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        side = 'Dr' if self.debit else 'Cr'
        amount = self.debit or self.credit
        return f"{side} {self.account.code} {amount} - {self.label}"


class AlphanumericTaxCode(models.Model):
    TAX_FAMILY_CHOICES = [
        ('expanded_withholding_tax', 'Expanded Withholding Tax'),
        ('creditable_vat_withheld', 'Creditable VAT Withheld'),
        ('percentage_tax_withheld', 'Percentage Tax Withheld'),
        ('final_withholding_tax', 'Final Withholding Tax'),
        ('income_tax', 'Income Tax'),
        ('other', 'Other'),
    ]
    TAXPAYER_TYPE_CHOICES = [
        ('individual', 'Individual'),
        ('corporation', 'Corporation'),
        ('both', 'Individual / Corporation'),
        ('not_applicable', 'Not Applicable'),
    ]
    PAYOR_TYPE_CHOICES = [
        ('any', 'Any Payor'),
        ('private_withholding_agent', 'Private Withholding Agent'),
        ('top_withholding_agent', 'Top Withholding Agent'),
        ('government', 'Government / GOCC'),
        ('other', 'Other'),
    ]

    code = models.CharField(max_length=30, unique=True)
    description = models.TextField()
    tax_family = models.CharField(
        max_length=40,
        choices=TAX_FAMILY_CHOICES,
        default='expanded_withholding_tax',
    )
    taxpayer_type = models.CharField(
        max_length=30,
        choices=TAXPAYER_TYPE_CHOICES,
        default='not_applicable',
    )
    rate = models.DecimalField(max_digits=7, decimal_places=4, default=MONEY_ZERO)
    rate_label = models.CharField(max_length=80, blank=True)
    bir_form = models.CharField(max_length=120, blank=True)
    payor_type = models.CharField(max_length=40, choices=PAYOR_TYPE_CHOICES, default='any')
    source_reference = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tax_family', 'code']

    def clean(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError('ATC effective end date cannot be before start date.')

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.description}"


class WithholdingTaxClass(models.Model):
    TAX_FAMILY_CHOICES = [
        ('expanded_withholding_tax', 'Expanded Withholding Tax'),
        ('creditable_vat_withheld', 'Creditable VAT Withheld'),
        ('percentage_tax_withheld', 'Percentage Tax Withheld'),
        ('other_creditable_withholding', 'Other Creditable Withholding'),
    ]
    BASIS_CHOICES = [
        ('gross_payment', 'Gross Payment'),
        ('vatable_base', 'VATable Base'),
        ('gross_invoice', 'Gross Invoice'),
        ('manual', 'Manual Amount'),
    ]
    PAYOR_TYPE_CHOICES = [
        ('any', 'Any Payor'),
        ('private_withholding_agent', 'Private Withholding Agent'),
        ('top_withholding_agent', 'Top Withholding Agent'),
        ('government', 'Government / GOCC'),
        ('other', 'Other'),
    ]
    SUPPLIER_TAXPAYER_TYPE_CHOICES = [
        ('any', 'Any Supplier Type'),
        ('sole_proprietor', 'Sole Proprietor'),
        ('corporation', 'Corporation'),
    ]
    SUPPLIER_TAX_CLASSIFICATION_CHOICES = [
        ('any', 'Any Tax Classification'),
        ('vat', 'VAT'),
        ('non_vat', 'Non-VAT'),
    ]

    entity = models.ForeignKey(
        AccountingEntity,
        on_delete=models.CASCADE,
        related_name='withholding_tax_classes',
    )
    atc_code = models.ForeignKey(
        AlphanumericTaxCode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='withholding_tax_classes',
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=255)
    tax_family = models.CharField(
        max_length=40,
        choices=TAX_FAMILY_CHOICES,
        default='expanded_withholding_tax',
    )
    atc = models.CharField(max_length=30, blank=True)
    rate = models.DecimalField(max_digits=7, decimal_places=4, default=MONEY_ZERO)
    basis = models.CharField(max_length=30, choices=BASIS_CHOICES, default='gross_payment')
    payor_type = models.CharField(max_length=40, choices=PAYOR_TYPE_CHOICES, default='any')
    supplier_taxpayer_type = models.CharField(
        max_length=30,
        choices=SUPPLIER_TAXPAYER_TYPE_CHOICES,
        default='any',
    )
    supplier_tax_classification = models.CharField(
        max_length=20,
        choices=SUPPLIER_TAX_CLASSIFICATION_CHOICES,
        default='any',
    )
    bir_reference = models.CharField(max_length=255, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['entity', 'tax_family', 'code', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'code'],
                name='accounting_unique_withholding_tax_class_code',
            ),
        ]

    def clean(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError('Withholding tax class end date cannot be before start date.')
        if self.atc:
            self.atc = self.atc.upper().strip()
        if self.atc_code_id and not self.atc:
            self.atc = self.atc_code.code

    def __str__(self):
        return f"{self.code} - {self.name}"


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
    withholding_class = models.ForeignKey(
        WithholdingTaxClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_withholding_claims',
    )
    atc_code = models.ForeignKey(
        AlphanumericTaxCode,
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
