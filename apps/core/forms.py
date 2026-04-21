from django import forms
from django.contrib.auth.models import User
from apps.core.models import SystemSetup


class FirstRunForm(forms.Form):
    isp_name = forms.CharField(max_length=255, label='ISP Name')
    isp_address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), label='Address')
    isp_phone = forms.CharField(max_length=50, label='Phone Number')
    isp_email = forms.EmailField(label='Email')

    admin_username = forms.CharField(max_length=150, label='Admin Username')
    admin_email = forms.EmailField(label='Admin Email')
    admin_password = forms.CharField(widget=forms.PasswordInput, label='Password')
    admin_password_confirm = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')

    def clean_admin_username(self):
        username = self.cleaned_data['admin_username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        pw1 = cleaned.get('admin_password')
        pw2 = cleaned.get('admin_password_confirm')
        if pw1 and pw2 and pw1 != pw2:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned
