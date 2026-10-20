"""Triaging from the vulnerabilities panel, and choosing how many rows it shows.

Reported by a pilot customer. The panel is the only findings view with search
and filters, so it is where a reader actually locates a finding, and it was the
one place they could not act on it: the triage control lived only on the
artifact page's assessment card, which has no filtering at all. Having found the
finding they wanted, a reader had to go elsewhere and page an unfiltered list
until they reached it again.

The page size was pinned at five for everyone, which is what made that second
list so long. The panel is now the workspace Vulnerabilities list scoped to the
component, so it offers that list's sizes: 10, 25 or 50, 25 by default.
"""

from __future__ import annotations

import re
from html import unescape

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db

PANEL_URL_NAME = "core:component_vulnerabilities_panel"


def _component_with_findings(team, count: int = 40, *, purl: bool = True):
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    component = Component.objects.create(
        name="triage-target",
        team=team,
        component_type=Component.ComponentType.BOM,
        visibility=Component.Visibility.PRIVATE,
    )
    sbom = SBOM.objects.create(
        name="image",
        version="2.0.0",
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="image.json",
        bom_type=SBOM.BomType.SBOM,
    )
    findings = []
    for n in range(count):
        package = {"name": f"pkg-{n:04d}", "version": "1.0", "ecosystem": "deb"}
        if purl:
            package["purl"] = f"pkg:deb/debian/pkg-{n:04d}@1.0"
        findings.append({"id": f"CVE-2026-{n:04d}", "severity": "high", "component": package})
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category="security",
        status="completed",
        result={"findings": findings},
    )
    # The panel reads the projected findings, as the workspace list does.
    sync_findings(run)
    return component


