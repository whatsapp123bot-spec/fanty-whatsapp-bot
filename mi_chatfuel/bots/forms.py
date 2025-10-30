from django import forms
from .models import Bot, Flow


class BotForm(forms.ModelForm):
    class Meta:
        model = Bot
        fields = [
            'name',
            'phone_number_id',
            'access_token',
            'verify_token',
            'is_active',
        ]
        widgets = {
            'access_token': forms.Textarea(attrs={'rows': 3}),
        }


class FlowForm(forms.ModelForm):
    class Meta:
        model = Flow
        fields = ['name', 'definition', 'is_active']
        widgets = {
            'definition': forms.Textarea(attrs={'rows': 12}),
        }
