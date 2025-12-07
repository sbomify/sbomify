from django import forms

from sbomify.apps.documents.models import Document


class DocumentEditForm(forms.Form):
    document_id = forms.CharField(
        required=True,
    )
    name = forms.CharField(
        required=True,
        max_length=255,
    )
    version = forms.CharField(
        required=True,
        max_length=255,
    )
    document_type = forms.ChoiceField(
        required=False,
        choices=Document.DocumentType.choices,
    )
    description = forms.CharField(
        required=False,
    )


class DocumentDeleteForm(forms.Form):
    document_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )
