"""The component page's vulnerabilities panel, paged on the server.

The page used to render every finding of the newest SBOM and let the browser
show five at a time. On a Yocto-class BSP that was 2,390 rows, 8.5 MB of HTML
and 5.1 s of template render against a 30 s gateway timeout, which is how a
trial workspace turned one component page into site-wide 504s.

So the thing worth pinning is a size, not a feature: the response must carry the
page, not the set. The rest of these tests cover what paging had to take with
it, because filtering a list the browser can no longer see all of has to happen
before the slice.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import Component

pytestmark = pytest.mark.django_db


def _component_with_findings(team, count: int = 40, name: str = "embedded-image", **row_overrides):
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

    component = Component.objects.create(
        name=name,
        team=team,
        component_type=Component.ComponentType.BOM,
        visibility=Component.Visibility.PRIVATE,
    )
    sbom = SBOM.objects.create(
        name="image",
        version="1.7.3",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="image.json",
        bom_type=SBOM.BomType.SBOM,
    )
    findings = [
        {
            "id": f"CVE-2026-{n:04d}",
            # All one severity so the display sort keeps the generated order and
            # "page two continues where page one stopped" is a real assertion.
            "severity": "high",
            "component": {"name": f"pkg-{n:04d}", "version": "1.0", "ecosystem": "deb"},
            **row_overrides,
        }
        for n in range(count)
    ]
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category="security",
        status="completed",
        result={"findings": findings},
    )
    return component, sbom


def _client(team, user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


class TestThePageShipsOnePage:
    def test_the_component_page_renders_five_rows_not_every_finding(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))
        body = response.content.decode()

        assert response.status_code == 200
        assert body.count("CVE-2026-") >= 5
        assert "CVE-2026-0004" in body
        assert "CVE-2026-0005" not in body
        assert "CVE-2026-0039" not in body

    def test_the_header_badge_still_counts_every_finding(self, sample_team_with_owner_member, sample_user):
        """The summary is the whole scan; only the table is a page of it."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.context["vuln_summary"]["total"] == 40
        assert response.context["vuln_summary"]["high"] == 40
        assert response.context["vuln_panel"]["unfiltered_total"] == 40
        assert len(response.context["vuln_panel"]["rows"]) == 5

    def test_the_footer_counts_the_whole_list(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert "Showing 1 to 5 of 40" in response.content.decode()


class TestTheSummaryFallback:
    def test_a_summary_only_result_still_feeds_the_badge(self, sample_team_with_owner_member, sample_user):
        """Some providers store counts and no findings list; the badge reads those.

        Taken as the highest total across each provider's newest run, which is
        what the artifacts table and the product page already do. The page used
        to read whichever run completed last regardless of provider, and that
        contradicted the rule the rest of this view follows.
        """
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM

        member = sample_team_with_owner_member
        component = Component.objects.create(
            name="summary-only",
            team=member.team,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        sbom = SBOM.objects.create(
            name="image",
            version="1.0",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="image.json",
            bom_type=SBOM.BomType.SBOM,
        )
        for plugin, high in (("osv", 1), ("dependency-track", 4)):
            AssessmentRun.objects.create(
                sbom=sbom,
                plugin_name=plugin,
                category="security",
                status="completed",
                result={"summary": {"total_findings": high, "by_severity": {"high": high}}, "findings": []},
            )
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.context["vuln_summary"]["total"] == 4
        # Nothing to page through, so the panel renders no table at all.
        assert response.context["vuln_panel"]["unfiltered_total"] == 0
        assert "component-vulnerabilities-table" not in response.content.decode()


class TestThePanelEndpoint:
    def test_an_htmx_request_gets_the_region_rather_than_the_page(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        response = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        )
        body = response.content.decode()

        assert response.status_code == 200
        assert 'id="component-vulnerabilities-table"' in body
        # The region and nothing around it: no page chrome, no other panel.
        assert "<html" not in body

    def test_it_pages(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)
        url = reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id})

        response = client.get(url, {"vuln_page": "2"}, headers={"hx-request": "true"})
        body = response.content.decode()

        assert "CVE-2026-0005" in body
        assert "CVE-2026-0004" not in body
        assert "Page 2 / 3" in body

    def test_it_filters_before_it_slices(self, sample_team_with_owner_member, sample_user):
        """Searching for row 30 of 40 has to find it, though it is not rendered."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)
        url = reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id})

        response = client.get(url, {"vuln_search": "CVE-2026-0030"}, headers={"hx-request": "true"})
        body = response.content.decode()

        assert "CVE-2026-0030" in body
        assert "Showing 1 to 1 of 1" in body

    def test_a_plain_request_is_sent_to_the_page_carrying_its_parameters(
        self, sample_team_with_owner_member, sample_user
    ):
        """So a pager link works with JavaScript off, and a shared URL opens the page."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)
        url = reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id})

        response = client.get(url, {"vuln_page": "2", "vuln_search": "pkg-0006"})

        assert response.status_code == 302
        assert response.headers["Location"].startswith(
            reverse("core:component_details", kwargs={"component_id": component.id})
        )
        assert "vuln_search=pkg-0006" in response.headers["Location"]
        assert response.headers["Location"].endswith("#component-vulnerabilities")

    def test_the_page_renders_the_state_the_redirect_carries(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        response = client.get(
            reverse("core:component_details", kwargs={"component_id": component.id}),
            {"vuln_page": "2"},
        )

        assert response.context["vuln_panel"]["page"] == 2
        assert "CVE-2026-0005" in response.content.decode()

    def test_a_document_component_has_no_panel_to_serve(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = Component.objects.create(
            name="policy",
            team=member.team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PRIVATE,
        )
        client = _client(member.team, sample_user)

        response = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        )

        assert response.status_code == 404

    def test_it_grants_no_more_than_the_page_it_belongs_to(self, sample_team_with_owner_member, guest_user):
        """A component a reader may not open must not become readable a region at a time."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=3)
        client = Client()
        client.force_login(guest_user)

        response = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        )

        assert response.status_code in (403, 404)
        assert "CVE-2026-0000" not in response.content.decode()

    def test_it_needs_a_session(self, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=3)

        response = Client().get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        )

        assert response.status_code in (302, 403, 404)
        assert "CVE-2026-0000" not in response.content.decode()
