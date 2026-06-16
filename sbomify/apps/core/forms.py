from __future__ import annotations

import json
from typing import Any

import requests
from django import forms
from django.conf import settings

from sbomify.apps.core.integrations.http import post_form


class CreateAccessTokenForm(forms.Form):
    # Default token lifetime. Tokens used to live forever (security issue
    # #215); new tokens expire after 90 days unless the user explicitly
    # opts out via the "No expiration" choice.
    DEFAULT_EXPIRY_DAYS = 90
    EXPIRY_CHOICES = [
        ("30", "30 days"),
        ("60", "60 days"),
        ("90", "90 days"),
        ("365", "1 year"),
        ("never", "No expiration"),
    ]

    description = forms.CharField(
        max_length=255,
        error_messages={"required": "Please provide a name for the token."},
    )
    expires_in_days = forms.ChoiceField(
        choices=EXPIRY_CHOICES,
        required=False,
        initial=str(DEFAULT_EXPIRY_DAYS),
        label="Expiration",
        widget=forms.Select(attrs={"class": "tw-form-select"}),
    )

    # Action scope (#215). "full" = unscoped (legacy default); the others narrow
    # what the token may do regardless of the user's role. Maps to a concrete
    # scope list via authz.SCOPE_PRESETS so the choices can't drift from the
    # action vocabulary can() enforces.
    SCOPE_CHOICES = [
        ("full", "Full access"),
        ("publish", "Publish only (CI/CD upload)"),
        ("read_only", "Read-only"),
    ]
    scope = forms.ChoiceField(
        choices=SCOPE_CHOICES,
        required=False,
        initial="full",
        label="Access scope",
        widget=forms.Select(attrs={"class": "tw-form-select"}),
    )

    def scopes(self) -> list[str] | None:
        """Chosen action scopes, or ``None`` for an unscoped (full) token.

        Only valid after ``is_valid()``.
        """
        from sbomify.apps.core.authz import SCOPE_PRESETS

        # Direct index (not .get) so a SCOPE_CHOICES/SCOPE_PRESETS drift raises
        # KeyError instead of silently falling through to a full token. The
        # choice is validated against SCOPE_CHOICES (a subset of the preset keys),
        # and a blank choice (required=False) falls back to "full".
        preset = SCOPE_PRESETS[self.cleaned_data.get("scope") or "full"]
        # Copy the preset list so a caller mutating token.scopes in place can't
        # corrupt the shared SCOPE_PRESETS value (None stays None — full token).
        return list(preset) if preset is not None else None

    def expiry_days(self) -> int | None:
        """Chosen token lifetime in days, or ``None`` for no expiration.

        An omitted/blank choice falls back to the secure default
        (90 days); the explicit ``"never"`` sentinel maps to ``None``.
        Only valid after ``is_valid()``.
        """
        choice = self.cleaned_data.get("expires_in_days") or str(self.DEFAULT_EXPIRY_DAYS)
        return None if choice == "never" else int(choice)


class TogglePublicStatusForm(forms.Form):
    is_public = forms.BooleanField(required=False)


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Make Turnstile token required unless in DEBUG mode
        if not settings.DEBUG:
            self.fields["cf_turnstile_response"].required = True

    def clean_message(self) -> str:
        """Validate message length and content."""
        message = self.cleaned_data.get("message", "")

        if len(message.strip()) < 10:
            raise forms.ValidationError("Please provide a more detailed message (at least 10 characters).")

        return message.strip()  # type: ignore[no-any-return]

    def clean_subject(self) -> str:
        """Clean and validate subject."""
        subject = self.cleaned_data.get("subject", "")
        return subject.strip()  # type: ignore[no-any-return]

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
            response = post_form(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.TURNSTILE_SECRET_KEY,
                    "response": token,
                },
            )
            result = response.json()

            if not result.get("success", False):
                raise forms.ValidationError("Security verification failed. Please try again.")

        except (requests.RequestException, json.JSONDecodeError):
            raise forms.ValidationError("Unable to verify security check. Please try again.")

        return token  # type: ignore[no-any-return]
