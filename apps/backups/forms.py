from django import forms

from apps.backups.models import ProductionRestorePlan


class BackupImportValidationForm(forms.Form):
    file = forms.FileField(help_text='Upload a PostgreSQL backup file for validation only.')

    def clean_file(self):
        upload = self.cleaned_data['file']
        filename = upload.name.lower()
        allowed_suffixes = ('.dump', '.sql', '.sql.gz', '.dump.gz')
        if not filename.endswith(allowed_suffixes):
            raise forms.ValidationError('Upload a .dump, .sql, .sql.gz, or .dump.gz backup file.')
        return upload


class ProductionRestorePlanForm(forms.ModelForm):
    class Meta:
        model = ProductionRestorePlan
        fields = [
            'maintenance_window_starts_at',
            'maintenance_window_ends_at',
            'authorized_by_name',
            'authorization_reference',
            'rollback_plan',
            'post_restore_validation_plan',
            'notes',
            'current_state_backup_confirmed',
            'maintenance_window_confirmed',
            'scheduler_stop_confirmed',
            'writes_blocked_confirmed',
            'rollback_plan_confirmed',
            'post_restore_validation_confirmed',
        ]
        widgets = {
            'maintenance_window_starts_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
            'maintenance_window_ends_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
            'rollback_plan': forms.Textarea(attrs={'rows': 4}),
            'post_restore_validation_plan': forms.Textarea(attrs={'rows': 4}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        text_input_class = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm'
        checkbox_class = 'mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600'
        for name in [
            'maintenance_window_starts_at',
            'maintenance_window_ends_at',
            'authorized_by_name',
            'authorization_reference',
        ]:
            self.fields[name].widget.attrs['class'] = text_input_class
        for name in ['rollback_plan', 'post_restore_validation_plan', 'notes']:
            self.fields[name].widget.attrs['class'] = text_input_class
        for name in [
            'current_state_backup_confirmed',
            'maintenance_window_confirmed',
            'scheduler_stop_confirmed',
            'writes_blocked_confirmed',
            'rollback_plan_confirmed',
            'post_restore_validation_confirmed',
        ]:
            self.fields[name].widget.attrs['class'] = checkbox_class

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get('maintenance_window_starts_at')
        ends_at = cleaned_data.get('maintenance_window_ends_at')
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error(
                'maintenance_window_ends_at',
                'Maintenance window end must be later than the start.',
            )
        return cleaned_data
