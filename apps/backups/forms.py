from django import forms


class BackupImportValidationForm(forms.Form):
    file = forms.FileField(help_text='Upload a PostgreSQL backup file for validation only.')

    def clean_file(self):
        upload = self.cleaned_data['file']
        filename = upload.name.lower()
        allowed_suffixes = ('.dump', '.sql', '.sql.gz', '.dump.gz')
        if not filename.endswith(allowed_suffixes):
            raise forms.ValidationError('Upload a .dump, .sql, .sql.gz, or .dump.gz backup file.')
        return upload
