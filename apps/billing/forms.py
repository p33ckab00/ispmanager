from decimal import Decimal

from django import forms
from django.utils import timezone


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
    has_withholding = forms.BooleanField(required=False)
    withholding_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.01'),
    )
    withholding_rate = forms.DecimalField(
        max_digits=7,
        decimal_places=4,
        required=False,
        min_value=Decimal('0.0000'),
    )
    atc = forms.CharField(max_length=30, required=False)
    withholding_status = forms.ChoiceField(
        choices=[
            ('pending_2307', 'Pending 2307'),
            ('received', '2307 Received'),
            ('customer_claimed', 'Customer Claimed'),
        ],
        required=False,
    )
    period_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    period_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    payor_tin = forms.CharField(max_length=50, required=False)
    payor_name = forms.CharField(max_length=255, required=False)
    payor_address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
    certificate_number = forms.CharField(max_length=120, required=False)
    certificate_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    received_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        self.open_balance = kwargs.pop('open_balance', None)
        subscriber = kwargs.pop('subscriber', None)
        super().__init__(*args, **kwargs)
        if subscriber and not self.initial.get('payor_name'):
            self.initial['payor_name'] = subscriber.display_name

    def clean_paid_at(self):
        return self.cleaned_data.get('paid_at') or timezone.now()

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount') or Decimal('0.00')
        has_withholding = cleaned.get('has_withholding')
        withholding_amount = cleaned.get('withholding_amount') or Decimal('0.00')
        period_from = cleaned.get('period_from')
        period_to = cleaned.get('period_to')
        received_date = cleaned.get('received_date')
        certificate_date = cleaned.get('certificate_date')

        if not has_withholding:
            cleaned['withholding_amount'] = Decimal('0.00')
            return cleaned

        if withholding_amount <= Decimal('0.00'):
            self.add_error('withholding_amount', 'Enter the EWT/CWT amount withheld by the customer.')
        if amount <= Decimal('0.00'):
            self.add_error('amount', 'Cash received must be greater than zero.')
        if self.open_balance is not None and amount + withholding_amount > self.open_balance:
            raise forms.ValidationError(
                'Cash received plus EWT/CWT cannot exceed the current open invoice balance.'
            )
        if period_from and period_to and period_to < period_from:
            self.add_error('period_to', '2307 period end cannot be before period start.')
        if received_date and not certificate_date:
            self.add_error('certificate_date', 'Enter the certificate date when marking 2307 as received.')

        return cleaned

    def get_withholding_data(self):
        if not self.cleaned_data.get('has_withholding'):
            return None
        tax_withheld = self.cleaned_data.get('withholding_amount') or Decimal('0.00')
        if tax_withheld <= Decimal('0.00'):
            return None
        return {
            'gross_amount': (self.cleaned_data.get('amount') or Decimal('0.00')) + tax_withheld,
            'tax_withheld': tax_withheld,
            'withholding_rate': self.cleaned_data.get('withholding_rate') or Decimal('0.0000'),
            'atc': self.cleaned_data.get('atc') or '',
            'period_from': self.cleaned_data.get('period_from'),
            'period_to': self.cleaned_data.get('period_to'),
            'payor_tin': self.cleaned_data.get('payor_tin') or '',
            'payor_name': self.cleaned_data.get('payor_name') or '',
            'payor_address': self.cleaned_data.get('payor_address') or '',
            'certificate_number': self.cleaned_data.get('certificate_number') or '',
            'certificate_date': self.cleaned_data.get('certificate_date'),
            'received_date': self.cleaned_data.get('received_date'),
            'status': self.cleaned_data.get('withholding_status') or 'pending_2307',
        }


class RefundCompletionForm(forms.Form):
    reference = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500',
            'placeholder': 'GCash, bank transfer, voucher, or OR reference',
        }),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500',
        }),
    )
    paid_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'type': 'datetime-local',
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500',
        }),
    )
    create_expense = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'mt-0.5 w-4 h-4 rounded border-gray-300 text-orange-600',
        }),
        help_text='Create a matching accounting expense record.',
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
