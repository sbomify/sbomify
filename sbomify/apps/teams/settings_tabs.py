"""The workspace settings sections, in one place.

The settings page used to declare each section three times over — once in the
nav, once as a hidden pane, and once in an ``{% if role %}`` around each — so a
new section meant editing the template in three places and a permission change
meant hunting for all of them. This is the list; the view filters it and the
template renders whatever it is handed.

Each tab is a real page at its own URL rather than a hidden div, so a section can
be linked to, bookmarked and reached with the back button, and only the section
being looked at is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass

from sbomify.apps.core.authz import ADMINISTER, MANAGE, READ_INTERNAL

# Roles that may see a tab, taken from the capability tiers rather than spelled
# out here: a tab and the actions behind it should never disagree about who may
# use them, and deriving both from ``authz`` makes that true by construction.
#
# Every workspace-configuration tab is ``ADMINISTER``. Admins are near-owners —
# the only capability they lack is deleting the workspace — so there is no tab an
# owner can open and an admin cannot. (Workspace deletion lives inside the
# General tab and is gated separately, on ``is_owner``.)
# There is deliberately no "any role" alias here. One existed, written as
# ADMINISTER + guest back when those two covered every role; it silently stopped
# meaning "anyone" the moment `member` arrived, and cost members the Account tab.
# Tabs name the tier they mean, so widening a tier widens the tab with it and an
# alias cannot fall out of step with the roles again.


@dataclass(frozen=True)
class SettingsTab:
    """One settings section: its URL slug, how it presents, and who may see it."""

    key: str
    label: str
    icon: str
    # The template under ``teams/team_settings_tabs/`` that renders the body.
    template: str
    roles: tuple[str, ...] = ADMINISTER
    # Billing sections are pointless when the deployment has billing switched off.
    requires_billing: bool = False
    description: str = ""

    @property
    def template_path(self) -> str:
        return f"teams/team_settings_tabs/{self.template}.html.j2"


# Order is the order the tabs appear in. General first because it is where a
# workspace is named; Account last because it is about the person, not the
# workspace.
SETTINGS_TABS: tuple[SettingsTab, ...] = (
    SettingsTab(
        key="general",
        label="General",
        icon="fa-sliders",
        template="general",
        description="Workspace name, visibility and identifiers.",
    ),
    SettingsTab(
        key="members",
        label="Members",
        icon="fa-users",
        template="members",
        description="Who can reach this workspace, and what they may do.",
    ),
    SettingsTab(
        key="tokens",
        label="API tokens",
        icon="fa-key",
        template="tokens",
        # MANAGE, not ADMINISTER: tokens are personal and this page only ever
        # lists, creates and revokes the caller's own. A member needs one to
        # upload from CI, and a token can never exceed its holder's role.
        roles=MANAGE,
        description="Personal access tokens for the API and CI.",
    ),
    SettingsTab(
        key="contact-profiles",
        label="Contacts",
        icon="fa-address-book",
        template="contact_profiles",
        description="The people and organisations named on your artifacts.",
    ),
    SettingsTab(
        key="trust-center",
        label="Trust Center",
        icon="fa-globe",
        template="trust_center",
        description="What the public sees, and who may be let past the gate.",
    ),
    SettingsTab(
        key="branding",
        label="Branding",
        icon="fa-palette",
        template="branding",
        description="How this workspace looks to everyone outside it.",
    ),
    # Plugins is deliberately absent: it has its own page in the sidebar, which
    # shows the summary bar as well as the same settings partial this tab
    # embedded. Two entry points to one screen is a choice the reader has to make
    # for no reason.
    SettingsTab(
        key="billing",
        label="Billing",
        icon="fa-credit-card",
        template="billing",
        requires_billing=True,
        description="Your plan, usage and payment details.",
    ),
    SettingsTab(
        key="account",
        label="Account",
        icon="fa-user-gear",
        template="account",
        # Your own account is yours whatever your *internal* role. Guests are
        # external and never reach this view — allowed_roles stops them well
        # before the tab list — so listing them here only invited someone to
        # widen the view later and hand guests a settings page by accident.
        roles=READ_INTERNAL,
        description="Your own sign-in and personal settings.",
    ),
)

TABS_BY_KEY: dict[str, SettingsTab] = {tab.key: tab for tab in SETTINGS_TABS}


def visible_tabs(role: str | None, *, billing_enabled: bool) -> list[SettingsTab]:
    """The sections this member may open, in display order.

    Filtering here rather than in the template means the nav and the page agree
    by construction: a tab that is not returned cannot be linked *or* rendered.
    """
    return [tab for tab in SETTINGS_TABS if role in tab.roles and (billing_enabled or not tab.requires_billing)]


def resolve_tab(key: str | None, role: str | None, *, billing_enabled: bool) -> SettingsTab | None:
    """The tab to render, or None when the member may open no section at all.

    An unknown or forbidden key falls back to the first section they can see
    rather than erroring: settings links are pasted around and outlive renames,
    and landing on the first page beats a 404.
    """
    allowed = visible_tabs(role, billing_enabled=billing_enabled)
    if not allowed:
        return None
    by_key = {tab.key: tab for tab in allowed}
    return by_key.get(key or "", allowed[0])
