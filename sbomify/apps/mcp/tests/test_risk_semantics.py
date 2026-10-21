"""The risk tools' numbers must match what the dashboards report.

These pin the three ways the module could quietly diverge from the UI: a
pending or failed rescan shadowing the last completed result, VEX dispositions
uploaded after a scan being ignored, and severity buckets an agent can read in
the summary but not reach through the list filter.
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.mcp.tools import risk
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

CRITICAL_FINDING = {
    "findings": [
        {
            "id": "CVE-2025-11111",
            "severity": "critical",
            "cvss_score": 9.8,
            "component": {"name": "libexample", "version": "1.0.0", "purl": "pkg:pypi/libexample@1.0.0"},
        }
    ]
}


def _sbom(team, name: str = "risk-sbom") -> SBOM:
    component = Component.objects.create(name=f"{name}-component", team=team)
    return SBOM.objects.create(
        name=name,
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{name}.json",
        component=component,
    )


def _run(sbom: SBOM, *, status: str = "completed", result: dict | None = CRITICAL_FINDING) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status=status,
        result=result if status == "completed" else None,
    )


@pytest.mark.django_db
def test_pending_rescan_does_not_shadow_the_last_completed_result(mcp_owner):
    """A queued or failed rescan must not make an SBOM read as scanned-and-clean.

    The dashboards only consider completed runs; a pending row has no result,
    so letting it win the newest-per-provider pick would report zero findings
    (and the SBOM as scanned) while the UI still shows the last real counts.
    """
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed")
    _run(sbom, status="pending")

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))

    assert scanned == {sbom.id}
    assert risk._counts(rows)["critical"] == 1

    _run(sbom, status="failed")
    rows, _, _ = risk._rows_for(risk._security_runs(bound))
    assert risk._counts(rows)["critical"] == 1


@pytest.mark.django_db
def test_vex_uploaded_after_the_scan_suppresses_the_finding(mcp_owner, monkeypatch):
    """A finding the customer dispositioned via VEX must not be reported live.

    The dashboards resolve VEX statements at read time, so a VEX uploaded
    after the scan already suppresses there; the agent has to agree.
    """
    from sbomify.apps.vulnerability_scanning import vex

    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed")

    monkeypatch.setattr(
        vex,
        "load_vex_suppressions",
        lambda component_id, cache=None: [
            # The shape derive_vex_suppressions produces: ids normalised to
            # lowercase, packages as a set, product_scoped statements matching
            # on id alone.
            {
                "ids": {"cve-2025-11111"},
                "state": "not_affected",
                "justification": "code_not_reachable",
                "source": "vex-import",
                "product_scoped": True,
                "packages": set(),
            }
        ],
    )

    rows, _, _ = risk._rows_for(risk._security_runs(bound))

    assert len(rows) == 1
    assert rows[0]["vex_suppressed"] is True
    assert risk._counts(rows)["total"] == 0


@pytest.mark.django_db
def test_every_summary_bucket_is_reachable_through_the_list_filter(mcp_owner):
    """The name a count appears under is the name the list filter accepts."""
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(
        sbom,
        status="completed",
        result={
            "findings": [
                {"id": "CVE-2025-1", "severity": "info", "component": {"name": "a"}},
                {"id": "CVE-2025-2", "severity": "moderate", "component": {"name": "b"}},
            ]
        },
    )

    rows, _, _ = risk._rows_for(risk._security_runs(bound))
    counts = risk._counts(rows)

    assert counts["info"] == 1
    assert counts["unknown"] == 1
    for row in rows:
        assert risk._severity_bucket(row) in risk.SEVERITIES


def test_severities_mirror_the_shared_rank():
    """SEVERITIES is hand-written to keep imports lazy; hold it to the source."""
    from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK

    assert risk.SEVERITIES == (*SEVERITY_RANK, "unknown")


@pytest.mark.django_db
def test_only_the_latest_sbom_per_component_counts(mcp_owner):
    """Historical SBOM versions must not stack their findings.

    The dashboards count only the newest bom_type=sbom per component; a
    component uploading an SBOM per build would otherwise report the same
    CVE once per upload, and the tool docstring promises dashboard parity.
    """
    from datetime import timedelta

    from django.utils import timezone

    _, bound, _ = mcp_owner
    component = Component.objects.create(name="versioned-component", team=bound)

    def _versioned(version: str) -> SBOM:
        return SBOM.objects.create(
            name="versioned",
            version=version,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"versioned-{version}.json",
            component=component,
        )

    old = _versioned("1.0.0")
    new = _versioned("2.0.0")
    SBOM.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))

    _run(
        old,
        status="completed",
        result={
            "findings": [{"id": "CVE-2024-0001", "severity": "high", "component": {"name": "oldlib", "version": "1"}}]
        },
    )
    _run(new, status="completed")

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))
    counts = risk._counts(rows)

    assert scanned == {new.id}
    assert counts["critical"] == 1
    assert counts["high"] == 0
    assert counts["total"] == 1


@pytest.mark.django_db
def test_a_clean_sbom_never_fetches_its_vex(mcp_owner, monkeypatch):
    """VEX lives in S3, so a workspace of clean components must not pay a round
    trip per component to overlay nothing. The dashboard already skips it."""
    _, bound, _ = mcp_owner
    sbom = _sbom(bound, "clean")
    _run(sbom, status="completed", result={"findings": []})

    calls: list[Any] = []
    monkeypatch.setattr(
        "sbomify.apps.vulnerability_scanning.vex.load_vex_suppressions",
        lambda component_id, cache=None: calls.append(component_id) or [],
    )

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))

    assert scanned == {sbom.id}
    assert rows == []
    assert calls == [], "a clean SBOM triggered a VEX fetch"


@pytest.mark.django_db
def test_a_skipped_run_does_not_count_as_scanned(mcp_owner):
    """A completed run is not proof anyone looked at the SBOM.

    A plugin returns a skipped result when it could not process the artifact at
    all. That stores zero findings, which is indistinguishable on the surface
    from a scan that read every package and found nothing, so counting it makes
    the agent report "no known vulnerabilities" for an SBOM nobody read. The
    dashboards already split the two; this is the same rule.
    """
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed", result={"findings": [], "metadata": {"skipped": True}})

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))

    assert rows == []
    assert scanned == set(), "a skipped run reads as scanned-and-clean"


@pytest.mark.django_db
def test_one_provider_skipping_leaves_the_sbom_scanned(mcp_owner):
    """Only when every provider skipped. One that ran still counts."""
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed", result={"findings": [], "metadata": {"skipped": True}})
    skipped = AssessmentRun.objects.filter(sbom=sbom).first()
    assert skipped is not None
    skipped.plugin_name = "dependency_track"
    skipped.save(update_fields=["plugin_name"])
    _run(sbom, status="completed")

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))

    assert scanned == {sbom.id}
    assert risk._counts(rows)["critical"] == 1


def test_a_finding_with_more_aliases_than_fit_says_it_was_cut():
    """Aliases come from scanner output, so their count is the supplier's to choose.

    Each alias was clipped but the list was not, so one finding could push a
    page of ``list_vulnerabilities`` past the response cap after all the work
    was done. The list is capped at the bound the triage prompt uses.
    """
    from sbomify.apps.mcp.tools.risk import _present
    from sbomify.apps.vulnerability_scanning.services.fix_prompt import MAX_ALIASES

    row = {"id": "CVE-2026-1", "aliases": [f"GHSA-{i:04d}-aaaa-bbbb" for i in range(MAX_ALIASES + 40)]}

    shaped = _present(row)

    assert len(shaped["aliases"]) == MAX_ALIASES
    assert shaped["aliases_truncated"] is True
    assert "aliases_truncated" not in _present({"id": "CVE-2026-1", "aliases": ["GHSA-aaaa-bbbb-cccc"]})


class _Bucket:
    """The result store's bucket, in memory."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_file_data(self, bucket: str, key: str) -> bytes | None:
        return self.objects.get(key)


@pytest.fixture
def result_bucket(monkeypatch) -> _Bucket:
    bucket = _Bucket()
    monkeypatch.setattr("sbomify.apps.plugins.result_store._client", lambda: bucket)
    monkeypatch.setattr("sbomify.apps.plugins.result_store._bucket", lambda: "test-bucket")
    return bucket


def _offload(run: AssessmentRun, bucket: _Bucket, *, keep_object: bool = True) -> None:
    """Move a run's payload to object storage the way the offload sweep does: key and NULL in one UPDATE."""
    from sbomify.apps.plugins.result_store import object_key_for, serialise_result

    payload = serialise_result(run.result)
    key = object_key_for(run.id, payload)
    if keep_object:
        bucket.objects[key] = payload
    AssessmentRun.objects.filter(pk=run.pk).update(result=None, result_object_key=key)


@pytest.mark.django_db
def test_an_offloaded_scan_still_counts_its_findings(mcp_owner, result_bucket):
    """A scan whose payload moved to object storage still found what it found.

    Its ``result`` column is NULL once offloaded, so reading the column instead of
    the result store reported the SBOM as scanned and clean.
    """
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _offload(_run(sbom), result_bucket)

    rows, scanned, unavailable = risk._rows_for(risk._security_runs(bound))

    assert risk._counts(rows)["critical"] == 1
    assert scanned == {sbom.id}
    assert unavailable == set()


@pytest.mark.django_db
def test_a_scan_whose_payload_is_gone_reads_as_unavailable_not_clean(mcp_owner, result_bucket):
    """No findings and "we cannot read what was found" are different answers.

    The scan still ran (its stored skipped flag says so), so the SBOM stays
    scanned; the findings it holds are reported as unavailable rather than as none.
    """
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _offload(_run(sbom), result_bucket, keep_object=False)

    rows, scanned, unavailable = risk._rows_for(risk._security_runs(bound))

    assert rows == []
    assert scanned == {sbom.id}
    assert unavailable == {sbom.id}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_tools_say_when_a_scan_could_not_be_read(mcp_owner, make_token, result_bucket):
    """The agent relays the counts, so they must carry the gap, not hide it."""
    from asgiref.sync import sync_to_async

    from .test_artifact_surface import _call
    from .test_protocol import structured

    _, bound, _ = mcp_owner

    def setup() -> None:
        _offload(_run(_sbom(bound)), result_bucket, keep_object=False)

    await sync_to_async(setup)()
    token = await sync_to_async(make_token)(["workspace:read"])

    summary = structured(await _call(token, "get_vulnerability_summary"))
    listing = structured(await _call(token, "list_vulnerabilities"))

    assert summary["sboms_unavailable"] == 1
    assert listing["sboms_unavailable"] == 1
    assert listing["items"] == []


@pytest.mark.django_db
def test_a_workspace_list_holds_one_sboms_scans_at_a_time(mcp_owner, monkeypatch):
    """Every SBOM in scope is read, but never all of their scans at once."""
    import gc
    import weakref

    from sbomify.apps.plugins import result_store

    _, bound, _ = mcp_owner
    for index in range(12):
        _run(_sbom(bound, f"many-{index}"))

    held: weakref.WeakSet = weakref.WeakSet()
    peaks: list[int] = []
    real = result_store.load_result

    def watching(run):
        held.add(run)
        gc.collect()
        peaks.append(len(held))
        return real(run)

    monkeypatch.setattr(result_store, "load_result", watching)

    rows, scanned, _ = risk._rows_for(risk._security_runs(bound))

    assert len(rows) == 12
    assert len(scanned) == 12
    assert max(peaks) <= 2
