"""Forms for document metadata editing."""

from django import forms

from .models import Document


class DocumentMetadataForm(forms.ModelForm):
    """Form for editing document metadata."""

    class Meta:
        model = Document
        fields = ["name", "version", "document_type", "description"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Enter document name"
            }),
            "version": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., 1.0, v2.1, latest"
            }),
            "document_type": forms.Select(attrs={
                "class": "form-select"
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Brief description of the document..."
            }),
        }
        labels = {
            "name": "Document Name",
            "version": "Version",
            "document_type": "Document Type",
            "description": "Description",
        }
        help_texts = {
            "name": "The display name for this document",
            "version": "Version identifier for this document",
            "document_type": "Categorize the document type for better organization",
            "description": "Optional description of the document content",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make name required
        self.fields["name"].required = True

        # Make optional fields truly optional
        self.fields["version"].required = False
        self.fields["document_type"].required = False
        self.fields["description"].required = False

        # Add empty option to document_type
        self.fields["document_type"].empty_label = "Select document type (optional)"

        # Set initial values
        if not self.instance.pk:  # New document
            self.fields["version"].initial = "1.0"
