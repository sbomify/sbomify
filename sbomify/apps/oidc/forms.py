"""Forms for OIDC binding management."""

from __future__ import annotations

import re

from django import forms

from sbomify.apps.oidc.models import OIDCBinding

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class OIDCBindingForm(forms.Form):
    """Workspace-owner-facing form to set up a new trusted-publisher binding.

    Provider is hardcoded to GitHub for v1 (matches the user-selected
    scope in the design). When other providers are added the choice
    list lives here; the model already supports more via its
    ``PROVIDER_CHOICES``.
    """

    provider = forms.ChoiceField(
        choices=OIDCBinding.PROVIDER_CHOICES,
        initial=OIDCBinding.PROVIDER_GITHUB,
        widget=forms.Select(attrs={"class": "tw-form-select"}),
    )
    repository = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "tw-form-input",
                "placeholder": "org/repo",
                "autocomplete": "off",
            },
        ),
        help_text=(
            "GitHub repository in 'org/repo' form. Only workflows from this exact "
            "repository will be able to upload to this component."
        ),
    )

    def clean_repository(self) -> str:
        value = (self.cleaned_data.get("repository") or "").strip()
        if not _REPO_PATTERN.fullmatch(value):
            raise forms.ValidationError(
                "Repository must be in the form 'org/repo' (letters, digits, '.', '_', '-' only)."
            )
        # Normalise to lowercase for display consistency; the canonical
        # case comes back from GitHub's API in the view.
        return value
