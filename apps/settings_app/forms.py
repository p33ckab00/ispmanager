from django import forms
from apps.settings_app.models import (
    BackupSettings,
    BillingSettings,
    RouterSettings,
    SMSSettings,
    TelegramSettings,
)
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
        if not 1 <= day <= 31:
            raise forms.ValidationError('Billing day must be between 1 and 31.')
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
            'billing_sms_schedule', 'billing_sms_days_before_due',
            'billing_sms_repeat_interval_days', 'billing_sms_send_after_due',
            'billing_sms_after_due_interval_days', 'billing_sms_template',
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

    def clean_billing_sms_days_before_due(self):
        days = self.cleaned_data['billing_sms_days_before_due']
        if days < 0:
            raise forms.ValidationError('Days before due date must be 0 or higher.')
        return days

    def clean_billing_sms_repeat_interval_days(self):
        days = self.cleaned_data['billing_sms_repeat_interval_days']
        if days < 1:
            raise forms.ValidationError('Repeat interval must be at least 1 day.')
        return days

    def clean_billing_sms_after_due_interval_days(self):
        days = self.cleaned_data['billing_sms_after_due_interval_days']
        if days < 1:
            raise forms.ValidationError('After-due interval must be at least 1 day.')
        return days


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


class BackupSettingsForm(forms.ModelForm):
    class Meta:
        model = BackupSettings
        fields = [
            'backup_root',
            'pg_dump_path',
            'filename_prefix',
            'manual_backups_enabled',
            'partial_backups_enabled',
            'allow_backup_download',
            'allow_backup_delete',
            'retention_keep_last',
            'minimum_free_space_mb',
            'scheduled_backups_enabled',
            'scheduled_backup_time',
            'scheduled_backup_profile',
            'weekly_backup_enabled',
            'remote_copy_enabled',
            'remote_backend',
            'encryption_enabled',
            'backup_failure_alerts_enabled',
            'backup_stale_after_hours',
            'restore_test_enabled',
        ]
        widgets = {
            'scheduled_backup_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
        }

    def clean_backup_root(self):
        backup_root = self.cleaned_data['backup_root'].strip()
        if not backup_root.startswith('/'):
            raise forms.ValidationError('Backup root must be an absolute filesystem path.')
        return backup_root.rstrip('/') or '/'

    def clean_filename_prefix(self):
        prefix = self.cleaned_data['filename_prefix'].strip()
        allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        if not prefix or any(char not in allowed for char in prefix):
            raise forms.ValidationError('Filename prefix may contain only letters, numbers, hyphen, and underscore.')
        return prefix

    def clean_retention_keep_last(self):
        value = self.cleaned_data['retention_keep_last']
        if value < 1:
            raise forms.ValidationError('Retention must keep at least one backup.')
        return value

    def clean_minimum_free_space_mb(self):
        value = self.cleaned_data['minimum_free_space_mb']
        if value < 256:
            raise forms.ValidationError('Minimum free space guard must be at least 256 MB.')
        return value

    def clean_backup_stale_after_hours(self):
        value = self.cleaned_data['backup_stale_after_hours']
        if value < 1:
            raise forms.ValidationError('Stale backup alert threshold must be at least one hour.')
        return value
