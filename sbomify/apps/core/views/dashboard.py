from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key

# The Trends filters a shared link may carry. The chart view rides in the URL
# too, but only the browser reads that one, so it never reaches the fragment.
TRENDS_URL_FILTERS = ("product_id", "release_id", "days")


def trends_query(request: HttpRequest) -> str:
    """The query the Trends page fetches its fragment with.

    The page fetches its own content, so a filter in the address bar has to
    travel with that fetch or a bookmark opens on the defaults instead. Only
    the known filters travel; the fragment validates each one for itself. The
    whole string is built here rather than joined in the template, so the one
    attribute the template writes has one value and no punctuation of its own.
    """
    params = QueryDict(mutable=True)
    params["show_product_filter"] = "true"
    for name in TRENDS_URL_FILTERS:
        if name in request.GET:
            params[name] = request.GET[name]
    return params.urlencode()


class ValidateWorkspaceMixin:
    """Mixin that validates the user is still a member of their current workspace."""

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")

        if team_key:
            # Check if user is still a member of this workspace
            is_member = get_member_role_by_key(request.user, team_key) is not None

            if not is_member:
                # User was removed from this workspace, recover their session
                from sbomify.apps.teams.utils import recover_workspace_session

                return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class DashboardView(GuestAccessBlockedMixin, ValidateWorkspaceMixin, LoginRequiredMixin, View):
    show_trends: bool = False
    show_setup: bool = False

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})

        if not current_team.get("has_completed_wizard", True):
            return redirect("teams:onboarding_wizard")

        from sbomify.apps.billing.config import needs_plan_selection
        from sbomify.apps.core.services.dashboard_page import get_dashboard_workspace

        workspace_result = get_dashboard_workspace(current_team.get("key"))
        if not workspace_result.ok:
            return HttpResponse(workspace_result.error, status=workspace_result.status_code or 400)
        team = workspace_result.value

        if needs_plan_selection(team, request.user):
            return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")

        if self.show_trends:
            return render(request, "core/dashboard_trends.html.j2", {"trends_query": trends_query(request)})

        from sbomify.apps.core.services.dashboard_page import build_dashboard_context, get_first_component

        result = build_dashboard_context(team.id) if team else None
        if result is not None and not result.ok:
            return HttpResponse(result.error, status=result.status_code or 400)
        dashboard = result.value if result and result.value else {"is_first_visit": True}
        show_repository_setup = self.show_setup or dashboard.get("is_first_visit", False)

        context = {
            "current_team": current_team,
            "page_subtitle": "Prioritise vulnerabilities and keep your product evidence current.",
            "dashboard": dashboard,
            "show_repository_setup": show_repository_setup,
        }

        # An SBOM upload needs a BOM component. Without one, the empty state
        # links to component creation instead.
        if team and show_repository_setup:
            base_url = (settings.APP_BASE_URL or request.build_absolute_uri("/")).rstrip("/")
            context["onboarding"] = {
                "title": "Set up your first repository" if dashboard.get("is_first_visit") else "Set up a repository",
                "first_component": get_first_component(team.id).value,
                "setup_config": {
                    "baseUrl": base_url,
                    "instructionsUrl": base_url + reverse("core:repository_setup_instructions"),
                    "tokenUrl": reverse("core:repository_setup_token", kwargs={"workspace_key": team.key}),
                },
            }

        return render(request, "core/dashboard.html.j2", context)
