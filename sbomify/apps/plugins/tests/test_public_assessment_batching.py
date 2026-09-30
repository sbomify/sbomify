"""The public component status reads every SBOM's runs in a fixed number of queries."""

import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.public_assessment_utils import (
    ComponentAssessmentStatus,
    PassingAssessment,
    _aggregate_passing,
    _collect_details,
    _get_latest_assessment_runs_for_sbom,
    _get_plugin_display_names,
    _is_run_passing,
    _passing_assessment_from_run,
    get_component_assessment_status,
    get_sbom_passing_assessments,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team

PLUGINS = {
    "ntia-minimum-elements-2021": AssessmentCategory.COMPLIANCE.value,
    "cisa-minimum-elements-2025": AssessmentCategory.COMPLIANCE.value,
    "osv": AssessmentCategory.SECURITY.value,
}

PASSING = {
    "summary": {"total_findings": 7, "pass_count": 6, "warning_count": 1, "fail_count": 0, "error_count": 0},
    "metadata": {
        "standard_name": "Minimum elements",
        "standard_version": "2021",
        "standard_url": "https://example.com",
    },
}
FAILING = {"summary": {"total_findings": 7, "pass_count": 5, "fail_count": 2, "error_count": 0}}
SKIPPED = {"summary": {"total_findings": 0, "fail_count": 0, "error_count": 0}, "metadata": {"skipped": True}}
CLEAN_SCAN = {
    "summary": {"total_findings": 0, "fail_count": 0, "error_count": 0, "by_severity": {"critical": 0, "high": 0}},
    "findings": [],
}
DIRTY_SCAN = {
    "summary": {"total_findings": 1, "fail_count": 0, "error_count": 0, "by_severity": {"critical": 1}},
    "findings": [{"id": "CVE-2024-0001"}],
}


def _reference_component_status(component: Component) -> ComponentAssessmentStatus:
    """The per-SBOM implementation this module replaced, reading every full result."""
    sbom_ids = list(SBOM.objects.filter(component=component).values_list("id", flat=True))
    plugin_info = _get_plugin_display_names()
    sbom_passing: dict[str, set[str]] = {}
    details_by_plugin: dict[str, PassingAssessment] = {}
    for sbom_id in sbom_ids:
        runs = _get_latest_assessment_runs_for_sbom(str(sbom_id))
        passing = [_passing_assessment_from_run(run, plugin_info) for run in runs if _is_run_passing(run)]
        sbom_passing[str(sbom_id)] = {p.plugin_name for p in passing}
        _collect_details(details_by_plugin, passing)
    common = set.intersection(*sbom_passing.values())
    has_assessments = any(sbom_passing.values())
    return ComponentAssessmentStatus(
        component_id=str(component.id),
        component_name=component.name,
        all_pass=len(common) > 0 if has_assessments else False,
        has_assessments=has_assessments,
        passing_assessments=_aggregate_passing(common, details_by_plugin, plugin_info),
    )


@pytest.fixture
def plugins(db):
    for name, category in PLUGINS.items():
        RegisteredPlugin.objects.get_or_create(
            name=name,
            defaults={
                "display_name": name.upper(),
                "category": category,
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                "is_enabled": True,
            },
        )


@pytest.fixture
def component(db, plugins):
    team = Team.objects.create(name="Batch Team", key="batch-team", is_public=True)
    return Component.objects.create(
        name="Batched", team=team, visibility=Component.Visibility.PUBLIC, component_type="bom"
    )


def _run(sbom: SBOM, plugin_name: str, result: dict, minutes_ago: int, status: str = RunStatus.COMPLETED.value):
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        plugin_config_hash="h",
        category=PLUGINS[plugin_name],
        run_reason=RunReason.ON_UPLOAD.value,
        status=status,
        result=result,
        completed_at=timezone.now() - timedelta(minutes=minutes_ago),
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))


def _sbom(component: Component) -> SBOM:
    version = f"1.0.{SBOM.objects.filter(component=component).count()}"
    return SBOM.objects.create(
        name="sbom", version=version, component=component, format="cyclonedx", format_version="1.6"
    )


def _add_sboms(component: Component, count: int) -> list[SBOM]:
    """SBOMs that pass every plugin on their latest run, so the aggregate keeps all of them."""
    sboms = []
    for i in range(count):
        sbom = _sbom(component)
        _run(sbom, "ntia-minimum-elements-2021", FAILING, minutes_ago=100 + i)
        _run(sbom, "ntia-minimum-elements-2021", PASSING, minutes_ago=50 + i)
        _run(sbom, "cisa-minimum-elements-2025", PASSING, minutes_ago=40 + i)
        _run(sbom, "osv", CLEAN_SCAN, minutes_ago=30 + i)
        sboms.append(sbom)
    return sboms


@pytest.mark.django_db
class TestComponentStatusMatchesPerSbomReads:
    def test_mixed_runs_give_the_same_status(self, component):
        first, second, third = _add_sboms(component, 3)
        # Newest run fails: cisa drops out of the aggregate.
        _run(second, "cisa-minimum-elements-2025", FAILING, minutes_ago=1)
        # A skipped scan and a dirty scan count as not passing.
        _run(third, "osv", SKIPPED, minutes_ago=1)
        _run(first, "osv", DIRTY_SCAN, minutes_ago=2)
        _run(first, "osv", CLEAN_SCAN, minutes_ago=1)
        # An SBOM only one plugin has scanned.
        fourth = _sbom(component)
        _run(fourth, "ntia-minimum-elements-2021", PASSING, minutes_ago=200)

        expected = _reference_component_status(component)
        actual = get_component_assessment_status(component)

        assert actual == expected
        assert [p.plugin_name for p in actual.passing_assessments] == ["ntia-minimum-elements-2021"]
        assert actual.passing_assessments[0].standard_name == "Minimum elements"

    def test_all_passing_keeps_every_plugin_and_the_oldest_time(self, component):
        _add_sboms(component, 4)

        expected = _reference_component_status(component)
        actual = get_component_assessment_status(component)

        assert actual == expected
        assert {p.plugin_name for p in actual.passing_assessments} == set(PLUGINS)

    def test_single_sbom_list_matches(self, component):
        (sbom,) = _add_sboms(component, 1)
        _run(sbom, "osv", DIRTY_SCAN, minutes_ago=1)

        plugin_info = _get_plugin_display_names()
        expected = [
            _passing_assessment_from_run(run, plugin_info)
            for run in _get_latest_assessment_runs_for_sbom(str(sbom.id))
            if _is_run_passing(run)
        ]
        assert get_sbom_passing_assessments(str(sbom.id)) == expected
        assert len(expected) == 2


def _count_queries(component: Component) -> tuple[int, list[str]]:
    with CaptureQueriesContext(connection) as ctx:
        get_component_assessment_status(component)
    return len(ctx.captured_queries), [q["sql"] for q in ctx.captured_queries]


@pytest.mark.django_db
class TestComponentStatusQueryCount:
    def test_query_count_does_not_grow_with_sboms(self, component, django_assert_max_num_queries):
        _add_sboms(component, 1)
        one, _ = _count_queries(component)
        _add_sboms(component, 19)

        with django_assert_max_num_queries(one):
            status = get_component_assessment_status(component)
        assert status.all_pass

    def test_full_result_is_never_selected(self, component):
        _add_sboms(component, 2)
        _, sqls = _count_queries(component)

        whole_result = re.compile(rf'"{AssessmentRun._meta.db_table}"\."result"(?!\s*->)')
        assert not [sql for sql in sqls if whole_result.search(sql)]
