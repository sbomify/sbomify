"""Forms for OIDC binding management."""

from __future__ import annotations

from django import forms

# Single source of truth for repository slug validation. Shared with the
# GitHub REST resolver in ``github_api.py`` so the form and the
# downstream API agree on what's parseable.
from sbomify.apps.oidc.github_api import REPO_PATTERN, REPO_SLUG_HELP_TEXT
from sbomify.apps.oidc.models import OIDCBinding


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
        if not REPO_PATTERN.fullmatch(value):
            raise forms.ValidationError(REPO_SLUG_HELP_TEXT)
        # Canonical-case lower-casing happens in the view from the
        # GitHub API's ``full_name`` response. Returning the raw user
        # input here keeps the form layer pure-validation.
        return value
