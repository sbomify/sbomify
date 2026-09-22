"""Regressions for disconnected actions found during the page audit."""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus
from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact, User
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink
from sbomify.apps.teams.models import Member, Team

pytest_plugins = [
    "sbomify.apps.core.tests.e2e.fixtures",
    "sbomify.apps.core.tests.e2e.test_cra_compliance",
]
pytestmark = pytest.mark.django_db


@pytest.fixture
def billing_session(browser_context: Any) -> None:
    """Exercise paid identifier controls with the browser's real workspace plan."""
    for row in Session.objects.all():
        session = SessionStore(session_key=row.session_key)
        current = session.get("current_team") or {}
        current["billing_plan"] = "business"
        session["current_team"] = current
        session.save()


@pytest.mark.parametrize("kind", ["identifier", "link"])
def test_product_form_errors_preserve_editor(
    authenticated_page: Page, product_factory: Callable[..., Product], billing_session: None, kind: str
) -> None:
    page = authenticated_page
    product = product_factory("Form validation product")
    identifiers = kind == "identifier"
    heading = "Product identifiers" if identifiers else "Product links"
    add_label = "Add Identifier" if identifiers else "Add link"
    action_label = "Identifier actions" if identifiers else "Link actions"
    value_field = "value" if identifiers else "title"
    valid = "pkg:npm/audit-example" if identifiers else "Audit documentation"
    invalid = "not-a-purl" if identifiers else " "
    card = page.locator(f"#product-{kind}s-card")
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(reverse("core:product_details", args=[product.pk]))
    page.locator("summary").filter(has_text=heading).click()
    page.get_by_role("button", name=add_label, exact=True).click()
    dialog = page.get_by_role("dialog")
    page.locator(f"#add-{kind}-type").select_option("purl" if identifiers else "website")
    page.locator(f"#add-{kind}-{value_field}").fill(invalid)
    if not identifiers:
        page.locator("#add-link-url").fill("https://example.com/docs")
    dialog.get_by_role("button", name="Add", exact=True).click()
    expect(
        page.get_by_text("Invalid PURL format" if identifiers else "Link type, title, and URL are required", exact=True)
    ).to_be_visible()
    expect(card).to_be_visible()
    expect(dialog).to_be_visible()
    expect(page.locator(f"#add-{kind}-{value_field}")).to_have_value(invalid)
    page.locator(f"#add-{kind}-{value_field}").fill(valid)
    dialog.get_by_role("button", name="Add", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(card).to_contain_text(valid)

    card.get_by_role("button", name=action_label, exact=True).click()
    page.get_by_role("menuitem", name="Edit", exact=True).click()
    page.locator(f"#edit-{kind}-{value_field}").fill(invalid)
    dialog.get_by_role("button", name="Update", exact=True).click()
    expect(
        page.get_by_text(
            "Invalid PURL format" if identifiers else "All required fields must be provided", exact=True
        ).last
    ).to_be_visible()
    expect(dialog).to_be_visible()
    page.locator(f"#edit-{kind}-{value_field}").fill(valid + "-updated")
    dialog.get_by_role("button", name="Update", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(card).to_contain_text(valid + "-updated")

    card.get_by_role("button", name=action_label, exact=True).click()
    page.get_by_role("menuitem", name="Delete", exact=True).click()
    deletion = page.get_by_role("alertdialog")
    deletion.get_by_role("button", name="Delete", exact=True).click()
    expect(deletion).to_be_hidden()
    expect(card.get_by_role("button", name=add_label, exact=True)).to_be_visible()

    # A concurrent deletion must not erase the user's card or confirmation.
    model = ProductIdentifier if identifiers else ProductLink
    if identifiers:
        model.objects.create(product=product, identifier_type="purl", value=valid)
    else:
        model.objects.create(product=product, link_type="website", title=valid, url="https://example.com")
    page.reload()
    page.locator("summary").filter(has_text=heading).click()
    card.get_by_role("button", name=action_label, exact=True).click()
    page.get_by_role("menuitem", name="Delete", exact=True).click()
    model.objects.filter(product=product).delete()
    deletion.get_by_role("button", name="Delete", exact=True).click()
    expect(page.get_by_text(re.compile("not found", re.I)).last).to_be_visible()
    expect(card).to_be_visible()
    expect(deletion).to_be_visible()
    assert not errors


@pytest.mark.parametrize("role", ["member", "admin", "owner"])
@pytest.mark.parametrize("component_type", ["bom", "document"])
@pytest.mark.parametrize("visibility", ["public", "gated"])
def test_component_sharing_does_not_require_visibility_permission(
    authenticated_page: Page,
    component_factory: Callable[..., Component],
    team_with_business_plan: Team,
    sample_user: User,
    role: str,
    component_type: str,
    visibility: str,
) -> None:
    component = component_factory("Shared component", component_type, visibility=visibility)
    Member.objects.filter(team=team_with_business_plan, user=sample_user).update(role=role)
    page = authenticated_page
    page.add_init_script("""window.auditCopies = []; Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: {writeText: async text => window.auditCopies.push(text)}
    });""")
    page.goto(reverse("core:component_details", args=[component.pk]))
    for index, label in enumerate(["Copy public URL", "Copy badge"], start=1):
        page.get_by_role("button", name="Component actions", exact=True).click()
        page.get_by_role("menuitem", name=label, exact=True).click()
        page.wait_for_function(f"window.auditCopies.length === {index}")
    copies = page.evaluate("window.auditCopies")
    public_path = reverse("core:component_details_public", args=[component.pk])
    assert copies[0].endswith(public_path)
    assert copies[1] == f"[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)]({copies[0]})"
    assert page.get_by_role("button", name="Component visibility", exact=True).count() == (0 if role == "member" else 1)
    component.visibility = "private"
    component.save(update_fields=["visibility"])
    page.reload()
    page.get_by_role("button", name="Component actions", exact=True).click()
    expect(page.get_by_role("menuitem", name="Copy public URL", exact=True)).to_be_hidden()
    expect(page.get_by_role("menuitem", name="Copy badge", exact=True)).to_be_hidden()


@pytest.mark.parametrize("component_type", ["bom", "document"])
def test_upload_menu_and_deep_links(
    authenticated_page: Page, component_factory: Callable[..., Component], component_type: str, snapshot: Any
) -> None:
    component = component_factory("Upload destination", component_type)
    page = authenticated_page
    page.add_init_script("localStorage.setItem('document-upload-expanded', 'false')")
    path = reverse("core:component_details", args=[component.pk])
    page.goto(path)
    page.get_by_role("button", name="Component actions", exact=True).click()
    page.get_by_role("menuitem", name="Upload artifact…", exact=True).click()
    dialog = page.get_by_role(
        "dialog", name="Upload Artifact" if component_type == "bom" else "Upload document", exact=True
    )
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(dialog).to_be_hidden()
    page.goto(path + "#upload-artifact")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Close", exact=True).click()
    page.goto(path + "#upload-sbom")
    expect(dialog).to_be_visible()
    page.goto(path + "#upload-artifact")
    page.reload()
    expect(dialog).to_be_visible()
    if component_type == "document":
        expect(dialog.get_by_label("Version", exact=False)).to_have_value("1.0")
        dialog.get_by_label("Document type", exact=True).select_option("compliance")
        expect(dialog.get_by_label("Compliance Subcategory", exact=True)).to_be_visible()
        baseline = snapshot.get_or_create_baseline_screenshot(page, width=992)
        current = snapshot.take_screenshot(page, width=992)
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


def test_cra_parties_link_opens_complete_settings(authenticated_page: Page, cra_assessment: Any) -> None:
    page = authenticated_page
    page.goto(reverse("compliance:cra_step", args=[cra_assessment.pk, 1]))
    page.get_by_role("link", name="Edit in team settings", exact=True).click()
    expect(page.locator("#settings-content")).to_be_visible()
    expect(
        page.get_by_role("navigation", name="Settings sections").get_by_role("link", name="Parties", exact=True)
    ).to_have_attribute("aria-current", "page")
    page.get_by_role("button", name="Add profile", exact=True).click()
    page.get_by_role("button", name="Back to profiles", exact=True).click()
    expect(page.locator("#contact-profiles-content")).to_be_visible()
    page.go_back()
    expect(page).to_have_url(re.compile(re.escape(reverse("compliance:cra_step", args=[cra_assessment.pk, 1])) + "$"))


def test_controls_navigation_and_product_overrides(
    authenticated_page: Page, team_with_business_plan: Team, product_factory: Callable[..., Product]
) -> None:
    page = authenticated_page
    workspace = team_with_business_plan
    page.goto(reverse("teams:team_settings", args=[workspace.key]) + "#controls")
    expect(page).to_have_url(re.compile(r"/settings/controls$"))
    page.get_by_role("button", name="Activate SOC 2 Type II", exact=True).click()
    expect(page.get_by_role("button", name="Deactivate SOC 2 Type II", exact=True)).to_be_visible()
    # A second catalog ensures responses do not accidentally replace the first catalog.
    catalog = ControlCatalog.objects.create(team=workspace, name="Audit framework", source="custom", version="1")
    control = Control.objects.create(catalog=catalog, control_id="AUD-1", title="Review access", group="Access")
    page.reload()
    table = page.locator(f"#controls-table-{catalog.pk}")
    table.get_by_role("button", name="Access (1)", exact=True).click()
    with page.expect_response(lambda response: response.request.method == "POST" and "/status" in response.url):
        table.get_by_label("Status for AUD-1", exact=True).select_option("compliant")
    expect(table).to_contain_text("Audit framework")
    assert ControlStatus.objects.get(control=control, product=None).status == "compliant"
    expect(table.get_by_label("Status for AUD-1", exact=True)).to_have_value("compliant")

    product = product_factory("Overrides product")
    page.goto(reverse("core:product_details", args=[product.pk]))
    page.locator("summary").filter(has_text="Compliance controls").click()
    table.get_by_role("button", name="Access (1)", exact=True).click()
    expect(table).to_contain_text("Workspace default")
    expect(table.get_by_label("Status for AUD-1", exact=True)).to_have_value("compliant")
    with page.expect_response(lambda response: response.request.method == "POST" and "/status" in response.url):
        table.get_by_label("Status for AUD-1", exact=True).select_option("partial")
    expect(table).to_contain_text("Product override")
    expect(table.get_by_label("Status for AUD-1", exact=True)).to_have_value("partial")
    assert ControlStatus.objects.get(control=control, product=None).status == "compliant"
    assert ControlStatus.objects.get(control=control, product=product).status == "partial"
    page.get_by_role("link", name="Manage workspace controls", exact=True).click()
    expect(page).to_have_url(re.compile(r"/settings/controls$"))
    page.get_by_role("button", name="Deactivate SOC 2 Type II", exact=True).click()
    expect(page.get_by_role("button", name="Activate SOC 2 Type II", exact=True)).to_be_visible()


@pytest.mark.parametrize("bom_type", ["sbom", "cbom", "vex", "document"])
def test_release_artifact_links(
    authenticated_page: Page,
    product_factory: Callable[..., Product],
    component_factory: Callable[..., Component],
    sbom_factory: Callable[..., Any],
    document_factory: Callable[..., Any],
    bom_type: str,
) -> None:
    page = authenticated_page
    product = product_factory("Linked artifacts")
    component = component_factory("Release component", "document" if bom_type == "document" else "bom", product=product)
    release = Release.objects.create(product=product, name="v1")
    if bom_type == "document":
        artifact = document_factory(component, name="Audit artifact")
        field = "document"
        item_type = "documents"
    else:
        artifact = sbom_factory(component, name="Audit artifact")
        artifact.bom_type = bom_type
        artifact.save(update_fields=["bom_type"])
        field = "sbom"
        item_type = "sboms" if bom_type == "sbom" else bom_type
    expected = reverse("core:component_item", args=[component.pk, item_type, artifact.pk])
    path = reverse("core:release_details", args=[product.pk, release.pk])
    page.goto(path)
    page.get_by_role("button", name="Add Artifact", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("link", name="Audit artifact", exact=True)).to_have_attribute("href", expected)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    ReleaseArtifact.objects.create(release=release, **{field: artifact})
    page.reload()
    link = page.get_by_role("link", name="Audit artifact", exact=True)
    expect(link).to_have_attribute("href", expected)
    link.click()
    expect(page).to_have_url(re.compile(re.escape(expected) + "$"))
    expect(page.get_by_role("heading", name="Page not found (404)")).to_have_count(0)


def test_unchanged_lifecycle_keeps_the_editor(
    authenticated_page: Page, product_factory: Callable[..., Product]
) -> None:
    page = authenticated_page
    product = product_factory("Lifecycle product")
    page.goto(reverse("core:product_details", args=[product.pk]))
    page.locator("summary").filter(has_text="Lifecycle").click()
    page.get_by_role("button", name="Set dates", exact=True).click()
    card = page.locator("#product-lifecycle-card")
    card.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("No changes to save", exact=True)).to_be_visible()
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    card.get_by_role("button", name="Cancel", exact=True).click()
    expect(card.get_by_role("button", name="Set dates", exact=True)).to_be_visible()
    card.get_by_role("button", name="Set dates", exact=True).click()
    card.get_by_role("textbox").first.click()
    page.get_by_role("button", name="Today", exact=True).click()
    card.get_by_role("button", name="Save", exact=True).click()
    expect(card.get_by_role("button", name="Edit", exact=True)).to_be_visible()
    product.refresh_from_db()
    assert product.release_date is not None


def test_catalog_import_and_deletion(authenticated_page: Page, team_with_business_plan: Team) -> None:
    page = authenticated_page
    page.goto(reverse("teams:team_settings_tab", args=[team_with_business_plan.key, "controls"]))
    page.get_by_role("button", name="Import catalog", exact=True).click()
    dialog = page.get_by_role("dialog", name="Import OSCAL catalog", exact=True)
    upload = page.locator("#catalog-import-file")
    upload.set_input_files({"name": "invalid.json", "mimeType": "application/json", "buffer": b"{}"})
    dialog.get_by_role("button", name="Import catalog", exact=True).click()
    expect(dialog).to_contain_text("missing 'catalog' root key")
    payload = {
        "catalog": {
            "metadata": {"title": "Imported audit", "version": "1"},
            "groups": [{"id": "access", "title": "Access", "controls": [{"id": "IMP-1", "title": "Review access"}]}],
        }
    }
    upload.set_input_files(
        {"name": "catalog.json", "mimeType": "application/json", "buffer": json.dumps(payload).encode()}
    )
    dialog.get_by_role("button", name="Import catalog", exact=True).click()
    expect(page.get_by_role("button", name="Deactivate Imported audit", exact=True)).to_be_visible()
    page.get_by_role("button", name="Deactivate Imported audit", exact=True).click()
    page.get_by_role("button", name="Activate Imported audit", exact=True).click()
    expect(page.get_by_role("button", name="Deactivate Imported audit", exact=True)).to_be_visible()
    page.get_by_role("button", name="Delete Imported audit", exact=True).click()
    deletion = page.get_by_role("alertdialog", name="Delete catalog", exact=True)
    deletion.get_by_role("button", name="Cancel", exact=True).click()
    expect(deletion).to_be_hidden()
    assert ControlCatalog.objects.filter(team=team_with_business_plan, name="Imported audit").exists()
    page.get_by_role("button", name="Delete Imported audit", exact=True).click()
    deletion.get_by_role("button", name="Delete catalog", exact=True).click()
    expect(page.get_by_role("button", name="Delete Imported audit", exact=True)).to_have_count(0)
    assert not ControlCatalog.objects.filter(team=team_with_business_plan, name="Imported audit").exists()


@pytest.mark.parametrize("width,theme", [(1440, "light"), (1440, "dark"), (390, "light"), (390, "dark")])
def test_controls_settings_snapshot(
    authenticated_page: Page, team_with_business_plan: Team, snapshot: Any, width: int, theme: str
) -> None:
    catalog = ControlCatalog.objects.create(
        team=team_with_business_plan, name="Access controls", source="custom", version="1"
    )
    Control.objects.create(catalog=catalog, control_id="AC-1", title="Review access permissions", group="Access")
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}')")
    page.set_viewport_size({"width": width, "height": 1080})
    page.goto(reverse("teams:team_settings_tab", args=[team_with_business_plan.key, "controls"]))
    page.get_by_role("button", name="Access (1)", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
    current = snapshot.take_screenshot(page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.parametrize("fails", [False, True])
def test_product_sharing_uses_the_shared_clipboard_flow(
    authenticated_page: Page, product_factory: Callable[..., Product], fails: bool
) -> None:
    product = product_factory("Example shared product", is_public=True)
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""window.auditCopies = []; Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: {writeText: async text => {
            if (window.failCopy) throw new Error('Clipboard unavailable');
            window.auditCopies.push(text);
        }}
    });""")
    page.goto(reverse("core:product_details", args=[product.pk]))
    page.evaluate("value => { window.failCopy = value; }", fails)
    for index, label in enumerate(["Copy public URL", "Copy badge"], start=1):
        page.get_by_role("button", name="Product actions", exact=True).click()
        page.get_by_role("menuitem", name=label, exact=True).click()
        if fails:
            message = "Failed to copy URL to clipboard" if index == 1 else "Failed to copy badge to clipboard"
            expect(page.get_by_text(message, exact=True)).to_be_visible()
        else:
            page.wait_for_function(f"window.auditCopies.length === {index}")
    if not fails:
        copies = page.evaluate("window.auditCopies")
        public_path = reverse("core:product_details_public", args=[product.pk])
        assert copies[0] == page.evaluate("location.origin") + public_path
        assert copies[1] == f"[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)]({copies[0]})"
    assert not errors
