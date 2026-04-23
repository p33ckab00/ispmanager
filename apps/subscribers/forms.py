from datetime import date
from django import forms
from apps.subscribers.models import Subscriber, Plan


class SubscriberBillingFieldsMixin:
    def clean_cutoff_day(self):
        day = self.cleaned_data.get('cutoff_day')
        if day in (None, ''):
            return None
        if not 1 <= int(day) <= 28:
            raise forms.ValidationError('Cutoff day must be between 1 and 28.')
        return day

    def clean_billing_due_days(self):
        due_days = self.cleaned_data.get('billing_due_days')
        if due_days in (None, ''):
            return None
        if int(due_days) < 0:
            raise forms.ValidationError('Due offset must be 0 or higher.')
        return due_days


class SubscriberAdminForm(SubscriberBillingFieldsMixin, forms.ModelForm):
    class Meta:
        model = Subscriber
        fields = [
            'full_name', 'phone', 'address', 'email',
            'latitude', 'longitude', 'cutoff_day', 'billing_effective_from',
            'billing_due_days', 'is_billable', 'start_date', 'status', 'notes', 'sms_opt_out',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'format': '%Y-%m-%d'}),
            'billing_effective_from': forms.DateInput(attrs={'type': 'date', 'format': '%Y-%m-%d'}),
        }

    def clean_status(self):
        status = self.cleaned_data.get('status', 'active')
        allowed = ['active', 'inactive', 'suspended']
        if status not in allowed:
            return 'active'
        return status


class RateChangeForm(forms.Form):
    APPLY_MODE_CHOICES = [
        ('next_only', 'Next invoice only (safe)'),
        ('all_unpaid', 'All unpaid invoices from effective date'),
        ('manual', 'Let me choose which invoices to update'),
    ]

    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True),
        required=False,
        empty_label='-- No Plan --',
    )
    monthly_rate = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        help_text='Leave blank to use plan rate.',
    )
    effective_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=date.today,
    )
    apply_mode = forms.ChoiceField(choices=APPLY_MODE_CHOICES)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('plan') and not cleaned.get('monthly_rate'):
            raise forms.ValidationError('Provide a plan or a monthly rate.')
        return cleaned


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['name', 'speed_down_mbps', 'speed_up_mbps', 'monthly_rate', 'description', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class ManualSubscriberForm(SubscriberBillingFieldsMixin, forms.ModelForm):
    class Meta:
        model = Subscriber
        fields = [
            'username', 'mt_password', 'mt_profile', 'service_type',
            'full_name', 'phone', 'address', 'email',
            'cutoff_day', 'billing_effective_from', 'billing_due_days',
            'is_billable', 'start_date', 'status', 'notes',
        ]
        widgets = {
            'mt_password': forms.PasswordInput(render_value=True),
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'billing_effective_from': forms.DateInput(attrs={'type': 'date'}),
        }


class StatusChangeForm(forms.Form):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('inactive', 'Inactive'),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class DisconnectForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Reason for disconnection (client request, relocation, etc.)',
    )


class SuspensionHoldForm(forms.Form):
    suspension_hold_until = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M'],
        help_text='Service may stay active until this date/time even if billing is overdue.',
    )
    suspension_hold_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional note such as promise-to-pay or approved extension reason.',
    )

    def clean(self):
        cleaned = super().clean()
        hold_until = cleaned.get('suspension_hold_until')
        if hold_until is not None:
            from django.utils import timezone
            if hold_until <= timezone.now():
                raise forms.ValidationError('Palugit end must be in the future.')
        return cleaned


class DeceasedForm(forms.Form):
    deceased_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=date.today,
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional notes (obituary reference, next of kin info, etc.)',
    )


class OTPRequestForm(forms.Form):
    phone = forms.CharField(max_length=20, label='Phone Number')


class OTPVerifyForm(forms.Form):
    phone = forms.CharField(max_length=20, widget=forms.HiddenInput)
    code = forms.CharField(max_length=6, label='OTP Code')
