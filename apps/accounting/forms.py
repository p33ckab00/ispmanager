from decimal import Decimal

from django import forms

from apps.accounting.models import (
    AlphanumericTaxCode,
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
            'debit',
            'credit',
            'source_document_number',
            'notes',
        ]
        widgets = {
            'statement_date': forms.DateInput(attrs={'type': 'date'}),
            'label': forms.TextInput(attrs={'placeholder': 'Cash count, BDO ending balance, GCash clearing, vendor, or tax account'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Statement number, wallet report, invoice, or worksheet'}),
            'counterparty_name': forms.TextInput(attrs={'placeholder': 'Vendor/payee for AP; optional otherwise'}),
            'source_document_number': forms.TextInput(attrs={'placeholder': 'Return, ledger, worksheet, or statement reference'}),
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

    def clean_debit(self):
        return self.cleaned_data.get('debit') or Decimal('0.00')

    def clean_credit(self):
        return self.cleaned_data.get('credit') or Decimal('0.00')


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
