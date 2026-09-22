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


class TestTheReportedIncident:
    """The customer's case, at its real size, as one property.

    The component that prompted this carried 2,390 findings. The page rendered
    every one of them into the HTML to show five: 8.5 MB and 5.10 s of template
    render on production, against Caddy's 30 s response_header_timeout.

    What went wrong is not "the page was slow" but "the page grew with the
    scan", so that is what is asserted: **the response size does not depend on
    how many findings the component has.** A 2,390-finding component and a
    50-finding one must ship within a few hundred bytes of each other, the
    difference being the footer's count and the page number.

    That is the assertion that would have failed before. Rendering this same
    fixture unbounded produces **7.83 MB** of HTML against **0.027 MB** paged,
    so the old page failed the comparison by roughly 290x rather than by a
    margin someone could argue about.

    Marked slow because it builds the real number of findings; it runs in a
    couple of seconds, which is itself the point.
    """

    @pytest.mark.slow
    def test_the_response_size_does_not_grow_with_the_finding_count(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        small, _ = _component_with_findings(member.team, count=50, name="small")
        huge, _ = _component_with_findings(member.team, count=2390, name="large-image")
        client = _client(member.team, sample_user)

        small_body = client.get(reverse("core:component_details", kwargs={"component_id": small.id})).content
        huge_body = client.get(reverse("core:component_details", kwargs={"component_id": huge.id})).content

        growth = len(huge_body) - len(small_body)
        assert growth < 1024, f"the page grew {growth} bytes for 2,340 more findings"
        # An absolute ceiling as well, so a future regression that makes both
        # pages huge cannot pass by growing them equally.
        assert len(huge_body) < 512 * 1024, f"{len(huge_body)} bytes for one component page"

    @pytest.mark.slow
    def test_the_page_is_still_correct_at_that_size(self, sample_team_with_owner_member, sample_user):
        """Cheap is no good if the numbers stopped being true."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=2390)
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.context["vuln_summary"]["total"] == 2390
        assert response.context["vuln_panel"]["page_count"] == 478
        assert "Showing 1 to 5 of 2390" in response.content.decode()

    @pytest.mark.slow
    def test_the_last_finding_is_still_reachable(self, sample_team_with_owner_member, sample_user):
        """Nothing was dropped; it is a page away rather than in the first response."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=2390)
        client = _client(member.team, sample_user)

        response = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            {"vuln_search": "CVE-2026-2389"},
            headers={"hx-request": "true"},
        )

        assert "CVE-2026-2389" in response.content.decode()


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


class TestPublishedComponentsAreNotOpen:
    """Publishing a component does not publish its CVE list.

    ``get_component`` answers 200 for any PUBLIC or GATED component to anyone,
    because it also serves the trust-center read path. Treating that 200 as
    authorization hands every authenticated user the findings, VEX dispositions
    and KEV flags of every published component in the install, none of which the
    public component page renders. The panel and the page it lives on both gate
    on ``component:manage`` instead.
    """

    @pytest.fixture
    def outsider(self, guest_user) -> Client:
        """Authenticated, and a member of nothing."""
        client = Client()
        client.force_login(guest_user)
        return client

    @pytest.mark.parametrize("visibility", ["public", "gated", "private"])
    def test_the_panel_endpoint_tells_an_outsider_nothing(
        self, sample_team_with_owner_member, outsider, visibility
    ):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=8, name=f"published-{visibility}")
        Component.objects.filter(pk=component.id).update(visibility=visibility)

        response = outsider.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        )

        assert response.status_code in (403, 404)
        assert "CVE-2026-0000" not in response.content.decode()

    @pytest.mark.parametrize("visibility", ["public", "gated", "private"])
    def test_the_component_page_tells_an_outsider_nothing(
        self, sample_team_with_owner_member, outsider, visibility
    ):
        """The page has the same hole as the endpoint, so it takes the same fix."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=8, name=f"page-{visibility}")
        Component.objects.filter(pk=component.id).update(visibility=visibility)

        response = outsider.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert "CVE-2026-0000" not in response.content.decode()
        assert "component-vulnerabilities-table" not in response.content.decode()

    def test_a_member_of_the_workspace_still_sees_its_own_published_component(
        self, sample_team_with_owner_member, sample_user
    ):
        """The gate is membership, not privacy: publishing must not blind the owner."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=8, name="published-own")
        Component.objects.filter(pk=component.id).update(visibility="public")
        client = _client(member.team, sample_user)

        response = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert response.status_code == 200
        assert "CVE-2026-0000" in response.content.decode()


