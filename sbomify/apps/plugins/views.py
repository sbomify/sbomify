"""Views for the plugins framework."""

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin, TeamRoleRequiredMixin
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


class AssessmentRunFindingsView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """One page of a single assessment run's findings.

    The run card on the artifact page renders its header from ``result.summary``
    and fetches this when a reader opens it, so a scan with thousands of
    findings costs the page nothing until someone looks.

    Authorized by the same ``component:access`` check the assessments API runs,
    so this adds no reachable data beyond what that endpoint already answers.
    Guests are blocked on top of that, the way the page this belongs to is.
    ``component:access`` is the attribute path a guest legitimately reaches
    gated trust-center content through, so without the mixin a guest redirected
    off the artifact page could still pull its fragments by URL.

    One URL, two audiences. An HTMX request gets the region; a plain one, a
    pasted link or a pager link followed with hx-boost not running, lands on the
    artifact page at that plugin's card instead of a bare fragment.
    """

    def get(self, request: HttpRequest, run_id: str) -> HttpResponse:
        from sbomify.apps.core.authz import can
        from sbomify.apps.vulnerability_scanning.services.finding_browse import query_string

        from .services.run_findings import PAGE_SIZE, PARAM_PREFIX, build_run_findings_page

        result = build_run_findings_page(request, run_id, request.GET)
        if not result.ok or result.value is None:
            return HttpResponseNotFound(result.error or "Assessment run not found")
        found = result.value

        # The header rather than django-htmx's request.htmx, the same reading the
        # vulnerabilities panel does: the middleware that sets that attribute is
        # not in the test settings.
        if not request.headers.get("HX-Request"):
            page_url = reverse(
                "core:component_item",
                kwargs={
                    "component_id": found.sbom.component_id,
                    "item_type": "sboms",
                    "item_id": str(found.sbom.id),
                },
            )
            return HttpResponseRedirect(f"{page_url}#plugin-{found.run.plugin_name}")

        base_url = reverse("plugins:assessment_run_findings", args=[str(found.run.id)])
        query = found.panel["query"]
        # The pager sits outside the filter form, so its links carry the active
        # filters themselves; following one must not silently clear the search.
        return render(
            request,
            "plugins/components/_assessment_run_findings.html.j2",
            {
                "run": found.run,
                "is_security": found.is_security,
                "findings": found.findings,
                "can_triage": can(request, "artifact:publish_vex", found.sbom.component),
                "findings_url": base_url,
                "findings_query": query_string(query, page=1, prefix=PARAM_PREFIX, default_per_page=PAGE_SIZE),
                "panel": found.panel,
            },
        )


class AssessmentResultsCardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The artifact page's assessments card, re-rendered on its own.

    The card used to answer a completed assessment by reloading the whole page.
    An assessment finishes when the queue says so, not when the reader is ready,
    so that reload landed on a triage modal with a justification half typed, on
    a filtered suppression list, on an expanded findings panel: all of it client
    state that a reload cannot restore. This endpoint is what the card swaps in
    instead.

    Authorization is the one ``get_sbom_assessments`` already applies, which
    answers the empty shape rather than an error for an SBOM the caller may not
    read. Guests are blocked on top of that, matching the page this belongs to,
    so a guest redirected off the artifact page cannot pull its fragments by URL.

    One URL, two audiences, the same split the findings view makes: an HTMX
    request gets the region, anything else lands on the artifact page.
    """

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        from sbomify.apps.sboms.models import SBOM

        from .apis import get_sbom_assessments

        sbom = SBOM.objects.filter(pk=sbom_id).select_related("component").first()
        if sbom is None:
            return HttpResponseNotFound("Artifact not found")

        if not request.headers.get("HX-Request"):
            return HttpResponseRedirect(
                reverse(
                    "core:component_item",
                    kwargs={
                        "component_id": sbom.component_id,
                        "item_type": "sboms",
                        "item_id": str(sbom.id),
                    },
                )
            )

        try:
            # Same two knobs the artifact page passes: the card reads counts from
            # each run's summary and one title, and building every finding twice
            # is what once made this payload 31 MB.
            assessment_runs = get_sbom_assessments(
                request, sbom_id, findings_limit=1, include_history=False
            ).model_dump(mode="json")
        except Exception:
            logger.exception("Failed to refresh assessments for SBOM %s", sbom_id)
            return HttpResponseNotFound("Assessments unavailable")

        return render(
            request,
            "plugins/components/assessment_results_card.html.j2",
            {"sbom_id": sbom_id, "assessment_runs": assessment_runs},
        )
