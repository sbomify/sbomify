from django import forms


class CreateAccessTokenForm(forms.Form):
    description = forms.CharField(max_length=255)