class TestTheFiltersSurviveALeaveAndAReturn:
    """A filtered panel has to be a place, not a gesture.

    Every swap replaces the region and leaves the address bar on the component
    page's bare URL, so without hx-push-url a refresh, a Back, or a link sent to
    a colleague all silently reset to page one with no filters. The view already
    renders the same state from a plain GET, so the URL is worth pushing.
    """

    def test_the_panel_pushes_its_url(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        body = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            {"vuln_severity": "high", "page": "2"},
            headers={"hx-request": "true"},
        ).content.decode()

        assert 'hx-push-url="true"' in body

    def test_what_it_pushes_is_something_a_plain_request_can_serve(
        self, sample_team_with_owner_member, sample_user
    ):
        """Pushing a URL that only htmx can render would break the refresh it exists to fix."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)
        params = {"vuln_severity": "high", "page": "2", "vuln_submitted": "1"}

        panel = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            params,
            headers={"hx-request": "true"},
        )
        page = client.get(
            reverse("core:component_details", kwargs={"component_id": component.id}), params
        )

        assert panel.status_code == 200
        assert page.status_code == 200
        assert [r["id"] for r in page.context["vuln_panel"]["rows"]] == [
            r["id"] for r in panel.context["vuln_panel"]["rows"]
        ]


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


class TestTheKevControlIsOfferedOnlyWhenItCanMatch:
    """A filter that can only ever return nothing is not a filter.

    The assessment card and the scan report both hide this control when the run
    holds no catalogued finding. The panel used to render it regardless, so on
    the common scan, which has none, ticking it emptied the list and nothing on
    the page said why.
    """

    def test_a_scan_with_none_does_not_offer_it(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        component, _ = _component_with_findings(team, count=3)
        client = _client(team, sample_team_with_owner_member.user)

        body = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        ).content.decode()

        assert "vuln_kev" not in body

    def test_a_scan_with_one_offers_it_and_counts_it(self, sample_team_with_owner_member, monkeypatch) -> None:
        """KEV is read from the catalog on every request, never stored, so the
        feed is what decides whether the control appears."""
        from sbomify.apps.vulnerability_scanning import kev

        team = sample_team_with_owner_member.team
        component, _ = _component_with_findings(team, count=3)
        monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2026-0001"}))
        client = _client(team, sample_team_with_owner_member.user)

        body = client.get(
            reverse("core:component_vulnerabilities_panel", kwargs={"component_id": component.id}),
            headers={"hx-request": "true"},
        ).content.decode()

        assert "vuln_kev" in body
        assert "Known exploited (1)" in body

    def test_the_three_views_say_the_same_thing(self) -> None:
        """Three templates offer this filter. They drifted into two spellings,
        and "KEV" is the catalog's acronym rather than a word a reader has.

        Resolved from BASE_DIR rather than the working directory, so this holds
        wherever pytest is started from.
        """
        from django.conf import settings

        roots = [
            "core/templates/core/components/component_vulnerabilities_table.html.j2",
            "plugins/templates/plugins/components/_assessment_run_findings.html.j2",
            "sboms/templates/sboms/sbom_vulnerabilities.html.j2",
        ]
        for relative in roots:
            path = settings.BASE_DIR / "sbomify" / "apps" / relative
            text = path.read_text(encoding="utf-8")
            assert "KEV only" not in text, f"{relative} still says KEV only"
            assert "Known exploited (" in text, f"{relative} lost the label"
