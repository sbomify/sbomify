import json

import requests
from django import forms
from django.conf import settings


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
