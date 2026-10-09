"""Whether a workspace's billing plan includes a plugin.

Shared by the plugin API and the artifact page's coverage check, so the card
never offers a run the endpoint would refuse.
"""

from collections.abc import Iterable

from sbomify.apps.teams.models import Team


def plugin_plan_requirement(plugin_name: str) -> str | None:
    """Get the required plan feature for a plugin.

    Returns the plan feature name or None if available to all plans.
    """
    # Map plugin names to their required plan features
    plan_requirements = {
        "ntia-minimum-elements-2021": "has_ntia_compliance",
        "fda-medical-device-2025": "has_fda_compliance",
        "dependency-track": "has_dependency_track_access",
        # Future plugins can be added here
    }
    return plan_requirements.get(plugin_name)


def team_has_plugin_access(team: Team, plugin_name: str) -> bool:
    """Check if a team's billing plan allows access to a plugin."""
    from sbomify.apps.billing.config import is_billing_enabled
    from sbomify.apps.billing.models import BillingPlan

    # If billing is disabled, grant access to all plugins
    if not is_billing_enabled():
        return True

    required_feature = plugin_plan_requirement(plugin_name)
    if required_feature is None:
        return True  # No plan requirement

    if not team.billing_plan:
        return False  # No billing plan means community (free) tier

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)
        return getattr(plan, required_feature, False)
    except BillingPlan.DoesNotExist:
        return False


def plugins_within_plan(team: Team, plugin_names: Iterable[str]) -> list[str]:
    """The subset of ``plugin_names`` the workspace's plan includes, in order.

    ``TeamPluginSettings.enabled_plugins`` records what a workspace asked for,
    which is not the same as what it may run: an entry the plan excludes stays
    on the list so the setting takes effect again on upgrade instead of being
    deleted by the next save. Anything that needs "what actually runs" has to
    filter through here rather than read the list directly.
    """
    return [name for name in plugin_names if team_has_plugin_access(team, name)]


def plugins_outside_plan(team: Team, plugin_names: Iterable[str]) -> list[str]:
    """The subset of ``plugin_names`` the workspace's plan excludes, in order."""
    return [name for name in plugin_names if not team_has_plugin_access(team, name)]
