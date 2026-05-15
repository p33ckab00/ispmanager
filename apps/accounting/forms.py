from decimal import Decimal

from django import forms
from django.db.models import Sum

from apps.accounting.models import (
    AccountingReportPreset,
    AlphanumericTaxCode,
    APVendor,
    APVendorBill,
    APVendorBillAttachment,
    APVendorPayment,
    ChartOfAccount,
    CutoverBalanceSchedule,
    CutoverBalanceScheduleLine,
    CutoverPlan,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    OpeningBalanceImport,
    OpeningBalanceLine,
    WithholdingTaxClass,
)
from apps.accounting.services import (
    available_coa_templates,
    available_cutover_balance_schedule_types,
)
from apps.subscribers.models import Subscriber


class AccountingSetupForm(forms.Form):
    name = forms.CharField(max_length=255, initial='ISP Operator')
    legal_name = forms.CharField(max_length=255, required=False)
    tin = forms.CharField(max_length=50, required=False)
    registered_address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    template_key = forms.ChoiceField(label='COA template')
    fiscal_year = forms.IntegerField(min_value=2020, max_value=2099)
    require_period_close_review = forms.BooleanField(required=False)
    require_period_reopen_review = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template_key'].choices = [
            (item['key'], item['label'])
            for item in available_coa_templates()
        ]


class JournalEntryHeaderForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['entry_date', 'description', 'reference']
        widgets = {
            'entry_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={'placeholder': 'Manual journal description'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Optional reference'}),
        }


class AccountingReportPresetForm(forms.ModelForm):
    class Meta:
        model = AccountingReportPreset
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Preset name'}),
        }


