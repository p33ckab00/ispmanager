from django import forms
from apps.settings_app.models import BillingSettings, SMSSettings, TelegramSettings, RouterSettings
from apps.core.models import SystemSetup


class SystemInfoForm(forms.ModelForm):
    class Meta:
        model = SystemSetup
        fields = ['isp_name', 'isp_address', 'isp_phone', 'isp_email', 'isp_logo']
        widgets = {'isp_address': forms.Textarea(attrs={'rows': 3})}


class BillingSettingsForm(forms.ModelForm):
    class Meta:
        model = BillingSettings
        fields = [
            'billing_day', 'due_days', 'grace_period_days', 'currency_symbol',
            'enable_auto_generate', 'enable_auto_disconnect',
            'billing_mode', 'billing_snapshot_mode', 'draft_auto_freeze_hours',
            'billing_due_offset_days',
        ]

    def clean_billing_day(self):
        day = self.cleaned_data['billing_day']
        if not 1 <= day <= 28:
            raise forms.ValidationError('Billing day must be between 1 and 28.')
        return day

    def clean_due_days(self):
        due_days = self.cleaned_data['due_days']
        if due_days < 0:
            raise forms.ValidationError('Default due days must be 0 or higher.')
        return due_days

    def clean_billing_due_offset_days(self):
        due_offset = self.cleaned_data['billing_due_offset_days']
        if due_offset < 0:
            raise forms.ValidationError('Default due offset must be 0 or higher.')
        return due_offset


class SMSSettingsForm(forms.ModelForm):
    class Meta:
        model = SMSSettings
        fields = [
            'semaphore_api_key', 'sender_name', 'enable_billing_sms',
            'billing_sms_schedule', 'billing_sms_days_before_due', 'billing_sms_template',
        ]
        widgets = {
            'semaphore_api_key': forms.PasswordInput(render_value=True),
            'billing_sms_template': forms.Textarea(attrs={'rows': 4}),
        }

    def clean_sender_name(self):
        name = self.cleaned_data['sender_name']
        if len(name) > 11:
            raise forms.ValidationError('Sender name cannot exceed 11 characters.')
        return name


class TelegramSettingsForm(forms.ModelForm):
    class Meta:
        model = TelegramSettings
        fields = '__all__'
        exclude = ['updated_at']
        widgets = {'bot_token': forms.PasswordInput(render_value=True)}


class RouterSettingsForm(forms.ModelForm):
    class Meta:
        model = RouterSettings
        fields = [
            'default_api_port', 'polling_interval_seconds',
            'sync_on_startup', 'connection_timeout_seconds',
        ]
