from django import forms
from django.utils import timezone
from apps.billing.models import Invoice


class PaymentForm(forms.Form):
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('gcash', 'GCash'),
        ('bank', 'Bank Transfer'),
        ('maya', 'Maya'),
        ('other', 'Other'),
    ]

    amount = forms.DecimalField(max_digits=10, decimal_places=2)
    method = forms.ChoiceField(choices=METHOD_CHOICES)
    reference = forms.CharField(max_length=255, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
    paid_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    def clean_paid_at(self):
        return self.cleaned_data.get('paid_at') or timezone.now()


class RateChangeForm(forms.Form):
    APPLY_MODE_CHOICES = [
        ('next_only', 'Next Invoice Only (safe, no surprises)'),
        ('all_unpaid', 'All Unpaid Invoices from Effective Date'),
        ('manual', 'Let me choose which invoices to update'),
    ]

    plan = forms.ModelChoiceField(
        queryset=None, required=False, empty_label='-- No Plan --'
    )
    monthly_rate = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    effective_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    apply_mode = forms.ChoiceField(choices=APPLY_MODE_CHOICES)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        from apps.subscribers.models import Plan
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = Plan.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('plan') and not cleaned.get('monthly_rate'):
            raise forms.ValidationError('Provide either a plan or a monthly rate.')
        return cleaned
