"""Record one FAQ-length screencast per plugin.

Produces ``plugin_enablement_<slug>.webm`` for each plugin (the website links
to these names). Each clip opens Plugins from the sidebar, explains what the
plugin checks, ticks it, saves, and shows the enabled count go up. Billing is
disabled in the screencast fixture so every plugin (including ones that are
plan-gated in production) is clickable here.

The per-plugin narration lives in :data:`PLUGINS` as string literals. The
recording fixture only pre-synthesises lines passed straight to ``caption()``,
so :func:`prefetched_plugin_lines` synthesises this clip's lines before the
camera rolls, which keeps the dict-driven lines free of dead air.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    _synthesize,
    _tts_enabled,
    caption,
    clear_caption,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_plugins,
    pace,
    smooth_scroll,
    start_on_dashboard,
)

PLUGINS: dict[str, dict[str, str]] = {
    "osv": {
        "intro": "Here is how to turn on the OSV Vulnerability Scanner in sbomify.",
        "about": (
            "OSV checks each SBOM against the Open Source Vulnerabilities database. It works with CycloneDX and SPDX."
        ),
        "done": "OSV is on. Every new SBOM upload is now scanned for known vulnerabilities.",
    },
    "dependency-track": {
        "intro": "Here is how to turn on the Dependency Track plugin in sbomify.",
        "about": (
            "Dependency Track sends CycloneDX SBOMs to a Dependency Track server for vulnerability analysis. "
            "It needs a Business or Enterprise plan."
        ),
        "done": "Dependency Track is on. New CycloneDX uploads are now analyzed for vulnerabilities.",
    },
    "ntia-minimum-elements-2021": {
        "intro": "Here is how to turn on the NTIA Minimum Elements check in sbomify.",
        "about": (
            "It checks each SBOM for the NTIA minimum elements, such as supplier, component name, version and author."
        ),
        "done": "The NTIA check is on. Every new SBOM upload now gets a compliance result.",
    },
    "bsi-tr03183-v2.1-compliance": {
        "intro": "Here is how to turn on the BSI TR-03183-2 check in sbomify.",
        "about": (
            "It checks SBOMs against the German BSI guideline behind the EU Cyber Resilience Act SBOM rules. "
            "It needs CycloneDX 1.6 or SPDX 3.0.1, or newer."
        ),
        "done": "The BSI check is on. Every new SBOM upload now gets a Cyber Resilience Act compliance result.",
    },
    "fda-medical-device-2025": {
        "intro": "Here is how to turn on the FDA Medical Device Cybersecurity check in sbomify.",
        "about": (
            "It checks SBOMs against the 2025 FDA guidance for medical device submissions, "
            "including support status and end of support dates."
        ),
        "done": "The FDA check is on. Every new SBOM upload now gets a compliance result.",
    },
    # ``sbom-verification`` is the unified attestation plugin. It covers both
    # sbomify-stored signatures and GitHub-published Sigstore attestations in
    # a single run (formerly two separate plugins).
    "sbom-verification": {
        "intro": "Here is how to turn on SBOM Verification in sbomify.",
        "about": (
            "It confirms an SBOM has not been tampered with. "
            "It checks the file digest, Sigstore signatures, and attestations published on GitHub."
        ),
        "done": "SBOM Verification is on. New uploads are now checked for valid signatures and attestations.",
    },
}

PLUGIN_SLUGS = list(PLUGINS)


@pytest.fixture
def prefetched_plugin_lines(plugin_slug: str) -> None:
    """Synthesise this clip's dict-driven lines before the video starts."""
    if _tts_enabled():
        for line in PLUGINS[plugin_slug].values():
            _synthesize(line)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin_slug", PLUGIN_SLUGS, ids=PLUGIN_SLUGS)
def plugin_enablement(
    prefetched_plugin_lines: None, recording_page: Page, plugin_slug: str, pied_piper_with_sboms: dict
) -> None:
    page = recording_page
    lines = PLUGINS[plugin_slug]

    mock_vuln_trends(page)
    start_on_dashboard(page, pause_ms=600)
    caption(page, lines["intro"])
    clear_caption(page)

    navigate_to_plugins(page)
    page.locator("#plugin-settings-form").wait_for(state="visible", timeout=15_000)
    pace(page, 400)
    caption(page, "Open Plugins from the sidebar. Plugins are grouped into compliance, security and attestation.")

    # Attribute selector (not #id) because some plugin slugs contain dots
    # (e.g. bsi-tr03183-v2.1-compliance) which have CSS-special meaning.
    toggle = page.locator(f"[id='plugin-{plugin_slug}']")
    smooth_scroll(page, toggle, 600)
    caption(page, lines["about"])

    caption(page, "Tick the plugin, then save your changes.", block=False)
    hover_and_click(page, toggle)
    pace(page, 600)

    save_btn = page.locator("#plugin-settings-form button[type='submit']").last
    smooth_scroll(page, save_btn, 500)
    hover_and_click(page, save_btn)
    page.wait_for_load_state("networkidle")

    # The summary cards refresh after the save; scroll back up to show the
    # enabled count.
    enabled_card = page.locator("#plugins-summary")
    enabled_card.get_by_text("Enabled plugins").wait_for(state="visible", timeout=10_000)
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 900)
    caption(page, lines["done"])
    caption(page, "Changes apply to new uploads. Results you already have are kept.")
    pace(page, 600)
