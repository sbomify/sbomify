import os

from django.http import JsonResponse
from django.urls import path
from django.urls.resolvers import URLPattern

from sbomify.apps.vulnerability_scanning.views_scans import VulnerabilityScansView

from . import views


def domain_check(request):
    """
    RFC 8615 .well-known endpoint for sbomify domain verification.

    Returns structured JSON response for any request that passes Django's ALLOWED_HOSTS validation.
    Used by the domain verification task to confirm DNS points to our server.

    Domain validation is handled by CustomDomainContextMiddleware, which runs
    before this view — so by the time we get here, the domain is already validated.

    Returns:
        JSON response with domain verification status and metadata
    """
    from django.utils import timezone

    from sbomify.apps.teams.utils import normalize_host

    host = normalize_host(request.META.get("HTTP_HOST", ""))

    return JsonResponse(
        {
            "ok": True,
            "service": "sbomify",
            "domain": host,
            "ts": timezone.now().isoformat(),
            "region": os.environ.get("AWS_REGION", "auto"),
        }
    )


app_name = "teams"
urlpatterns: list[URLPattern] = [
    path("", views.WorkspacesDashboardView.as_view(), name="teams_dashboard"),
    path("switch/<team_key>/", views.switch_team, name="switch_team"),
    path("invite/<team_key>/", views.invite, name="invite_user"),
    path("accept_invite/<invite_token>/", views.accept_invite, name="accept_invite"),
    path("<membership_id>/leave", views.delete_member, name="team_membership_delete"),
    path("<invitation_id>/uninvite", views.delete_invite, name="team_invitation_delete"),
    path("onboarding/", views.OnboardingWizardView.as_view(), name="onboarding_wizard"),
    # Backward compatibility redirects - must come before general patterns
    path("settings/", views.settings_redirect, name="settings_redirect"),
    path("<team_key>/settings/", views.team_settings_redirect, name="team_settings_redirect"),
    # Keep team_details as an alias that redirects to team_settings for backward compatibility
    path("<team_key>/details", views.team_details, name="team_details"),
    path("<team_key>/vulnerability-scans", VulnerabilityScansView.as_view(), name="vulnerability_scans"),
    # Contact profiles HTMX endpoints
    path("<team_key>/contact-profiles", views.ContactProfileView.as_view(), name="contact_profiles_list"),
    path(
        "<team_key>/contact-profiles/form",
        views.ContactProfileFormView.as_view(),
        name="contact_profiles_form",
    ),
    path(
        "<team_key>/contact-profiles/<profile_id>/form",
        views.ContactProfileFormView.as_view(),
        name="contact_profiles_detail_form",
    ),
    path(
        "<team_key>/branding",
        views.TeamBrandingView.as_view(),
        name="team_branding",
    ),
    path(
        "<team_key>/general",
        views.TeamGeneralView.as_view(),
        name="team_general",
    ),
    path(
        "<team_key>/custom-domain",
        views.TeamCustomDomainView.as_view(),
        name="team_custom_domain",
    ),
    path(
        "<team_key>/tokens",
        views.TeamTokensView.as_view(),
        name="team_tokens",
    ),
    # Main team settings (unified interface) - must come after specific patterns
    path("<team_key>", views.TeamSettingsView.as_view(), name="team_settings"),
]
