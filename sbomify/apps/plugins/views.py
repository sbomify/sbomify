"""Views for the plugins framework."""

import uuid
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.logging import getLogger

from .apis import UpdateTeamPluginSettingsRequest, get_team_plugin_settings, update_team_plugin_settings

logger = getLogger(__name__)


class TeamPluginSettingsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing team plugin settings."""

    allowed_roles = list(ADMINISTER)

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Render the plugin settings page."""
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, plugin_settings = get_team_plugin_settings(request, team_key)
        if status_code != 200:
            return htmx_error_response(plugin_settings.get("detail", "Failed to load settings"))

        # Pre-compute values for Django template compatibility
        enabled_plugins = plugin_settings.get("enabled_plugins", [])
        plugin_configs = plugin_settings.get("plugin_configs", {})
        plugins = plugin_settings.get("available_plugins", [])
        for plugin in plugins:
            plugin["is_enabled"] = plugin["name"] in enabled_plugins and plugin.get("has_access", False)
            schema = plugin.get("config_schema") or []
            for field in schema:
                field["current_value"] = plugin_configs.get(plugin["name"], {}).get(field.get("key", ""), "")
            # A select with no choices flagged hide_if_no_choices is skipped in the
            # template. If every field is skipped the config section would still render
            # an empty bordered div (a stray divider under the plugin), so only mark it
            # renderable when at least one field will actually show.
            plugin["has_visible_config"] = any(
                not (f.get("type") == "select" and not f.get("choices") and f.get("hide_if_no_choices")) for f in schema
            )
        # Group into category sections in the template. The per-plugin "<plan>+ Plan"
        # badge conveys plan gating, so the previous global "Requires Plan Upgrade"
        # divider is dropped. Sort so regroup produces contiguous category blocks in
        # a stable, sensible order.
        # Every AssessmentCategory (sdk.enums) is listed so none falls into the unknown
        # bucket; anything unlisted still degrades gracefully via the category tiebreaker.
        category_order = {"compliance": 0, "license": 1, "security": 2, "attestation": 3}
        # Group by category for {% regroup %} (which only groups adjacent rows, so the
        # category string keeps same-category plugins contiguous even when two unknown
        # categories both fall back to 99). Within a category, preserve the API's ordering:
        # accessible plugins before upgrade-gated ones, then by display name.
        plugins.sort(
            key=lambda p: (
                category_order.get(p.get("category", ""), 99),
                p.get("category", ""),
                p.get("requires_upgrade", False),
                p.get("display_name", ""),
            )
        )

        return render(
            request,
            "plugins/team_plugin_settings.html.j2",
            {
                "team": team,
                "plugin_settings": plugin_settings,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Update plugin settings."""
        # Get enabled plugins from form data (checkboxes)
        enabled_plugins = request.POST.getlist("enabled_plugins")

        # Build plugin configs from form data
        plugin_configs: dict[str, dict[str, Any]] = {}
        for key, value in request.POST.items():
            if key.startswith("plugin_config_"):
                # Extract plugin name and config key
                # Format: plugin_config_<plugin_name>_<config_key>
                parts = key[len("plugin_config_") :].split("_", 1)
                if len(parts) == 2:
                    plugin_name, config_key = parts
                    if plugin_name not in plugin_configs:
                        plugin_configs[plugin_name] = {}
                    plugin_configs[plugin_name][config_key] = value

        payload = UpdateTeamPluginSettingsRequest(
            enabled_plugins=enabled_plugins,
            plugin_configs=plugin_configs if plugin_configs else None,
        )

        status_code, result = update_team_plugin_settings(request, team_key, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update settings"))

        return htmx_success_response(
            "Plugin settings updated successfully",
            triggers={"refreshPluginSettings": True},
        )


def _build_plugin_stats(request: HttpRequest, team_key: str) -> dict[str, Any] | None:
    """Build plugin summary stats from the API."""
    status_code, plugin_settings = get_team_plugin_settings(request, team_key)
    if status_code != 200:
        # Intentionally do NOT include team_key in the log message: CodeQL
        # flags it as "clear-text logging of sensitive information" because
        # team_key is a URL path parameter (user-controlled input). Structured
        # log correlation for this warning is available via the request's
        # standard Django request-id middleware, which already scopes every
        # log entry to the team implicitly through the URL.
        logger.warning("Failed to load plugin settings: status=%s", status_code)
        return None

    available = plugin_settings.get("available_plugins", [])
    enabled_names = set(plugin_settings.get("enabled_plugins", []))

    # Count only plugins that are both enabled AND accessible (matches toggle UI)
    enabled_count = sum(1 for p in available if p["name"] in enabled_names and p.get("has_access", False))

    categories: dict[str, int] = {}
    for p in available:
        cat = p.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total": len(available),
        "enabled": enabled_count,
        "categories": categories,
    }


class PluginsPageView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Standalone plugins page accessible from the sidebar.

    Summary stats are loaded lazily via HTMX (PluginsSummaryView) to avoid
    a redundant get_team_plugin_settings call on initial page load.
    """

    allowed_roles = list(ADMINISTER)

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the standalone plugins page."""
        return render(request, "plugins/plugins_page.html.j2")


class PluginsSummaryView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """HTMX partial: returns the plugin summary bar with counts."""

    allowed_roles = list(ADMINISTER)

    def get(self, request: HttpRequest) -> HttpResponse:
        """Return the summary bar partial."""
        team_data = request.session.get("current_team", {})
        team_key = team_data.get("key", "")

        context: dict[str, Any] = {}
        if team_key:
            stats = _build_plugin_stats(request, team_key)
            if stats:
                context["plugin_stats"] = stats

        return render(request, "plugins/plugins_summary.html.j2", context)


class AssessmentRunFindingsView(LoginRequiredMixin, View):
    """One page of a single assessment run's findings.

    The run card on the artifact page renders its header from ``result.summary``,
    which is a handful of integers however large the scan was. The findings list
    is the part that grows with the SBOM, and rendering every finding of every
    plugin is what took that page past the gateway timeout. This endpoint serves
    the list for one run, one page at a time, when a reader opens the card.

    Authorized by the same ``component:access`` check the assessments API runs,
    so this adds no reachable data beyond what that endpoint already answers.
    """

    #: Findings per page. Matches the vulnerabilities panel so a reader moving
    #: between the two is paging at the same rate.
    page_size = 25

    def get(self, request: HttpRequest, run_id: str) -> HttpResponse:
        from django.core.paginator import Paginator

        from sbomify.apps.core.authz import can
        from sbomify.apps.vulnerability_scanning.euvd import euvd_ids_for_serialization
        from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization

        from .apis import _readable_sbom, _result_with_kev
        from .models import AssessmentRun
        from .templatetags.plugins_extras import vulnerability_findings

        try:
            # The id reaches this from a template, so a value that is not a UUID
            # at all is a 404 rather than the ValidationError the field lookup
            # would otherwise raise.
            uuid.UUID(run_id)
        except ValueError:
            return HttpResponseNotFound("Assessment run not found")

        run = AssessmentRun.objects.filter(id=run_id).first()
        if run is None:
            # 404 rather than 403 for a run this reader has no business with:
            # confirming one exists at that id is itself an answer.
            return HttpResponseNotFound("Assessment run not found")
        sbom = _readable_sbom(request, str(run.sbom_id))
        if sbom is None:
            return HttpResponseNotFound("Assessment run not found")

        is_security = run.category == "security"
        kev_ids = kev_ids_for_serialization() if is_security else frozenset()
        euvd_ids = euvd_ids_for_serialization() if is_security else frozenset()
        result = _result_with_kev(run, kev_ids, euvd_ids)
        findings = result.get("findings") if isinstance(result, dict) else None
        if not isinstance(findings, list):
            findings = []
        if is_security:
            # Scanner status markers ride the same array and are not
            # vulnerabilities, the same filter the eager list used to apply.
            findings = vulnerability_findings(findings)

        paginator = Paginator(findings, self.page_size)
        page = paginator.get_page(request.GET.get("page"))
        base_url = reverse("plugins:assessment_run_findings", args=[str(run.id)])
        return render(
            request,
            "plugins/components/_assessment_run_findings.html.j2",
            {
                "run": run,
                "is_security": is_security,
                "findings": list(page.object_list),
                "can_triage": can(request, "artifact:publish_vex", sbom.component),
                "page": page.number,
                "page_count": paginator.num_pages,
                "has_prev": page.has_previous(),
                "has_next": page.has_next(),
                "prev_url": f"{base_url}?page={page.previous_page_number()}" if page.has_previous() else "",
                "next_url": f"{base_url}?page={page.next_page_number()}" if page.has_next() else "",
            },
        )
