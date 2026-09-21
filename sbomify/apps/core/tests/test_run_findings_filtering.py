"""Narrowing the plugin report's findings list.

Reported by a pilot customer. The assessment card is the only place a finding
can be triaged, and it was the one findings view with no way to narrow what it
shows: on a scan with thousands of findings a reader paged twenty-five at a time
with no search and no filters.

It runs on the same engine the component panel does now, so a search that works
in one works in the other. The card's parameters are prefixed ``run_`` rather
than the panel's ``vuln_``, so a URL carrying both stays readable.
"""

from __future__ import annotations

from hashlib import sha256

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _finding(index: int, *, severity: str = "high", package: str | None = None, **extra):
    return {
        "id": f"CVE-2026-{index:05d}",
        "title": f"Flaw in {package or f'pkg-{index:04d}'}",
        "description": "x" * 80,
        "severity": severity,
        "component": {
            "name": package or f"pkg-{index:04d}",
            "version": "1.0",
            "ecosystem": "PyPI",
            "purl": f"pkg:pypi/{package or f'pkg-{index:04d}'}@1.0",
        },
        **extra,
    }


def _run_with(component: Component, findings: list[dict], *, category: str = "security") -> AssessmentRun:
    sbom = SBOM.objects.create(
        component=component,
        name="scan",
        format="cyclonedx",
        format_version="1.6",
        version=f"3.0.{len(findings)}",
        sbom_filename="scan.json",
    )
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash=sha256(b"osv").hexdigest(),
        category=category,
        run_reason=RunReason.ON_UPLOAD.value,
        status="completed",
        result={
            "plugin_name": "osv",
            "plugin_version": "1.0.0",
            "category": category,
            "assessed_at": "2026-09-21T07:00:00Z",
            "summary": {"total_findings": len(findings)},
            "findings": findings,
            "metadata": {"scanner": "osv-scanner"},
        },
    )


@pytest.fixture
def signed_in(sample_team_with_owner_member: Member) -> tuple[Client, Component]:
    component = Component.objects.create(
        team=sample_team_with_owner_member.team,
        name="scan-target",
        component_type=Component.ComponentType.BOM,
    )
    client = Client()
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)
    return client, component


def _open(client: Client, run: AssessmentRun, **params):
    url = reverse("plugins:assessment_run_findings", kwargs={"run_id": str(run.id)})
    return client.get(url, params, headers={"hx-request": "true"})


