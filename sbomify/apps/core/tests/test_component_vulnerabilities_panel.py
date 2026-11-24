"""The component page's vulnerabilities panel, paged on the server.

The page used to render every finding of the newest SBOM and let the browser
show five at a time. On a Yocto-class BSP that was 2,390 rows, 8.5 MB of HTML
and 5.1 s of template render against a 30 s gateway timeout, which is how a
trial workspace turned one component page into site-wide 504s.

So the thing worth pinning is a size, not a feature: the response must carry the
page, not the set. The rest of these tests cover what paging had to take with
it, because filtering a list the browser can no longer see all of has to happen
before the slice.

The panel is now the workspace Vulnerabilities list scoped to the component, so
it takes that list's parameters (``search``, ``severity``, ``exposure``,
``per_page``, ``page``) and pages 25 rows at a time by default.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import Component

pytestmark = pytest.mark.django_db

PANEL = "core:component_vulnerabilities_panel"


def _component_with_findings(team, count: int = 40, name: str = "embedded-image", **row_overrides):
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

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
            "severity": "high",
            "component": {"name": f"pkg-{n:04d}", "version": "1.0", "ecosystem": "deb"},
            **row_overrides,
        }
        for n in range(count)
    ]
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category="security",
        status="completed",
        result={"findings": findings},
    )
    # The panel reads the projected findings, as the workspace list does.
    sync_findings(run)
    return component, sbom


def _client(team, user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _ids(response) -> list[str]:
    return [row["id"] for row in response.context["vuln_data"]["rows"]]


def _page(client: Client, component, **params):
    return client.get(reverse("core:component_details", kwargs={"component_id": component.id}), params)


def _panel(client: Client, component, **params):
    return client.get(reverse(PANEL, kwargs={"component_id": component.id}), params, headers={"hx-request": "true"})


class TestThePageShipsOnePage:
    def test_the_component_page_renders_one_page_not_every_finding(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = _page(client, component)
        body = response.content.decode()
        shown = _ids(response)
        hidden = {f"CVE-2026-{n:04d}" for n in range(40)} - set(shown)

        assert response.status_code == 200
        assert len(shown) == 25
        assert all(cve in body for cve in shown)
        assert len(hidden) == 15
        assert not any(cve in body for cve in hidden)

    def test_the_header_badge_still_counts_every_finding(self, sample_team_with_owner_member, sample_user):
        """The summary is the whole scan; only the table is a page of it."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = _page(client, component)

        assert response.context["vuln_summary"]["total"] == 40
        assert response.context["vuln_summary"]["high"] == 40
        assert response.context["vuln_data"]["summary"]["vulnerabilities"] == 40
        assert response.context["vuln_data"]["total"] == 40
        assert len(response.context["vuln_data"]["rows"]) == 25

    def test_the_footer_counts_the_whole_list(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = _page(client, component)

        assert "Showing 1 to 25 of 40" in response.content.decode()


class TestTheReportedIncident:
    """The customer's case, at its real size, as one property.

    The component that prompted this carried 2,390 findings. The page rendered
    every one of them into the HTML to show five: 8.5 MB and 5.10 s of template
    render on production, against Caddy's 30 s response_header_timeout.

    What went wrong is not "the page was slow" but "the page grew with the
    scan", so that is what is asserted: **the response size does not depend on
    how many findings the component has.** A 2,390-finding component and a
    300-finding one must ship within a few hundred bytes of each other, the
    difference being the footer's count and the page numbers.

    Marked slow because it builds the real number of findings; it runs in a
    couple of seconds, which is itself the point.
    """

    @pytest.mark.slow
    def test_the_response_size_does_not_grow_with_the_finding_count(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        # Enough pages that both pagers elide the same way, so what is compared
        # is the findings, not the shape of the page links.
        small, _ = _component_with_findings(member.team, count=300, name="small")
        huge, _ = _component_with_findings(member.team, count=2390, name="large-image")
        client = _client(member.team, sample_user)

        small_body = _page(client, small).content
        huge_body = _page(client, huge).content

        growth = len(huge_body) - len(small_body)
        assert growth < 1024, f"the page grew {growth} bytes for 2,090 more findings"
        # An absolute ceiling as well, so a future regression that makes both
        # pages huge cannot pass by growing them equally. The page carries 25
        # rows by default now, each with its own actions menu.
        assert len(huge_body) < 640 * 1024, f"{len(huge_body)} bytes for one component page"

    @pytest.mark.slow
    def test_the_page_is_still_correct_at_that_size(self, sample_team_with_owner_member, sample_user):
        """Cheap is no good if the numbers stopped being true."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=2390)
        client = _client(member.team, sample_user)

        response = _page(client, component)

        assert response.context["vuln_summary"]["total"] == 2390
        assert response.context["vuln_data"]["page"].paginator.num_pages == 96
        assert "Showing 1 to 25 of 2,390" in response.content.decode()

    @pytest.mark.slow
    def test_the_last_finding_is_still_reachable(self, sample_team_with_owner_member, sample_user):
        """Nothing was dropped; it is a page away rather than in the first response."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=2390)
        client = _client(member.team, sample_user)

        response = _panel(client, component, search="CVE-2026-2389")

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

        response = _page(client, component)

        assert response.context["vuln_summary"]["total"] == 4
        # Nothing to list row by row, so the panel has no rows to page through.
        assert response.context["vuln_data"]["total"] == 0
        assert response.context["vuln_data"]["rows"] == []


class TestPublishedComponentsAreNotOpen:
    """Publishing a component does not publish its CVE list.

    ``get_component`` answers 200 for any PUBLIC or GATED component to anyone,
    because it also serves the trust-center read path. Treating that 200 as
    authorization hands every authenticated user the findings, VEX dispositions
    and KEV flags of every published component in the install, none of which the
    public component page renders. The panel and the page it lives on both gate
    on the reader's rights in the workspace instead.
    """

    @pytest.fixture
    def outsider(self, guest_user) -> Client:
        """Authenticated, and a member of nothing."""
        client = Client()
        client.force_login(guest_user)
        return client

    @pytest.mark.parametrize("visibility", ["public", "gated", "private"])
    def test_the_panel_endpoint_tells_an_outsider_nothing(self, sample_team_with_owner_member, outsider, visibility):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=8, name=f"published-{visibility}")
        Component.objects.filter(pk=component.id).update(visibility=visibility)

        response = _panel(outsider, component)

        assert response.status_code in (403, 404)
        assert "CVE-2026-0000" not in response.content.decode()

    @pytest.mark.parametrize("visibility", ["public", "gated", "private"])
    def test_the_component_page_tells_an_outsider_nothing(self, sample_team_with_owner_member, outsider, visibility):
        """The page has the same hole as the endpoint, so it takes the same fix."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=8, name=f"page-{visibility}")
        Component.objects.filter(pk=component.id).update(visibility=visibility)

        response = _page(outsider, component)

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

        response = _page(client, component)

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

        body = _panel(client, component, severity="high", page="2", per_page="10").content.decode()

        assert 'hx-push-url="true"' in body

    def test_what_it_pushes_is_something_a_plain_request_can_serve(self, sample_team_with_owner_member, sample_user):
        """Pushing a URL that only htmx can render would break the refresh it exists to fix."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)
        params = {"severity": "high", "page": "2", "per_page": "10"}

        panel = _panel(client, component, **params)
        page = _page(client, component, **params)

        assert panel.status_code == 200
        assert page.status_code == 200
        assert len(_ids(panel)) == 2
        assert _ids(page) == _ids(panel)


class TestThePanelEndpoint:
    def test_an_htmx_request_gets_the_region_rather_than_the_page(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        response = _panel(client, component)
        body = response.content.decode()

        assert response.status_code == 200
        assert 'id="component-vulnerabilities-table"' in body
        # The region and nothing around it: no page chrome, no other panel.
        assert "<html" not in body

    def test_the_pager_and_a_refresh_get_only_the_results(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        response = client.get(
            reverse(PANEL, kwargs={"component_id": component.id}),
            headers={"hx-request": "true", "hx-target": "component-vulnerabilities-results"},
        )
        body = response.content.decode()

        assert response.status_code == 200
        assert 'id="component-vulnerabilities-results"' in body
        # Not the toolbar around it.
        assert 'id="component-vulnerabilities-table"' not in body
        assert 'id="component-vulnerabilities-search"' not in body

    def test_it_pages(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        first = _panel(client, component, per_page="10")
        second = _panel(client, component, per_page="10", page="2")
        body = second.content.decode()

        assert len(_ids(second)) == 2
        assert not set(_ids(second)) & set(_ids(first))
        assert all(cve in body for cve in _ids(second))
        assert 'aria-current="page"' in body
        assert "Showing 11 to 12 of 12" in body

    def test_it_filters_before_it_slices(self, sample_team_with_owner_member, sample_user):
        """Searching for a row past the first page has to find it, though it is not rendered."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)
        unfiltered = _panel(client, component)
        beyond = sorted({f"CVE-2026-{n:04d}" for n in range(40)} - set(_ids(unfiltered)))[0]

        response = _panel(client, component, search=beyond)
        body = response.content.decode()

        assert _ids(response) == [beyond]
        assert "Showing 1 to 1 of 1" in body

    def test_a_plain_request_is_sent_to_the_page_carrying_its_parameters(
        self, sample_team_with_owner_member, sample_user
    ):
        """So a pager link works with JavaScript off, and a shared URL opens the page."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)
        url = reverse(PANEL, kwargs={"component_id": component.id})

        response = client.get(url, {"page": "2", "search": "pkg-0006"})

        assert response.status_code == 302
        assert response.headers["Location"].startswith(
            reverse("core:component_details", kwargs={"component_id": component.id})
        )
        assert "search=pkg-0006" in response.headers["Location"]
        assert "page=2" in response.headers["Location"]
        assert response.headers["Location"].endswith("#component-vulnerabilities")

    def test_the_page_renders_the_state_the_redirect_carries(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=12)
        client = _client(member.team, sample_user)

        response = _page(client, component, page="2", per_page="10")

        assert response.context["vuln_data"]["page"].number == 2
        assert len(_ids(response)) == 2
        assert all(cve in response.content.decode() for cve in _ids(response))

    def test_a_document_component_has_no_panel_to_serve(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = Component.objects.create(
            name="policy",
            team=member.team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PRIVATE,
        )
        client = _client(member.team, sample_user)

        response = _panel(client, component)

        assert response.status_code == 404

    def test_it_grants_no_more_than_the_page_it_belongs_to(self, sample_team_with_owner_member, guest_user):
        """A component a reader may not open must not become readable a region at a time."""
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=3)
        client = Client()
        client.force_login(guest_user)

        response = _panel(client, component)

        assert response.status_code in (403, 404)
        assert "CVE-2026-0000" not in response.content.decode()

    def test_it_needs_a_session(self, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=3)

        response = _panel(Client(), component)

        assert response.status_code in (302, 403, 404)
        assert "CVE-2026-0000" not in response.content.decode()


class TestTheExploitedFilter:
    """Known exploited is read from the catalog on every request, never stored,
    so the feed is what decides which rows the filter keeps."""

    def test_it_keeps_only_the_catalogued_finding_and_counts_it(
        self, sample_team_with_owner_member, monkeypatch
    ) -> None:
        from sbomify.apps.vulnerability_scanning import kev

        team = sample_team_with_owner_member.team
        component, _ = _component_with_findings(team, count=3)
        monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2026-0001"}))
        client = _client(team, sample_team_with_owner_member.user)

        response = _panel(client, component, exposure="exploited")

        assert _ids(response) == ["CVE-2026-0001"]
        assert response.context["vuln_data"]["summary"]["exploited"] == 1
        assert "KEV" in response.content.decode()

    def test_a_scan_with_none_lists_nothing_under_it(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        component, _ = _component_with_findings(team, count=3)
        client = _client(team, sample_team_with_owner_member.user)

        response = _panel(client, component, exposure="exploited")

        assert _ids(response) == []
        assert response.context["vuln_data"]["summary"]["exploited"] == 0


class TestTriageModal:
    def test_loads_exact_package_and_saved_decision(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(
            member.team,
            count=40,
            analysis_state="in_triage",
            analysis_detail="Checking exposure",
        )
        response = _client(member.team, sample_user).get(
            reverse("core:component_triage_modal", args=[component.id]),
            {"advisory": "CVE-2026-0030", "package": "pkg-0030", "version": "1.0", "ecosystem": "deb"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert response.context["triage_payload"]["id"] == "CVE-2026-0030"
        assert response.context["triage_payload"]["state"] == "in_triage"
        assert response.context["triage_payload"]["detail"] == "Checking exposure"
        assert response.context["component_id"] == component.id

    def test_rejects_another_workspace(self, sample_team_with_owner_member, sample_user):
        from sbomify.apps.teams.models import Workspace

        other_workspace = Workspace.objects.create(name="Other workspace")
        component, _ = _component_with_findings(other_workspace, count=1)
        response = _client(sample_team_with_owner_member.team, sample_user).get(
            reverse("core:component_triage_modal", args=[component.id]),
            {"advisory": "CVE-2026-0000", "package": "pkg-0000", "version": "1.0", "ecosystem": "deb"},
            HTTP_HX_REQUEST="true",
        )
        assert response.headers["HX-Reswap"] == "none"
        assert "triage-modal" not in response.content.decode()

    def test_names_the_component_s_workspace_not_the_session_s(self, sample_team_with_owner_member, sample_user):
        """The modal posts this key when the scope is every component in the workspace."""
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Workspace

        other_workspace = Workspace.objects.create(name="Other workspace")
        other_workspace.key = number_to_random_token(other_workspace.pk)
        other_workspace.save(update_fields=["key"])
        Member.objects.create(team=other_workspace, user=sample_user, role="member")
        component, _ = _component_with_findings(other_workspace, count=1)
        client = _client(sample_team_with_owner_member.team, sample_user)

        modal = client.get(
            reverse("core:component_triage_modal", args=[component.id]),
            {"advisory": "CVE-2026-0000", "package": "pkg-0000", "version": "1.0", "ecosystem": "deb"},
            HTTP_HX_REQUEST="true",
        )
        page = client.get(reverse("core:component_details", kwargs={"component_id": component.id}))

        assert modal.context["team_key"] == other_workspace.key
        assert page.context["team_key"] == other_workspace.key

    def test_does_not_fall_back_to_a_different_package(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component, _ = _component_with_findings(member.team, count=1)
        response = _client(member.team, sample_user).get(
            reverse("core:component_triage_modal", args=[component.id]),
            {"advisory": "CVE-2026-0000", "package": "missing", "version": "1.0", "ecosystem": "deb"},
            HTTP_HX_REQUEST="true",
        )
        assert response.headers["HX-Reswap"] == "none"
        assert "triage-modal" not in response.content.decode()