def _client(team, user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _panel(client: Client, component_id: str, **params):
    """One page of the panel, the way its own endpoint serves it."""
    url = reverse(PANEL_URL_NAME, args=[component_id])
    return client.get(url, params, headers={"hx-request": "true"})


def _triage_urls(body: str, component_id: str) -> list[str]:
    """The triage dialog URL each row's control loads, unescaped."""
    base = reverse("core:component_triage_modal", args=[component_id])
    return [unescape(url) for url in re.findall(rf'data-triage-url="({re.escape(base)}\?[^"]+)"', body)]


def _ids(response) -> list[str]:
    return [row["id"] for row in response.context["vuln_data"]["rows"]]


class TestTheReaderCanActOnWhatTheyFound:
    def test_a_row_carries_a_triage_control(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=10)
        client = _client(member.team, sample_user)

        body = _panel(client, component.id).content.decode()

        assert len(_triage_urls(body, component.id)) == 10
        assert "Triage" in body

    def test_the_control_loads_the_finding_in_its_own_sbom(self, sample_team_with_owner_member, sample_user):
        """The control names the occurrence and the SBOM it was read from, not just the component."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)
        sbom_id = component.sbom_set.get().id

        urls = _triage_urls(_panel(client, component.id).content.decode(), component.id)

        assert any("advisory=CVE-2026-0000" in url and f"sbom={sbom_id}" in url for url in urls)

    def test_the_control_anchors_the_decision_to_the_package(self, sample_team_with_owner_member, sample_user):
        """The dialog it loads knows the purl, so the decision can name the package."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)
        url = next(
            url
            for url in _triage_urls(_panel(client, component.id).content.decode(), component.id)
            if "CVE-2026-0000" in url
        )

        dialog = client.get(url, headers={"hx-request": "true"})

        assert dialog.status_code == 200
        assert dialog.context["triage_payload"]["purl"] == "pkg:deb/debian/pkg-0000@1.0"

    def test_a_finding_with_no_purl_still_gets_a_control(self, sample_team_with_owner_member, sample_user):
        """Without a purl the modal falls back to component scope, which is a
        different decision, not a missing one."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3, purl=False)
        client = _client(member.team, sample_user)
        url = _triage_urls(_panel(client, component.id).content.decode(), component.id)[0]

        dialog = client.get(url, headers={"hx-request": "true"})

        assert dialog.status_code == 200
        assert dialog.context["triage_payload"]["purl"] in ("", None)

    def test_an_outsider_is_offered_nothing(self, sample_team_with_owner_member, guest_user):
        """No panel, so no control."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        outsider = Client()
        outsider.force_login(guest_user)

        response = _panel(outsider, component.id)

        assert response.status_code in (403, 404)
        assert not _triage_urls(response.content.decode(), component.id)

    def test_every_reader_of_the_panel_may_triage_on_it(self, sample_team_with_owner_member, sample_user):
        """The flag is computed, not hardcoded true; this pins the value it takes."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)

        assert _panel(client, component.id).context["vuln_data"]["can_triage"] is True


class TestTheReaderChoosesHowMuchToSee:
    def test_the_default_is_the_workspace_lists(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id)

        assert response.context["vuln_data"]["query"].per_page == "25"
        assert len(_ids(response)) == 25

    @pytest.mark.parametrize("size", [10, 25, 50])
    def test_a_reader_can_choose_a_size(self, sample_team_with_owner_member, sample_user, size):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=60)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, per_page=size)

        assert response.context["vuln_data"]["query"].per_page == str(size)
        assert len(_ids(response)) == size

    def test_the_request_cannot_ask_for_the_whole_list(self, sample_team_with_owner_member, sample_user):
        """The rows are filtered and sliced in Python, so an unbounded page size
        is the response this panel was paged to prevent."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=400)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, per_page=100000)

        assert response.context["vuln_data"]["query"].per_page == "25"
        assert len(_ids(response)) == 25

    @pytest.mark.parametrize("bad", ["", "abc", "-5", "0", "1", "7", "26", "100"])
    def test_a_size_the_toolbar_does_not_offer_falls_back_to_one_it_does(
        self, sample_team_with_owner_member, sample_user, bad
    ):
        """A value the select cannot show as selected would leave the control
        blank while paging used a size the reader never chose."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=60)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, per_page=bad)

        assert response.status_code == 200
        data = response.context["vuln_data"]
        assert data["query"].per_page == "25"
        assert data["query"].per_page in data["per_page_choices"]
        assert len(_ids(response)) == 25

    def test_the_panel_asks_for_the_component_once(self, sample_team_with_owner_member, sample_user):
        """Whether the reader may see the panel and whether they may triage on
        it are two verdicts from one lookup. Asking separately put a second
        Component query on every filter change and page turn."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=10)
        client = _client(member.team, sample_user)
        _panel(client, component.id)  # warm anything cached per process

        with CaptureQueriesContext(connection) as captured:
            _panel(client, component.id)

        # Lookups of this component. The list itself reads the workspace's
        # component names once, which is not a second verdict on this one.
        lookup = f""""sboms_components"."id" = '{component.id}'"""
        component_reads = sum(1 for query in captured if query["sql"].startswith("SELECT") and lookup in query["sql"])
        assert 1 <= component_reads <= 2, f"{component_reads} component lookups for one panel render"

    def test_paging_keeps_the_size_the_reader_chose(self, sample_team_with_owner_member, sample_user):
        """The pager sits outside the filter form, so its links carry the state
        themselves or following one silently resets it."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=60)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, per_page=10)

        next_link = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*aria-label="Next page"', response.content.decode())
        assert next_link is not None
        next_response = client.get(unescape(next_link.group(1)), headers={"hx-request": "true"})

        assert next_response.status_code == 200
        data = next_response.context["vuln_data"]
        assert data["page"].number == 2
        assert data["query"].per_page == "10"
        assert len(_ids(next_response)) == 10
        assert not set(_ids(next_response)) & set(_ids(response))

    def test_a_bigger_page_reaches_findings_the_default_does_not(self, sample_team_with_owner_member, sample_user):
        """The point of the control, from the reader's side."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        default_ids = set(_ids(_panel(client, component.id)))
        wider = _panel(client, component.id, per_page=50)
        beyond = sorted(set(_ids(wider)) - default_ids)

        assert len(beyond) == 15
        assert beyond[0] not in _panel(client, component.id).content.decode()
        assert beyond[0] in wider.content.decode()
