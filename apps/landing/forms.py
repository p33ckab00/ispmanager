from django import forms

from apps.landing.models import LandingFAQ, LandingInquiry, LandingPlan


class LandingFAQForm(forms.ModelForm):
    class Meta:
        model = LandingFAQ
        fields = ['question', 'answer', 'is_published', 'sort_order']
        widgets = {
            'answer': forms.Textarea(attrs={'rows': 4}),
        }


class LandingInquiryForm(forms.ModelForm):
    preferred_plan = forms.ChoiceField(required=False)

    class Meta:
        model = LandingInquiry
        fields = ['full_name', 'mobile_number', 'service_address', 'preferred_plan', 'message']
        widgets = {
            'service_address': forms.Textarea(attrs={'rows': 3}),
            'message': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, page=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.page = page
        choices = [('', 'I am not sure yet')]
        if page is not None:
            choices.extend(
                (plan.name, plan.name)
                for plan in LandingPlan.objects.filter(page=page).order_by('sort_order', 'id')
            )
        self.fields['preferred_plan'].choices = choices


class LandingInquiryStatusForm(forms.ModelForm):
    class Meta:
        model = LandingInquiry
        fields = ['status']
