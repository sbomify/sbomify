"""The newest run per (SBOM, plugin), found without reading the run history.

Every page that shows a scan result asks this question, and an SBOM scanned
hourly carries up to 720 runs per plugin inside the 30-day retention window.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from sbomify.apps.plugins.latest import latest_run_ids
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db

OSV = "osv"
DT = "dependency-track"


@pytest.fixture(autouse=True)
def registry() -> None:
    for name in (OSV, DT):
        RegisteredPlugin.objects.update_or_create(
            name=name,
            defaults={
                "display_name": name,
                "category": "security",
                "version": "1.0.0",
                "plugin_class_path": f"tests.{name}",
                "is_enabled": True,
            },
        )


def _run(sbom: SBOM, plugin: str, *, hours_ago: int = 0, status: str = "completed", at=None) -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="0" * 64,
        category="security",
        run_reason="manual",
        status=status,
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=at or timezone.now() - timedelta(hours=hours_ago))
    return run


def _another_sbom(sbom: SBOM) -> SBOM:
    return SBOM.objects.create(
        name="another",
        version="2.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="another.json",
        component=sbom.component,
    )


def test_the_newest_run_of_each_plugin_on_each_sbom(sample_sbom):
    another = _another_sbom(sample_sbom)
    newest = set()
    for sbom in (sample_sbom, another):
        for plugin in (OSV, DT):
            _run(sbom, plugin, hours_ago=3)
            newest.add(_run(sbom, plugin, hours_ago=1).pk)
            _run(sbom, plugin, hours_ago=2)

    found = latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk, another.pk])

    assert len(found) == 4
    assert set(found) == newest


def test_one_sboms_runs_come_in_plugin_name_order(sample_sbom):
    osv = _run(sample_sbom, OSV, hours_ago=2)
    dt = _run(sample_sbom, DT, hours_ago=1)

    assert latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk]) == [dt.pk, osv.pk]


def test_a_shared_timestamp_goes_to_the_higher_id(sample_sbom):
    stamp = timezone.now() - timedelta(hours=1)
    runs = [_run(sample_sbom, OSV, at=stamp) for _ in range(3)]

    assert latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk]) == [max(run.pk for run in runs)]


def test_the_callers_queryset_decides_what_counts(sample_sbom):
    completed = _run(sample_sbom, OSV, hours_ago=2)
    _run(sample_sbom, OSV, hours_ago=1, status="failed")

    assert latest_run_ids(AssessmentRun.objects.filter(status="completed"), [sample_sbom.pk]) == [completed.pk]


def test_sboms_and_plugins_without_runs_contribute_nothing(sample_sbom):
    another = _another_sbom(sample_sbom)
    only = _run(sample_sbom, OSV, hours_ago=1)

    assert latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk, another.pk]) == [only.pk]


def test_the_sboms_can_be_a_queryset(sample_sbom):
    run = _run(sample_sbom, OSV, hours_ago=1)

    sboms = SBOM.objects.filter(component=sample_sbom.component).values("pk")

    assert latest_run_ids(AssessmentRun.objects.all(), sboms) == [run.pk]


def test_a_plugin_removed_from_the_registry_drops_out(sample_sbom):
    """Its old runs describe a check the platform no longer runs."""
    kept = _run(sample_sbom, OSV, hours_ago=1)
    _run(sample_sbom, "retired-plugin", hours_ago=1)

    assert latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk]) == [kept.pk]


def test_the_run_history_is_never_scanned(sample_sbom):
    """DISTINCT ON read every run the SBOMs ever had to keep one per plugin:
    333 ms for 65 SBOMs on a million-run table, where one LIMIT 1 probe per
    pair took 1.4 ms."""
    for hours in range(1, 30):
        _run(sample_sbom, OSV, hours_ago=hours)

    with CaptureQueriesContext(connection) as queries:
        latest_run_ids(AssessmentRun.objects.all(), [sample_sbom.pk])

    assert queries
    assert all("DISTINCT" not in query["sql"] for query in queries)
    assert "LIMIT 1" in queries[-1]["sql"]
