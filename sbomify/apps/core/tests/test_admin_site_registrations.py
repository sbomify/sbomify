"""App admins register on the admin site sbomify mounts."""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.admin import admin_site
from sbomify.apps.onboarding.models import OnboardingEmail, OnboardingStatus
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin, TeamPluginSettings


@pytest.mark.parametrize(
    "model",
    [RegisteredPlugin, TeamPluginSettings, AssessmentRun, AccessToken, OnboardingStatus, OnboardingEmail],
)
def test_the_model_is_on_the_mounted_admin_site(model) -> None:
    """``sbomify/urls.py`` mounts only core's ``admin_site``; Django's default site is never served."""
    assert admin_site.is_registered(model)


@pytest.mark.django_db
@pytest.mark.parametrize("model", [AccessToken, OnboardingStatus, OnboardingEmail])
def test_rows_the_app_creates_have_no_add_form(admin_client, model) -> None:
    """The add form cannot set the token hash or the user, so submitting it would fail on insert."""
    opts = model._meta

    response = admin_client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_add"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_the_onboarding_primary_key_cannot_be_edited(admin_client, sample_user) -> None:
    """Saving a changed primary key writes a second row rather than renaming the first."""
    status, _ = OnboardingStatus.objects.get_or_create(user=sample_user)
    email = OnboardingEmail.create_email(sample_user, OnboardingEmail.EmailType.WELCOME)

    for obj in (status, email):
        opts = obj._meta
        response = admin_client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk]))

        assert response.status_code == 200
        assert "id" not in response.context["adminform"].form.fields
