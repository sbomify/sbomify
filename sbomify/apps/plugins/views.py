"""Views for the plugins framework."""

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.logging import getLogger

from .apis import UpdateTeamPluginSettingsRequest, get_team_plugin_settings, update_team_plugin_settings

logger = getLogger(__name__)


class TeamPluginSettingsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing team plugin settings."""

    allowed_roles = ["owner", "admin"]

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
        shown_divider = False
        for plugin in plugin_settings.get("available_plugins", []):
            plugin["show_upgrade_divider"] = not shown_divider and plugin.get("requires_upgrade", False)
            if plugin["show_upgrade_divider"]:
                shown_divider = True
            plugin["is_enabled"] = plugin["name"] in enabled_plugins and plugin.get("has_access", False)
            for field in plugin.get("config_schema") or []:
                field["current_value"] = plugin_configs.get(plugin["name"], {}).get(field.get("key", ""), "")

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

    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the standalone plugins page."""
        return render(request, "plugins/plugins_page.html.j2")


class PluginsSummaryView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """HTMX partial: returns the plugin summary bar with counts."""

    allowed_roles = ["owner", "admin"]

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
