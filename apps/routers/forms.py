from django import forms
from apps.routers.models import Router, RouterInterface


class RouterForm(forms.ModelForm):
    class Meta:
        model = Router
        fields = ['name', 'host', 'username', 'password', 'api_port', 'description', 'location']
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_api_port(self):
        port = self.cleaned_data['api_port']
        if not 1 <= port <= 65535:
            raise forms.ValidationError('Port must be between 1 and 65535.')
        return port


class RouterCoordinatesForm(forms.ModelForm):
    class Meta:
        model = Router
        fields = ['latitude', 'longitude', 'location']


class InterfaceLabelForm(forms.ModelForm):
    class Meta:
        model = RouterInterface
        fields = ['label', 'role', 'comment']
