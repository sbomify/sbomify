import json

import requests
from django import forms
from django.conf import settings
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError

from sboms.models import Component, ComponentAuthor, ComponentSupplierContact, ComponentLicense


class CreateAccessTokenForm(forms.Form):
    description = forms.CharField(max_length=255)


class SupportContactForm(forms.Form):
    """Form for general support contact inquiries."""

    # Contact Information
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your first name"}),
        label="First Name",
    )

    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your last name"}),
        label="Last Name",
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "your.email@example.com"}),
        label="Email Address",
    )

    # Support Request Details
    SUPPORT_TYPE_CHOICES = [
        ("", "Select support type"),
        ("bug", "Bug Report"),
        ("feature", "Feature Request"),
        ("account", "Account Issue"),
        ("billing", "Billing Question"),
        ("technical", "Technical Support"),
        ("general", "General Question"),
        ("other", "Other"),
    ]

    support_type = forms.ChoiceField(
        choices=SUPPORT_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Type of Support Request",
    )

    subject = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Brief description of your issue"}),
        label="Subject",
    )

    message = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": (
                    "Please describe your issue or question in detail. "
                    "Include any relevant information that might help us assist you better."
                ),
            }
        ),
        label="Message",
    )

    # System Information (optional, to help with troubleshooting)
    browser_info = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Chrome 120, Safari 17, etc."}),
        label="Browser/Version (Optional)",
        help_text="Helpful for technical issues",
    )

    # Cloudflare Turnstile token
    cf_turnstile_response = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,  # Will be set to True in production
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make Turnstile token required unless in DEBUG mode
        if not settings.DEBUG:
            self.fields["cf_turnstile_response"].required = True

    def clean_message(self) -> str:
        """Validate message length and content."""
        message = self.cleaned_data.get("message", "")

        if len(message.strip()) < 10:
            raise forms.ValidationError("Please provide a more detailed message (at least 10 characters).")

        return message.strip()

    def clean_subject(self) -> str:
        """Clean and validate subject."""
        subject = self.cleaned_data.get("subject", "")
        return subject.strip()

    def clean_cf_turnstile_response(self) -> str:
        """Validate Cloudflare Turnstile response."""
        token = self.cleaned_data.get("cf_turnstile_response")

        # Skip Turnstile validation in development mode
        if settings.DEBUG:
            return token or "dev-mode-bypass"

        if not token:
            raise forms.ValidationError("Please complete the security verification.")

        # Verify token with Cloudflare
        try:
            response = requests.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.TURNSTILE_SECRET_KEY,
                    "response": token,
                },
                timeout=10,
            )
            result = response.json()

            if not result.get("success", False):
                raise forms.ValidationError("Security verification failed. Please try again.")

        except (requests.RequestException, json.JSONDecodeError):
            raise forms.ValidationError("Unable to verify security check. Please try again.")

        return token


# =============================================================================
# COMPONENT METADATA FORMS
# =============================================================================


class ComponentMetadataForm(forms.ModelForm):
    """Main form for component metadata including supplier information and lifecycle."""

    class Meta:
        model = Component
        fields = [
            'supplier_name',
            'supplier_url',
            'supplier_address',
            'lifecycle_phase'
        ]
        widgets = {
            'supplier_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter supplier name'
            }),
            'supplier_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter supplier address'
            }),
            'lifecycle_phase': forms.Select(attrs={
                'class': 'form-select'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Custom handling for supplier_url JSONField
        if self.instance and self.instance.pk:
            urls = self.instance.supplier_url or []
            # Convert list to newline-separated string for textarea
            self.fields['supplier_url'] = forms.CharField(
                widget=forms.Textarea(attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Enter supplier URLs (one per line)'
                }),
                initial='\n'.join(urls),
                required=False,
                help_text='Enter one URL per line',
                label='Supplier URLs'
            )
        else:
            self.fields['supplier_url'] = forms.CharField(
                widget=forms.Textarea(attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Enter supplier URLs (one per line)'
                }),
                required=False,
                help_text='Enter one URL per line',
                label='Supplier URLs'
            )

    def clean_supplier_url(self):
        """Convert textarea content back to list of URLs."""
        urls_text = self.cleaned_data.get('supplier_url', '')
        if not urls_text.strip():
            return []

        urls = [url.strip() for url in urls_text.strip().split('\n') if url.strip()]

        # Validate each URL
        for url in urls:
            try:
                # Basic URL validation
                if not (url.startswith('http://') or url.startswith('https://')):
                    raise ValidationError(f'Invalid URL: {url}. URLs must start with http:// or https://')
            except Exception as e:
                raise ValidationError(f'Invalid URL: {url}')

        return urls


