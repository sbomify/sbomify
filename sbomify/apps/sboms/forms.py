from django import forms


class SbomDeleteForm(forms.Form):
    sbom_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )
