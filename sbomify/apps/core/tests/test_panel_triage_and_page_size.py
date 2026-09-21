"""Triaging from the vulnerabilities panel, and choosing how many rows it shows.

Reported by a pilot customer. The panel is the only findings view with search
and filters, so it is where a reader actually locates a finding, and it was the
one place they could not act on it: the triage control lived only on the
artifact page's assessment card, which has no filtering at all. Having found the
finding they wanted, a reader had to go elsewhere and page an unfiltered list
until they reached it again.

The page size was pinned at five for everyone, which is what made that second
list so long.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import Component

pytestmark = pytest.mark.django_db

PANEL_URL_NAME = "core:component_vulnerabilities_panel"


def _component_with_findings(team, count: int = 40, *, purl: bool = True):
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

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
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category="security",
        status="completed",
        result={"findings": findings},
    )
    return component


def _client(team, user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


def _panel(client: Client, component_id: str, **params):
    """One page of the panel, the way its own endpoint serves it."""
    url = reverse(PANEL_URL_NAME, args=[component_id])
    return client.get(url, params, headers={"hx-request": "true"})


class TestTheReaderCanActOnWhatTheyFound:
    def test_a_row_carries_a_triage_control(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=10)
        client = _client(member.team, sample_user)

        body = _panel(client, component.id).content.decode()

        assert "open-triage" in body
        assert ">Triage<" in body or "Triage" in body

    def test_the_control_carries_the_finding_and_its_package(self, sample_team_with_owner_member, sample_user):
        """The modal re-opens a decision with the values it was saved under, and
        anchors it to the package when a purl is known.

        The payload goes through ``escapejs``, which rewrites ``-`` as ``\\u002D``
        among others, so the expected string is built the same way rather than
        typed out and left to rot.
        """
        from django.utils.html import escapejs

        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)

        body = _panel(client, component.id).content.decode()

        assert escapejs("CVE-2026-0000") in body
        assert escapejs("pkg:deb/debian/pkg-0000@1.0") in body

    def test_a_finding_with_no_purl_still_gets_a_control(self, sample_team_with_owner_member, sample_user):
        """Without a purl the modal falls back to component scope, which is a
        narrower decision, not a missing one."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3, purl=False)
        client = _client(member.team, sample_user)

        body = _panel(client, component.id).content.decode()

        assert "open-triage" in body

    def test_the_rows_carry_the_purl_for_the_control_to_use(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)

        rows = _panel(client, component.id).context["vuln_panel"]["rows"]

        assert rows[0]["purl"] == "pkg:deb/debian/pkg-0000@1.0"
        assert "vex_detail" in rows[0]

    def test_an_outsider_is_offered_nothing(self, sample_team_with_owner_member, guest_user):
        """No panel, so no control.

        Worth saying plainly: ``artifact:publish_vex`` is PUBLISH and the panel
        itself is gated on ``component:manage``, and those tiers currently hold
        the same internal roles. So every reader who can see this panel can also
        triage on it, and the flag exists to follow the API's tier rather than to
        split today's readers into two groups.
        """
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        outsider = Client()
        outsider.force_login(guest_user)

        response = _panel(outsider, component.id)

        assert response.status_code in (403, 404)
        assert "open-triage" not in response.content.decode()

    def test_every_reader_of_the_panel_may_triage_on_it(self, sample_team_with_owner_member, sample_user):
        """The flag is computed, not hardcoded true; this pins the value it takes."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=3)
        client = _client(member.team, sample_user)

        assert _panel(client, component.id).context["can_triage"] is True


class TestTheReaderChoosesHowMuchToSee:
    def test_the_default_is_unchanged(self, sample_team_with_owner_member, sample_user):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        panel = _panel(client, component.id).context["vuln_panel"]

        assert panel["per_page"] == 5
        assert len(panel["rows"]) == 5

    @pytest.mark.parametrize("size", [10, 25, 50])
    def test_a_reader_can_ask_for_more(self, sample_team_with_owner_member, sample_user, size):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=60)
        client = _client(member.team, sample_user)

        panel = _panel(client, component.id, vuln_per_page=size).context["vuln_panel"]

        assert panel["per_page"] == size
        assert len(panel["rows"]) == size

    def test_the_request_cannot_ask_for_the_whole_list(self, sample_team_with_owner_member, sample_user):
        """The rows are filtered and sliced in Python, so an unbounded page size
        is the response this panel was paged to prevent."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=400)
        client = _client(member.team, sample_user)

        panel = _panel(client, component.id, vuln_per_page=100000).context["vuln_panel"]

        assert panel["per_page"] == 100
        assert len(panel["rows"]) == 100

    @pytest.mark.parametrize("bad", ["", "abc", "-5", "0"])
    def test_a_value_that_is_not_a_size_shows_the_panel_anyway(self, sample_team_with_owner_member, sample_user, bad):
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=20)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, vuln_per_page=bad)

        assert response.status_code == 200
        assert response.context["vuln_panel"]["per_page"] in (1, 5)

    def test_paging_keeps_the_size_the_reader_chose(self, sample_team_with_owner_member, sample_user):
        """The pager sits outside the filter form, so its links carry the state
        themselves or following one silently resets it."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=60)
        client = _client(member.team, sample_user)

        response = _panel(client, component.id, vuln_per_page=25)

        assert "vuln_per_page=25" in response.context["vuln_next_url"]

    def test_a_bigger_page_reaches_findings_the_default_does_not(self, sample_team_with_owner_member, sample_user):
        """The point of the control, from the reader's side."""
        member = sample_team_with_owner_member
        component = _component_with_findings(member.team, count=40)
        client = _client(member.team, sample_user)

        default_body = _panel(client, component.id).content.decode()
        wider_body = _panel(client, component.id, vuln_per_page=25).content.decode()

        assert "CVE-2026-0020" not in default_body
        assert "CVE-2026-0020" in wider_body