class CutoverPlanForm(forms.ModelForm):
    class Meta:
        model = CutoverPlan
        fields = ['cutover_date', 'source_policy', 'notes']
        widgets = {
            'cutover_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }


class OpeningBalanceImportForm(forms.ModelForm):
    class Meta:
        model = OpeningBalanceImport
        fields = ['import_type', 'source_filename', 'source_hash']
        widgets = {
            'source_filename': forms.TextInput(attrs={'placeholder': 'Optional source file or worksheet name'}),
            'source_hash': forms.TextInput(attrs={'placeholder': 'Optional checksum or file hash'}),
        }


class OpeningBalanceLineForm(forms.ModelForm):
    class Meta:
        model = OpeningBalanceLine
        fields = [
            'line_type',
            'account',
            'debit',
            'credit',
            'subscriber',
            'vendor_name',
            'reference',
            'description',
        ]
        widgets = {
            'vendor_name': forms.TextInput(attrs={'placeholder': 'Required for AP vendor lines'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Statement, invoice, subscriber, or schedule reference'}),
            'description': forms.TextInput(attrs={'placeholder': 'Opening balance description'}),
        }

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = ChartOfAccount.objects.none()
        if entity:
            self.fields['account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
            ).order_by('code')
        self.fields['subscriber'].queryset = Subscriber.objects.order_by('username')
        self.fields['subscriber'].required = False
        self.fields['subscriber'].empty_label = 'No subscriber'
        self.fields['debit'].required = False
        self.fields['credit'].required = False

    def clean_debit(self):
        return self.cleaned_data.get('debit') or Decimal('0.00')

    def clean_credit(self):
        return self.cleaned_data.get('credit') or Decimal('0.00')


class CutoverBalanceScheduleForm(forms.ModelForm):
    class Meta:
        model = CutoverBalanceSchedule
        fields = ['schedule_type', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['schedule_type'].choices = [
            (item['key'], item['label'])
            for item in available_cutover_balance_schedule_types()
        ]


class CutoverBalanceScheduleLineForm(forms.ModelForm):
    class Meta:
        model = CutoverBalanceScheduleLine
        fields = [
            'account',
            'label',
            'reference',
            'counterparty_name',
            'statement_date',
            'quantity',
            'unit',
            'location',
            'asset_identifier',
            'acquisition_date',
            'useful_life_months',
            'maturity_date',
            'debit',
            'credit',
            'source_document_number',
            'notes',
        ]
        widgets = {
            'statement_date': forms.DateInput(attrs={'type': 'date'}),
            'acquisition_date': forms.DateInput(attrs={'type': 'date'}),
            'maturity_date': forms.DateInput(attrs={'type': 'date'}),
            'label': forms.TextInput(attrs={'placeholder': 'Cash count, CPE batch, asset, lender, equity support, or tax account'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Statement, inventory count, asset register, loan, invoice, or worksheet'}),
            'counterparty_name': forms.TextInput(attrs={'placeholder': 'Vendor/payee/lender; required for AP and loan schedules'}),
            'unit': forms.TextInput(attrs={'placeholder': 'pcs, meters, units, lots'}),
            'location': forms.TextInput(attrs={'placeholder': 'Warehouse, POP, cabinet, site, or area'}),
            'asset_identifier': forms.TextInput(attrs={'placeholder': 'Asset tag, serial number, batch, or loan account'}),
            'source_document_number': forms.TextInput(attrs={'placeholder': 'Return, ledger, deed, asset register, loan agreement, or worksheet'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = ChartOfAccount.objects.none()
        if entity:
            self.fields['account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
            ).order_by('code')
        self.fields['debit'].required = False
        self.fields['credit'].required = False
        self.fields['quantity'].required = False
        self.fields['useful_life_months'].required = False

    def clean_debit(self):
        return self.cleaned_data.get('debit') or Decimal('0.00')

    def clean_credit(self):
        return self.cleaned_data.get('credit') or Decimal('0.00')

    def clean_quantity(self):
        return self.cleaned_data.get('quantity') or Decimal('0.0000')


class APVendorBillForm(forms.ModelForm):
    class Meta:
        model = APVendorBill
        fields = [
            'vendor',
            'vendor_name',
            'bill_number',
            'document_date',
            'due_date',
            'tax_treatment',
            'expense_account',
            'ap_account',
            'base_amount',
            'input_vat_amount',
            'amount',
            'notes',
        ]
        widgets = {
            'document_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'vendor_name': forms.TextInput(attrs={'placeholder': 'Vendor or supplier name'}),
            'bill_number': forms.TextInput(attrs={'placeholder': 'Supplier invoice or bill number'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.fields['vendor'].queryset = APVendor.objects.none()
        self.fields['vendor'].required = False
        self.fields['vendor_name'].required = False
        self.fields['expense_account'].queryset = ChartOfAccount.objects.none()
        self.fields['ap_account'].queryset = ChartOfAccount.objects.none()
        if entity:
            self.fields['vendor'].queryset = APVendor.objects.filter(
                entity=entity,
                is_active=True,
            ).order_by('name', 'code')
            if entity.tax_classification != 'vat':
                self.fields['tax_treatment'].choices = [
                    choice for choice in self.fields['tax_treatment'].choices
                    if choice[0] != 'vat'
                ]
            self.fields['expense_account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
                account_type__in=['direct_cost', 'expense', 'other_expense', 'asset'],
            ).order_by('code')
            self.fields['ap_account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
                account_type='liability',
            ).order_by('code')

    def clean_vendor_name(self):
        vendor_name = self.cleaned_data.get('vendor_name', '').strip()
        vendor = self.cleaned_data.get('vendor')
        if not vendor_name and vendor:
            return vendor.display_name
        if not vendor_name:
            raise forms.ValidationError('Enter a vendor name or choose an AP vendor.')
        return vendor_name


class APVendorForm(forms.ModelForm):
    class Meta:
        model = APVendor
        fields = [
            'code',
            'name',
            'registered_name',
            'tin',
            'registered_address',
            'email',
            'phone',
            'tax_classification',
            'default_expense_account',
            'default_ap_account',
            'is_active',
            'notes',
        ]
        widgets = {
            'registered_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['default_expense_account'].queryset = ChartOfAccount.objects.none()
        self.fields['default_ap_account'].queryset = ChartOfAccount.objects.none()
        if entity:
            self.fields['default_expense_account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
                account_type__in=['direct_cost', 'expense', 'other_expense', 'asset'],
            ).order_by('code')
            self.fields['default_ap_account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
                account_type='liability',
            ).order_by('code')


class APVendorBillAttachmentForm(forms.ModelForm):
    class Meta:
        model = APVendorBillAttachment
        fields = ['document_type', 'file', 'note']

    def clean_file(self):
        upload = self.cleaned_data['file']
        filename = upload.name.lower()
        allowed_suffixes = ('.pdf', '.jpg', '.jpeg', '.png', '.csv', '.xls', '.xlsx')
        if not filename.endswith(allowed_suffixes):
            raise forms.ValidationError('Upload a PDF, image, CSV, or Excel supporting file.')
        if upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Upload a file no larger than 10 MB.')
        return upload


class APVendorBillVoidForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Reason for voiding this bill'}),
    )


class APVendorPaymentForm(forms.ModelForm):
    class Meta:
        model = APVendorPayment
        fields = ['payment_date', 'cash_account', 'amount', 'reference']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Check, bank transfer, or wallet reference'}),
        }

    def __init__(self, *args, entity=None, bill=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bill = bill
        self.fields['cash_account'].queryset = ChartOfAccount.objects.none()
        if entity:
            self.fields['cash_account'].queryset = ChartOfAccount.objects.filter(
                entity=entity,
                is_active=True,
                account_type='asset',
                code__in=['1000', '1010', '1020'],
            ).order_by('code')

    def clean_amount(self):
        amount = self.cleaned_data.get('amount') or Decimal('0.00')
        if self.bill:
            existing_total = (
                self.bill.payments
                .exclude(status='voided')
                .exclude(void_journal_entry__status='posted')
                .aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )
            remaining = self.bill.amount - existing_total
            if amount > remaining:
                raise forms.ValidationError('Payment cannot exceed the remaining bill balance.')
        return amount


class APVendorPaymentVoidForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Reason for voiding this payment'}),
    )


class APVendorPaymentSettlementForm(forms.Form):
    settlement_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    settlement_reference = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={'placeholder': 'Bank statement, check clearing, or wallet settlement reference'}),
    )
    settlement_note = forms.CharField(max_length=255, required=False)


class IncomeForm(forms.ModelForm):
    class Meta:
        model = IncomeRecord
        fields = ['source', 'description', 'amount', 'reference', 'recorded_by', 'date']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = ExpenseRecord
        fields = ['category', 'description', 'amount', 'reference', 'vendor', 'recorded_by', 'date']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class WithholdingTaxClassForm(forms.ModelForm):
    class Meta:
        model = WithholdingTaxClass
        fields = [
            'atc_code',
            'code',
            'name',
            'tax_family',
            'atc',
            'rate',
            'basis',
            'payor_type',
            'supplier_taxpayer_type',
            'supplier_tax_classification',
            'bir_reference',
            'effective_from',
            'effective_to',
            'is_active',
            'notes',
        ]
        widgets = {
            'effective_from': forms.DateInput(attrs={'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['atc_code'].queryset = AlphanumericTaxCode.objects.filter(
            is_active=True,
            bir_form__icontains='2307',
        ).order_by('tax_family', 'code')
        self.fields['atc_code'].required = False
        self.fields['atc_code'].empty_label = 'Manual / no ATC catalog code'

    def clean(self):
        cleaned = super().clean()
        atc_code = cleaned.get('atc_code')
        if atc_code:
            cleaned['atc'] = cleaned.get('atc') or atc_code.code
            if not cleaned.get('rate') or cleaned.get('rate') == Decimal('0.0000'):
                cleaned['rate'] = atc_code.rate
            if not cleaned.get('bir_reference'):
                cleaned['bir_reference'] = atc_code.source_reference
        return cleaned
