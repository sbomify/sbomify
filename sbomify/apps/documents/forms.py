from django import forms

from .models import Document


class DocumentEditForm(forms.Form):
    """Form for editing document metadata."""

    document_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )
    name = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter document name"}),
    )
    version = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter version (e.g., 1.0)"}),
    )
    document_type = forms.ChoiceField(
        required=False,
        choices=Document.DocumentType.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 3, "placeholder": "Enter description (optional)"}
        ),
    )


class DocumentDeleteForm(forms.Form):
    """Form for deleting a document."""

    document_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )
