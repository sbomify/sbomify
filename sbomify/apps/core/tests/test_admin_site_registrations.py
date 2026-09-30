"""App admins register on the admin site sbomify mounts."""

from __future__ import annotations

import pytest

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
