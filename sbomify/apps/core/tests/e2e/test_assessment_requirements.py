"""The artifact page aggregates every standard's checks into one row per SBOM requirement."""

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.sboms.models import SBOM


def _check(element: str, title: str, status: str, **extra: str) -> dict:
    return {
        "id": f"{element}-{status}",
        "title": title,
        "status": status,
        "description": extra.get("description", ""),
        "remediation": extra.get("remediation"),
        "metadata": {"element": element},
    }


# Both standards test the SBOM author under their own element names, so the
# page must show one row that both columns mark as not met.
STANDARDS = [
    (
        "ntia-minimum-elements-2021",
        "NTIA Minimum Elements (2021)",
        [
            _check("component_name", "Component Name", "pass"),
            _check(
                "sbom_author",
                "SBOM Author",
                "fail",
                description="No author is recorded.",
                remediation="Add an author to the next SBOM.",
            ),
            _check("timestamp", "Timestamp", "pass"),
        ],
    ),
    (
        "bsi-tr03183-v2.1-compliance",
        "BSI TR-03183-2 v2.1",
        [
            _check("sbom_creator", "SBOM Creator", "fail", remediation="Add an author to the next SBOM."),
            _check("component_name", "Component Name", "pass"),
            _check("archive_property", "Archive Property", "warning", description="Archives are not marked."),
        ],
    ),
]


def _seed(sbom: SBOM) -> None:
    AssessmentRun.objects.filter(sbom=sbom).delete()
    for name, display_name, findings in STANDARDS:
        RegisteredPlugin.objects.update_or_create(
            name=name, defaults={"display_name": display_name, "category": "compliance", "version": "1.0"}
        )
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name=name,
            plugin_version="1.0",
            plugin_config_hash="e2e",
            category="compliance",
            status="completed",
            run_reason="on_upload",
            result={
                "plugin_name": name,
                "plugin_version": "1.0",
                "category": "compliance",
                "assessed_at": "2026-09-01T00:00:00Z",
                "findings": findings,
                "summary": {
                    "pass_count": sum(f["status"] == "pass" for f in findings),
                    "fail_count": sum(f["status"] == "fail" for f in findings),
                    "warning_count": sum(f["status"] == "warning" for f in findings),
                    "total_findings": len(findings),
                },
            },
        )


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_requirements_matrix(authenticated_page, sbom_component_details, mocker, snapshot, width, theme):
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 1000})
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}')")
    mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)
    sbom = SBOM.objects.get(component=sbom_component_details)
    _seed(sbom)
    page.goto(reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id]))
    page.wait_for_load_state("networkidle")

    section = page.locator("#assessment-results")
    expect(section).to_contain_text("1 requirement to fix")
    expect(section).to_contain_text("Meets 0 of 2 standards")

    # One row for the author, marked in both columns, leading the table.
    author = section.get_by_role("button", name="SBOM author")
    expect(author).to_have_count(1)
    expect(author).to_contain_text("Not met in 2 standards")
    first_row = section.locator("tbody tr").first
    expect(first_row).to_contain_text("SBOM author")
    expect(first_row.get_by_text("Not met", exact=True)).to_have_count(2)
    # Met requirements fold away until asked for.
    expect(section.get_by_text("Component name", exact=True)).to_be_hidden()

    author.click()
    expect(author).to_have_attribute("aria-expanded", "true")
    # The shared fix is stated once, with each standard's own finding under it.
    expect(section.get_by_text("Add an author to the next SBOM.")).to_have_count(1)
    expect(section.get_by_text("No author is recorded.", exact=True)).to_be_visible()

    baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
    current = snapshot.take_screenshot(page, width=width)
    snapshot.assert_screenshot(baseline, current)

    section.get_by_role("button", name="Show 2 met requirements").click()
    expect(section.get_by_text("Component name", exact=True)).to_be_visible()


@pytest.mark.django_db
def test_a_plugin_anchor_opens_the_standards_list(authenticated_page, sbom_component_details, mocker):
    page = authenticated_page
    mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)
    sbom = SBOM.objects.get(component=sbom_component_details)
    _seed(sbom)
    path = reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id])
    page.goto(f"{path}#plugin-ntia-minimum-elements-2021")
    expect(page.locator("#plugin-ntia-minimum-elements-2021")).to_be_visible()
    expect(page.locator("#plugin-ntia-minimum-elements-2021")).to_contain_text("2 of 3 checks passed")