class TestTheReaderCanNarrowTheList:
    def test_the_toolbar_is_there(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(component, [_finding(n) for n in range(30)])

        body = _open(client, run).content.decode()

        assert "run_search" in body
        assert "run_severity" in body

    def test_search_narrows_the_list(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(
            component,
            [_finding(0, package="openssl"), _finding(1, package="zlib"), _finding(2, package="curl")],
        )

        panel = _open(client, run, run_search="zlib").context["panel"]

        assert [row["id"] for row in panel["rows"]] == ["CVE-2026-00001"]
        assert panel["total"] == 1
        assert panel["unfiltered_total"] == 3

    def test_search_matches_the_advisory_id_too(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(component, [_finding(n) for n in range(30)])

        panel = _open(client, run, run_search="CVE-2026-00017").context["panel"]

        assert [row["id"] for row in panel["rows"]] == ["CVE-2026-00017"]

    def test_severity_narrows_the_list(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(
            component,
            [
                _finding(0, severity="critical"),
                _finding(1, severity="high"),
                _finding(2, severity="critical"),
            ],
        )

        panel = _open(client, run, run_severity="critical").context["panel"]

        assert {row["severity"] for row in panel["rows"]} == {"critical"}
        assert panel["total"] == 2

    def test_kev_only_narrows_the_list(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(component, [_finding(0, kev=True), _finding(1), _finding(2)])

        panel = _open(client, run, run_kev="1").context["panel"]

        assert [row["id"] for row in panel["rows"]] == ["CVE-2026-00000"]

    def test_vex_state_narrows_the_list(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(
            component,
            [_finding(0, analysis_state="not_affected"), _finding(1), _finding(2)],
        )

        panel = _open(client, run, run_submitted="1", run_state="not_affected").context["panel"]

        assert [row["id"] for row in panel["rows"]] == ["CVE-2026-00000"]

    def test_a_search_that_matches_nothing_says_so(self, signed_in) -> None:
        """An empty region reads as a card with no findings, which is a different
        thing from a filter that excluded them all."""
        client, component = signed_in
        run = _run_with(component, [_finding(n) for n in range(5)])

        body = _open(client, run, run_search="nothing-matches-this").content.decode()

        assert "No matches found" in body

    def test_the_rows_keep_everything_the_card_renders(self, signed_in) -> None:
        """The browse engine reads a flatter shape than this card does, so the
        filter keys are added alongside the raw finding rather than replacing
        it. Losing the references or the CVSS score here would be silent."""
        client, component = signed_in
        run = _run_with(component, [_finding(0, cvss_score=9.8, references=["https://example.test/a"])])

        row = _open(client, run).context["panel"]["rows"][0]

        assert row["cvss_score"] == 9.8
        assert row["references"] == ["https://example.test/a"]
        assert row["component"]["purl"] == "pkg:pypi/pkg-0000@1.0"
        assert row["package"] == "pkg-0000"


class TestPagingAndFiltersTravelTogether:
    def test_the_page_size_is_the_card_s_own(self, signed_in) -> None:
        """Twenty-five, not the component panel's five: this card owns its
        accordion, so it is not competing with anything else on the page."""
        client, component = signed_in
        run = _run_with(component, [_finding(n) for n in range(60)])

        panel = _open(client, run).context["panel"]

        assert panel["per_page"] == 25
        assert len(panel["rows"]) == 25

    def test_the_pager_keeps_the_filter(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(component, [_finding(n, severity="critical") for n in range(60)])

        response = _open(client, run, run_severity="critical")

        assert "run_severity=critical" in response.context["next_url"]

    def test_filtering_changes_how_many_pages_there_are(self, signed_in) -> None:
        client, component = signed_in
        findings = [_finding(n, severity="critical" if n < 10 else "low") for n in range(60)]
        run = _run_with(component, findings)

        unfiltered = _open(client, run).context["panel"]
        filtered = _open(client, run, run_severity="critical").context["panel"]

        assert unfiltered["page_count"] == 3
        assert filtered["page_count"] == 1
        assert filtered["total"] == 10

    def test_a_compliance_run_is_offered_only_search(self, signed_in) -> None:
        """Severity, VEX state and KEV belong to vulnerabilities. A check carries
        none of them, so offering those controls gives a blank severity option, a
        state dropdown reading "No decision" for every row, and a filter for a
        concept that does not apply."""
        client, component = signed_in
        findings = [
            {"id": f"check-{n:03d}", "title": f"Field {n}", "description": "d", "status": "fail"} for n in range(5)
        ]
        run = _run_with(component, findings, category="compliance")

        body = _open(client, run).content.decode()

        assert "run_search" in body
        assert "run_severity" not in body
        assert "run_state" not in body
        assert "run_kev" not in body

    def test_a_security_run_is_offered_the_filters(self, signed_in) -> None:
        client, component = signed_in
        run = _run_with(component, [_finding(0), _finding(1)])

        body = _open(client, run).content.decode()

        assert "run_severity" in body
        assert "run_state" in body

    def test_a_compliance_run_filters_too(self, signed_in) -> None:
        """The card's other branch renders checks rather than vulnerabilities,
        and a standard that reports per component grows just as long."""
        client, component = signed_in
        findings = [
            {"id": f"check-{n:03d}", "title": f"Field {n} present", "description": "d", "status": "fail"}
            for n in range(40)
        ]
        run = _run_with(component, findings, category="compliance")

        panel = _open(client, run, run_search="check-007").context["panel"]

        assert [row["id"] for row in panel["rows"]] == ["check-007"]
