from django import forms
from decimal import Decimal

from apps.accounting.models import (
    AlphanumericTaxCode,
    ExpenseRecord,
    IncomeRecord,
    JournalEntry,
    WithholdingTaxClass,
)
from apps.accounting.services import available_coa_templates


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
