"""Record one FAQ-length screencast per plugin.

Produces ``plugin_enablement_<slug>.webm`` for each plugin. Each clip
navigates to the Plugins page, flips the plugin's toggle on, and saves.
Billing is disabled in the screencast fixture so every plugin (including
ones that are plan-gated in production) is clickable here.
"""

import pytest
from playwright.sync_api import Page

from conftest import enable_and_save_plugin, start_on_dashboard

PLUGIN_SLUGS = [
    "osv",
    "dependency-track",
    "ntia-minimum-elements-2021",
    "bsi-tr03183-v2.1-compliance",
    "fda-medical-device-2025",
    # ``sbom-verification`` is the unified attestation plugin — it covers
    # both sbomify-stored signatures and GitHub-published Sigstore
    # attestations in a single run (formerly two separate plugins).
    "sbom-verification",
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin_slug", PLUGIN_SLUGS, ids=PLUGIN_SLUGS)
def plugin_enablement(recording_page: Page, plugin_slug: str) -> None:
    page = recording_page
    start_on_dashboard(page)
    enable_and_save_plugin(page, plugin_slug)
