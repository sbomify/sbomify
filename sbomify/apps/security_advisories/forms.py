"""Validation for the New Advisory form.

A plain ``Form`` rather than a ``ModelForm``: one submission writes an advisory,
its products, a vulnerability, per-product statuses and release ranges, so there
is no single model to bind.
"""

from __future__ import annotations

from typing import Any

from django import forms

from sbomify.apps.core.models import Product, Release
from sbomify.apps.security_advisories.models import CVE_ID_RE, SecurityAdvisory, Severity
from sbomify.apps.teams.models import Team


class AdvisoryCreateForm(forms.Form):
    """The New Advisory form's fields, scoped to one workspace.

    ``products`` and ``affected_releases`` querysets are restricted to the team
    at construction, so another workspace's ids fail validation rather than
    silently attaching foreign rows.
    """

    title = forms.CharField(max_length=255)
    severity = forms.ChoiceField(choices=Severity.choices, required=False)
    # Where the team already is on fixing it. Most advisories open at
    # "identified", but one being written up after the work started should not
    # have to be created wrong and then corrected on its own timeline.
    remediation_status = forms.ChoiceField(choices=SecurityAdvisory.RemediationStatus.choices, required=False)
    # The form's single identifier field: a CVE, another database's id
    # (GHSA-…), or a URL. clean_vulnerability_id sorts out which.
    vulnerability_id = forms.CharField(max_length=100, required=False)
    # The number the Trust Center leads with. The vector is optional context
    # that names its own CVSS version; clean() refuses a vector without a
    # score, which would store an entry the pages could never render.
    cvss_score = forms.FloatField(
        required=False,
        min_value=0,
        max_value=10,
        error_messages={
            "invalid": "CVSS score must be a number from 0 to 10.",
            "min_value": "CVSS score must be a number from 0 to 10.",
            "max_value": "CVSS score must be a number from 0 to 10.",
        },
    )
    cvss_vector = forms.CharField(max_length=255, required=False)
    description = forms.CharField(required=False, widget=forms.Textarea)
    products = forms.ModelMultipleChoiceField(queryset=Product.objects.none(), required=False)
    affected_releases = forms.ModelMultipleChoiceField(queryset=Release.objects.none(), required=False)

    def __init__(self, team: Team, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["products"].queryset = Product.objects.filter(team=team)  # type: ignore[attr-defined]
        # ``latest`` is a floating pointer that re-targets as artifacts arrive,
        # so pinning it as an affected version would change meaning over time.
        self.fields["affected_releases"].queryset = Release.objects.filter(  # type: ignore[attr-defined]
            product__team=team, is_latest=False
        )

    def clean_vulnerability_id(self) -> str:
        identifier = (self.cleaned_data.get("vulnerability_id") or "").strip()
        # Normalise the case CVE ids are quoted in; other schemes keep the
        # user's casing since detect_reference_type matches case-insensitively.
        if CVE_ID_RE.match(identifier.upper()):
            return identifier.upper()
        return identifier

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        selected = {product.id for product in cleaned.get("products") or []}
        stray = [release for release in cleaned.get("affected_releases") or [] if release.product_id not in selected]
        if stray:
            self.add_error("affected_releases", "Affected releases must belong to a selected product.")
        # Guarded on the field's own errors: a score that failed to parse also
        # cleans to None, and telling the user to enter one they typed is worse
        # than the parse error already queued.
        vector_without_score = (cleaned.get("cvss_vector") or "").strip() and cleaned.get("cvss_score") is None
        if vector_without_score and "cvss_score" not in self.errors:
            self.add_error("cvss_score", "Enter the CVSS score for the vector.")
        return cleaned
