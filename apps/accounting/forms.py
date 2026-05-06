from django import forms
from apps.accounting.models import IncomeRecord, ExpenseRecord, JournalEntry
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
