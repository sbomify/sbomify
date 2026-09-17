"""The artifact page's vulnerability card, when every scanner declined.

A skipped run contributes no vulnerabilities and zero severity counts, exactly
as a clean scan does. The stored result is not empty: it carries bookkeeping of
its own, a status finding naming the reason and the counts that go with it, and
``metadata.skipped`` is what marks it. None of that bookkeeping is a
vulnerability, so none of it reaches the numbers on the card. The internal
tables already tell the two apart.
The card at the top of the artifact page did not: it read the latest completed
security runs whatever they were, so an SPDX 3 document that OSV and Dependency
Track had both refused rendered as

    Vulnerability Scan  8 Sep 2026  DEPENDENCY-TRACK, OSV
    0 total findings    0 CRITICAL  0 HIGH  0 MEDIUM  0 LOW

which is what a clean scan looks like.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member


def _skipped(total_findings: int) -> dict[str, Any]:
    """A skipped result as the plugins actually store one.

    Two shapes are in production and the count is what differs.
    ``build_single_finding_result`` in the SDK sets total_findings to 0 on
    purpose, so a skip does not read as "1 finding"; OSV's no-packages skip
    builds its own summary and sets 1. Both carry the status finding and
    metadata.skipped, which is what this card reads, so both belong here.
    """
    return {
        "summary": {"total_findings": total_findings, "warning_count": 1},
        "findings": [
            {
                "id": "osv:no-packages",
                "title": "No Packages Recognised",
                "status": "warning",
                "severity": "info",
            }
        ],
        "metadata": {"scanner": "osv-scanner", "skipped": True, "no_packages": True},
    }


SKIPPED_RESULT: dict[str, Any] = _skipped(0)
CLEAN_RESULT: dict[str, Any] = {
    "summary": {"total_findings": 0, "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}},
    "findings": [],
    "metadata": {"scanner": "osv-scanner"},
}


def _run(
    sbom: SBOM,
    plugin_name: str,
    result: dict[str, Any],
    created_at: datetime | None = None,
    category: str = "security",
) -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        plugin_config_hash=sha256(plugin_name.encode()).hexdigest(),
        category=category,
        run_reason=RunReason.ON_UPLOAD.value,
        status="completed",
        result=result,
    )
    if created_at is not None:
        # created_at is auto_now_add, so it has to be written back.
        AssessmentRun.objects.filter(pk=run.pk).update(created_at=created_at)
        run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestTheScanCard:
    @pytest.fixture
    def signed_in(self, sample_team_with_owner_member: Member) -> tuple[Client, Component]:
        component = Component.objects.create(
            team=sample_team_with_owner_member.team,
            name="yocto-image",
            component_type=Component.ComponentType.BOM,
        )
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, component

    @staticmethod
    def _sbom(component: Component) -> SBOM:
        return SBOM.objects.create(
            component=component,
            name="core-image-minimal",
            format="spdx",
            format_version="3.0.0",
            version="1.0",
            sbom_filename="x.json",
        )

    def _summary(self, client: Client, component: Component, sbom: SBOM):
        url = reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id},
        )
        response = client.get(url)
        assert response.status_code == 200
        return response.context["vulnerability_summary"]

    @pytest.mark.parametrize("total_findings", [0, 1], ids=["sdk-shape", "osv-shape"])
    def test_every_scanner_skipping_leaves_no_scan_to_summarise(
        self, signed_in: tuple[Client, Component], total_findings: int
    ) -> None:
        """Both counts a skip is stored with. metadata.skipped is the marker,
        and neither shape may reach the card."""
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "osv", _skipped(total_findings))
        _run(sbom, "dependency-track", _skipped(total_findings))

        assert self._summary(client, component, sbom) is None

    def test_a_row_whose_skipped_column_never_got_written_is_still_read(
        self, signed_in: tuple[Client, Component]
    ) -> None:
        """result_skipped is tri-state, and null means unknown.

        The database filter cannot exclude those, so the result itself still
        has to be read for them. A row predating the column must not slip
        through as a scan.
        """
        client, component = signed_in
        sbom = self._sbom(component)
        run = _run(sbom, "osv", SKIPPED_RESULT)
        AssessmentRun.objects.filter(pk=run.pk).update(result_skipped=None)

        assert self._summary(client, component, sbom) is None

    def test_a_real_clean_scan_still_reports_zero(self, signed_in: tuple[Client, Component]) -> None:
        """Zero findings is a fact when something was actually examined."""
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "osv", CLEAN_RESULT)

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["total"] == 0
        assert summary["provider"] == "osv"

    def test_the_date_comes_from_the_scan_it_reports_not_from_a_later_skip(
        self, signed_in: tuple[Client, Component]
    ) -> None:
        """A skip that lands after a real scan must not lend it its timestamp."""
        client, component = signed_in
        sbom = self._sbom(component)
        scanned_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        _run(sbom, "osv", CLEAN_RESULT, created_at=scanned_at)
        _run(sbom, "dependency-track", SKIPPED_RESULT, created_at=scanned_at + timedelta(days=3))

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["provider"] == "osv"
        assert summary["scan_date"] == scanned_at

    def test_a_scanner_that_ran_is_not_hidden_by_one_that_skipped(self, signed_in: tuple[Client, Component]) -> None:
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "dependency-track", SKIPPED_RESULT)
        _run(sbom, "osv", CLEAN_RESULT)

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["provider"] == "osv"


@pytest.mark.django_db
class TestTheCardIsNotHandedEveryFinding:
    """The artifact page carried every finding to a card nobody had opened.

    `_assessment_run_item` renders its header from `result.summary` plus one
    title, `result.findings.0.title`. The list under it is a collapsed
    accordion, so it now arrives over HTMX a page at a time when a reader opens
    the card. Building it for every plugin on every page load, closed or not,
    measured 9 MB on staging for a thousand findings and 31 MB for four
    thousand, and a 504 at the 60s gateway in both cases. That is the same shape
    as the panel bug, one page over.
    """

    @pytest.fixture
    def signed_in(self, sample_team_with_owner_member: Member) -> tuple[Client, Component]:
        component = Component.objects.create(
            team=sample_team_with_owner_member.team,
            name="noisy-image",
            component_type=Component.ComponentType.BOM,
        )
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, component

    def _sbom_with(self, component: Component, finding_count: int) -> SBOM:
        sbom = SBOM.objects.create(
            component=component,
            name="noisy",
            format="cyclonedx",
            format_version="1.6",
            # Unique per size: documents are unique on component, name and version.
            version=f"1.0.{finding_count}",
            sbom_filename=f"noisy-{finding_count}.json",
        )
        findings = [
            {
                "id": f"CVE-2026-{i:05d}",
                "title": f"CVE-2026-{i:05d}",
                "description": "x" * 200,
                "severity": "high",
                "component": {"name": "tensorflow", "version": "2.0.0", "ecosystem": "PyPI"},
            }
            for i in range(finding_count)
        ]
        _run(
            sbom,
            "osv",
            {
                "plugin_name": "osv",
                "plugin_version": "1.0.0",
                "category": "security",
                "assessed_at": "2026-09-17T07:00:00Z",
                "summary": {
                    "total_findings": finding_count,
                    "by_severity": {"critical": 0, "high": finding_count, "medium": 0, "low": 0},
                },
                "findings": findings,
                "metadata": {"scanner": "osv-scanner"},
            },
        )
        return sbom

    def _runs(self, client: Client, component: Component, sbom: SBOM):
        url = reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id},
        )
        response = client.get(url)
        assert response.status_code == 200
        return response.context["assessment_runs"]

    def test_only_the_finding_the_card_shows_is_carried(self, signed_in) -> None:
        client, component = signed_in
        sbom = self._sbom_with(component, 500)

        runs = self._runs(client, component, sbom)

        osv = next(r for r in runs["latest_runs"] if r["plugin_name"] == "osv")
        assert len(osv["result"]["findings"]) == 1

    def test_the_title_the_card_renders_survives(self, signed_in) -> None:
        """`findings.0.title` is on the page, so the first one has to stay."""
        client, component = signed_in
        sbom = self._sbom_with(component, 500)

        runs = self._runs(client, component, sbom)

        osv = next(r for r in runs["latest_runs"] if r["plugin_name"] == "osv")
        assert osv["result"]["findings"][0]["title"] == "CVE-2026-00000"

    def test_every_count_the_card_shows_is_untouched(self, signed_in) -> None:
        """The numbers come from summary, never from counting the list."""
        client, component = signed_in
        sbom = self._sbom_with(component, 500)

        runs = self._runs(client, component, sbom)

        osv = next(r for r in runs["latest_runs"] if r["plugin_name"] == "osv")
        assert osv["result"]["summary"]["total_findings"] == 500
        assert osv["result"]["summary"]["by_severity"]["high"] == 500

    def test_the_page_does_not_grow_with_the_finding_count(self, signed_in) -> None:
        """The property that matters: 500 findings and 5,000 cost the same."""
        client, component = signed_in
        small = self._sbom_with(component, 50)
        large = self._sbom_with(component, 5000)

        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": small.id}
        )
        small_len = len(client.get(url).content)
        url = reverse(
            "core:component_item", kwargs={"component_id": component.id, "item_type": "sboms", "item_id": large.id}
        )
        large_len = len(client.get(url).content)

        # A hundredfold more findings must not show up as a bigger page.
        assert large_len < small_len * 1.1


@pytest.mark.django_db
class TestTheFindingsListArrivesWhenAsked:
    """The list behind a run card, and who may read it.

    Bounding the page's payload only helps if the findings are still reachable.
    They are, one page at a time, from the endpoint the collapsed card points
    at. Nothing fetches it until a reader opens the card.
    """

    @pytest.fixture
    def signed_in(self, sample_team_with_owner_member: Member) -> tuple[Client, Component]:
        component = Component.objects.create(
            team=sample_team_with_owner_member.team,
            name="lazy-image",
            component_type=Component.ComponentType.BOM,
        )
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, component

    @staticmethod
    def _run_with(component: Component, finding_count: int) -> AssessmentRun:
        sbom = SBOM.objects.create(
            component=component,
            name="lazy",
            format="cyclonedx",
            format_version="1.6",
            version=f"2.0.{finding_count}",
            sbom_filename=f"lazy-{finding_count}.json",
        )
        return _run(
            sbom,
            "osv",
            {
                "plugin_name": "osv",
                "plugin_version": "1.0.0",
                "category": "security",
                "assessed_at": "2026-09-17T07:00:00Z",
                "summary": {
                    "total_findings": finding_count,
                    "by_severity": {"critical": 0, "high": finding_count, "medium": 0, "low": 0},
                },
                "findings": [
                    {
                        "id": f"CVE-2026-{i:05d}",
                        "title": f"CVE-2026-{i:05d}",
                        "description": "x" * 200,
                        "severity": "high",
                        "component": {"name": "tensorflow", "version": "2.0.0", "ecosystem": "PyPI"},
                    }
                    for i in range(finding_count)
                ],
                "metadata": {"scanner": "osv-scanner"},
            },
        )

    @staticmethod
    def _findings_url(run: AssessmentRun, page: int | None = None) -> str:
        url = reverse("plugins:assessment_run_findings", kwargs={"run_id": str(run.id)})
        return url if page is None else f"{url}?page={page}"

    def _open(self, client: Client, run: AssessmentRun, page: int | None = None):
        """Fetch the list the way the card does, as HTMX."""
        return client.get(self._findings_url(run, page), headers={"hx-request": "true"})

    def test_the_closed_card_carries_the_link_and_none_of_the_rows(self, signed_in) -> None:
        client, component = signed_in
        run = self._run_with(component, 300)

        url = reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "sboms", "item_id": run.sbom_id},
        )
        html = client.get(url).content.decode()

        assert self._findings_url(run) in html
        # The placeholder and the partial that replaces it have to agree on the
        # id, or the pager swaps into nothing.
        assert f'id="findings-{run.id}"' in html
        assert f"from:#run-trigger-{run.id}" in html
        # One title rides along in the header; the three hundredth is not on the page.
        assert "CVE-2026-00299" not in html

    def test_a_page_of_findings_comes_back(self, signed_in) -> None:
        client, component = signed_in
        run = self._run_with(component, 300)

        html = self._open(client, run).content.decode()

        assert "CVE-2026-00000" in html
        assert "CVE-2026-00024" in html
        # 25 to a page, so the twenty-sixth belongs to the next one.
        assert "CVE-2026-00025" not in html
        assert "Page 1 / 12" in html

    def test_the_last_finding_is_reachable(self, signed_in) -> None:
        """The whole point of paging rather than dropping."""
        client, component = signed_in
        run = self._run_with(component, 300)

        html = self._open(client, run, page=12).content.decode()

        assert "CVE-2026-00299" in html

    def test_a_scanner_status_marker_is_not_listed_as_a_vulnerability(self, signed_in) -> None:
        client, component = signed_in
        run = self._run_with(component, 1)
        run.result["findings"].append(
            {"id": "osv:no-packages", "title": "No Packages Recognised", "status": "warning", "severity": "info"}
        )
        AssessmentRun.objects.filter(pk=run.pk).update(result=run.result)

        html = self._open(client, run).content.decode()

        assert "CVE-2026-00000" in html
        assert "No Packages Recognised" not in html

    def test_a_reader_without_the_component_gets_nothing(self, signed_in, guest_user) -> None:
        _, component = signed_in
        run = self._run_with(component, 5)
        outsider = Client()
        outsider.force_login(guest_user)

        response = outsider.get(self._findings_url(run), headers={"hx-request": "true"})

        assert response.status_code == 404

    def test_a_plain_visit_lands_on_the_artifact_page(self, signed_in) -> None:
        """A pasted link is a reader, not a swap, so it gets the page the card
        is on rather than a fragment with no styling around it."""
        client, component = signed_in
        run = self._run_with(component, 5)

        response = client.get(self._findings_url(run, page=1))

        assert response.status_code == 302
        assert response["Location"].startswith(
            reverse(
                "core:component_item",
                kwargs={"component_id": component.id, "item_type": "sboms", "item_id": str(run.sbom_id)},
            )
        )
        assert response["Location"].endswith("#plugin-osv")

    def test_an_id_that_is_not_a_run_is_a_404(self, signed_in) -> None:
        client, _ = signed_in

        url = reverse("plugins:assessment_run_findings", kwargs={"run_id": "run1"})
        assert client.get(url, headers={"hx-request": "true"}).status_code == 404


@pytest.mark.django_db
class TestTheBoundCannotBeTurnedOff:
    """``findings_limit`` reaches the assessments endpoint as a query parameter,
    and that endpoint is ``auth=None``. A negative value would slice from the
    end and return every finding but the last, which is the response the bound
    exists to prevent."""

    @staticmethod
    def _run_of(member: Member, category: str, count: int) -> AssessmentRun:
        component = Component.objects.create(
            team=member.team,
            name=f"bounded-{category}",
            component_type=Component.ComponentType.BOM,
        )
        sbom = SBOM.objects.create(
            component=component,
            name="bounded",
            format="cyclonedx",
            format_version="1.6",
            version=f"1.0.{count}",
            sbom_filename=f"bounded-{category}.json",
        )
        return _run(
            sbom,
            "osv" if category == "security" else "ntia-minimum-elements-2021",
            {
                "summary": {
                    "total_findings": count,
                    "by_severity": {"critical": 0, "high": count, "medium": 0, "low": 0},
                },
                "findings": [
                    {"id": f"CVE-2026-{i}", "title": f"CVE-2026-{i}", "severity": "high"} for i in range(count)
                ],
                "metadata": {"scanner": "osv-scanner"},
            },
            category=category,
        )

    @pytest.mark.parametrize("category", ["security", "compliance"])
    def test_the_bound_holds_whatever_the_plugin_checks(
        self, sample_team_with_owner_member: Member, category: str
    ) -> None:
        """A compliance plugin reports per component, so its list grows with the
        SBOM exactly as a scanner's does. The flags are security-only; the bound
        is not."""
        from sbomify.apps.plugins.apis import _result_with_kev

        run = self._run_of(sample_team_with_owner_member, category, count=40)

        result = _result_with_kev(run, frozenset(), frozenset(), findings_limit=1)

        assert len(result["findings"]) == 1
        assert result["summary"]["total_findings"] == 40

    @pytest.mark.parametrize("limit", [-1, -500])
    def test_a_negative_limit_returns_no_findings_rather_than_nearly_all(
        self, sample_team_with_owner_member: Member, limit: int
    ) -> None:
        from sbomify.apps.plugins.apis import _result_with_kev

        run = self._run_of(sample_team_with_owner_member, "security", count=3)

        result = _result_with_kev(run, frozenset(), frozenset(), findings_limit=limit)

        assert result["findings"] == []
