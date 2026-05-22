"""Record the OIDC trusted-publishing setup screencast.

Drives: Dashboard → Components → open a component → scroll to the
Trusted Publishers section → add a GitHub repository binding → expand
the GitHub Actions workflow snippet so a viewer sees the copy-paste
YAML they would land in their CI.

Prerequisite: uses ``pied_piper_with_sboms`` to seed a Component the
screencast can click into. The GitHub REST call that
``services.create_binding`` would normally make is patched so the
recording is deterministic and doesn't depend on network reachability
or unauthenticated rate limits.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_COMPONENTS,
    auto_dismiss_toasts,
    dismiss_toasts,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_components,
    pace,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.oidc.github_api import ResolvedRepository

DEMO_REPOSITORY = "aurangzaib048/lithium"
# Fake-but-stable IDs so the recording shows the same "owner_id=… ·
# repo_id=…" subline every time. Real GitHub values would shift if the
# repo were ever transferred / renamed; deterministic ones keep the
# screencast frame-stable across re-records.
_FAKE_OWNER_ID = 44493075
_FAKE_REPO_ID = 1203430154


@pytest.fixture
def mock_github_resolve(mocker):
    """Stub the GitHub REST lookup so the recording doesn't hit github.com.

    Returns a ``ResolvedRepository`` with deterministic immutable IDs
    matching the real ``aurangzaib048/lithium`` repo at recording time.
    Patching at the ``services`` import site (not ``github_api``)
    matches what the existing OIDC test suite does — the service uses
    the symbol via ``from sbomify.apps.oidc.github_api import
    resolve_repository``, so the bound name lives in ``services``.
    """
    return mocker.patch(
        "sbomify.apps.oidc.services.resolve_repository",
        return_value=ResolvedRepository(
            repository=DEMO_REPOSITORY,
            repository_owner=DEMO_REPOSITORY.split("/")[0],
            repository_id=_FAKE_REPO_ID,
            repository_owner_id=_FAKE_OWNER_ID,
        ),
    )


@pytest.mark.django_db(transaction=True)
def oidc_trusted_publishing(
    recording_page: Page,
    pied_piper_with_sboms: dict,
    mock_github_resolve,
) -> None:
    page = recording_page

    # Toast suppressor — the trust-center / notifications panels lazy-load
    # in this screencast environment and would otherwise emit "failed to
    # load" toasts unrelated to the OIDC flow we're demoing.
    auto_dismiss_toasts(page)
    mock_vuln_trends(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Components ────────────────────────────────────────
    navigate_to_components(page)

    # ── 2. Click into the first Pied Piper component ─────────────────────
    # The components table renders Alpine x-text rows whose row-level
    # ``@click`` redirects to the detail page. Match the visible name
    # span (same pattern release_creation uses for products) and let
    # the click bubble up to the row handler.
    target_component = PIED_PIPER_COMPONENTS[0]
    component_name = page.locator(f"span.text-text:text-is('{target_component}')")
    component_name.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    hover_and_click(page, component_name)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 3. Scroll the Trusted Publishers section into view ───────────────
    # The section loads via ``hx-get … hx-trigger="load"`` so it may
    # briefly show the "Loading trusted publishers…" placeholder before
    # the partial swaps in. Wait for the real heading rather than the
    # placeholder so we don't snap a stale frame.
    section = page.locator("#trusted-publishers-section")
    section.wait_for(state="visible", timeout=15_000)
    section.scroll_into_view_if_needed()
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 4. Fill the repository field ─────────────────────────────────────
    repo_input = page.locator("#id_repository")
    repo_input.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, repo_input)
    pace(page, 300)
    type_text(repo_input, DEMO_REPOSITORY)
    pace(page, 800)

    # ── 5. Click "Add publisher" ─────────────────────────────────────────
    add_btn = page.locator("#trusted-publishers-section button[type='submit']:has-text('Add publisher')")
    hover_and_click(page, add_btn)

    # ── 6. Wait for the binding row to land + linger on the result ───────
    # The new row carries the repo name as plain text — match on the
    # ``<code>`` cell to disambiguate from the form field.
    page.locator(f"#trusted-publishers-section table code:has-text('{DEMO_REPOSITORY}')").wait_for(
        state="visible", timeout=10_000
    )
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 2000)

    # ── 7. Expand the "Configure your GitHub Actions workflow" snippet ──
    # Showing the embedded YAML closes the loop: the viewer sees both
    # the sbomify side (binding row) AND the GitHub-side copy-paste
    # they need to drop into ``.github/workflows/*.yml``.
    disclosure = page.locator("#trusted-publishers-section summary:has-text('Configure your GitHub Actions workflow')")
    disclosure.scroll_into_view_if_needed()
    pace(page, 600)
    hover_and_click(page, disclosure)
    pace(page, 2500)