class ComponentSupplierContactForm(forms.ModelForm):
    """Form for supplier contact information."""

    class Meta:
        model = ComponentSupplierContact
        fields = ['name', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact name',
                'required': True
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'contact@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+1 (555) 123-4567'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['email'].required = False
        self.fields['phone'].required = False


class ComponentAuthorForm(forms.ModelForm):
    """Form for component author information."""

    class Meta:
        model = ComponentAuthor
        fields = ['name', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Author name',
                'required': True
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'author@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+1 (555) 123-4567'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['email'].required = False
        self.fields['phone'].required = False


class ComponentLicenseForm(forms.ModelForm):
    """Form for component license information."""

    # SPDX license selection with autocomplete (loaded from API data)
    spdx_license_choice = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control spdx-license-autocomplete',
            'placeholder': 'Search for a license (e.g., MIT, Apache-2.0)...',
            'autocomplete': 'off',
            'data-bs-toggle': 'dropdown',
            'aria-expanded': 'false'
        }),
        label='Quick Select SPDX License'
    )

    class Meta:
        model = ComponentLicense
        fields = ['license_type', 'license_id', 'license_name', 'license_url', 'license_text']
        labels = {
            'license_type': 'License Type',
            'license_id': 'License ID or Expression',
            'license_name': 'License Name',
            'license_url': 'License URL',
            'license_text': 'License Text',
        }
        widgets = {
            'license_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'license_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., MIT or MIT OR Apache-2.0'
            }),
            'license_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Custom license name'
            }),
            'license_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/license'
            }),
            'license_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter the full license text (optional)'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set all fields as optional initially - validation happens in clean()
        self.fields['license_id'].required = False
        self.fields['license_name'].required = False
        self.fields['license_url'].required = False
        self.fields['license_text'].required = False
        self.fields['spdx_license_choice'].required = False

        # Set initial value for spdx_license_choice if editing existing SPDX license
        if self.instance and self.instance.pk and self.instance.license_type == 'spdx':
            self.fields['spdx_license_choice'].initial = self.instance.license_id

    def clean(self):
        cleaned_data = super().clean()
        license_type = cleaned_data.get('license_type')
        spdx_license_choice = cleaned_data.get('spdx_license_choice')
        license_id = cleaned_data.get('license_id')
        license_name = cleaned_data.get('license_name')

        if license_type == 'spdx':
            # For SPDX licenses, use either the choice field or direct license_id
            if spdx_license_choice:
                cleaned_data['license_id'] = spdx_license_choice
            elif not license_id:
                raise ValidationError({'license_id': 'Please select an SPDX license or enter a license ID.'})

        elif license_type == 'expression':
            if not license_id:
                raise ValidationError({'license_id': 'Please enter a license expression.'})

        elif license_type == 'custom':
            if not license_name:
                raise ValidationError({'license_name': 'Custom license name is required.'})

        return cleaned_data


# Create formsets for related models
ComponentSupplierContactFormSet = inlineformset_factory(
    Component,
    ComponentSupplierContact,
    form=ComponentSupplierContactForm,
    extra=1,  # Show one empty form by default
    can_delete=True,
    min_num=0,
    validate_min=False
)

ComponentAuthorFormSet = inlineformset_factory(
    Component,
    ComponentAuthor,
    form=ComponentAuthorForm,
    extra=1,  # Show one empty form by default
    can_delete=True,
    min_num=0,
    validate_min=False
)

ComponentLicenseFormSet = inlineformset_factory(
    Component,
    ComponentLicense,
    form=ComponentLicenseForm,
    extra=1,  # Show one empty form by default
    can_delete=True,
    min_num=0,
    validate_min=False
)


class ComponentMetadataFormSet:
    """Wrapper class to handle all component metadata forms together."""

    def __init__(self, data=None, instance=None):
        self.instance = instance
        self.data = data

        # Initialize main form and formsets
        self.metadata_form = ComponentMetadataForm(data=data, instance=instance)
        self.supplier_contact_formset = ComponentSupplierContactFormSet(
            data=data,
            instance=instance,
            prefix='supplier_contacts'
        )
        self.author_formset = ComponentAuthorFormSet(
            data=data,
            instance=instance,
            prefix='authors'
        )
        self.license_formset = ComponentLicenseFormSet(
            data=data,
            instance=instance,
            prefix='licenses'
        )

    def is_valid(self):
        """Check if all forms are valid."""
        return (
            self.metadata_form.is_valid() and
            self.supplier_contact_formset.is_valid() and
            self.author_formset.is_valid() and
            self.license_formset.is_valid()
        )

    def save(self, commit=True):
        """Save all forms."""
        if not self.is_valid():
            raise ValueError("Cannot save invalid formset")

        # Save the main metadata form
        component = self.metadata_form.save(commit=commit)

        if commit:
            # Save all the formsets
            self.supplier_contact_formset.instance = component
            self.supplier_contact_formset.save()

            self.author_formset.instance = component
            self.author_formset.save()

            self.license_formset.instance = component
            self.license_formset.save()

        return component

    @property
    def errors(self):
        """Get all errors from all forms."""
        errors = {}

        if not self.metadata_form.is_valid():
            errors['metadata'] = self.metadata_form.errors

        if not self.supplier_contact_formset.is_valid():
            errors['supplier_contacts'] = self.supplier_contact_formset.errors

        if not self.author_formset.is_valid():
            errors['authors'] = self.author_formset.errors

        if not self.license_formset.is_valid():
            errors['licenses'] = self.license_formset.errors

        return errors