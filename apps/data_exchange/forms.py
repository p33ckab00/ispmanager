from django import forms


class BaseImportForm(forms.Form):
    file = forms.FileField(help_text='Upload a CSV file.')

    def clean_file(self):
        upload = self.cleaned_data['file']
        if not upload.name.lower().endswith('.csv'):
            raise forms.ValidationError('Only CSV files are supported for v1 imports.')
        return upload


class SubscriberImportForm(BaseImportForm):
    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text='If enabled, matching usernames update existing subscriber records.',
    )


class PaymentImportForm(BaseImportForm):
    pass
