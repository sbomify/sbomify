"""Package grouping on the full scan report: cross-provider rows merge on the
artifact tail, while distinct purl namespaces sharing an artifact name stay
separate."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason

from ..models import SBOM
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session


def _run(sbom: SBOM, plugin: str, findings: list[dict]) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0",
        plugin_config_hash="x",
        category="security",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={"findings": findings},
    )


def _finding(advisory: str, name: str, version: str = "1.0", purl: str = "") -> dict:
    component = {"name": name, "version": version, "ecosystem": "maven"}
    if purl:
        component["purl"] = purl
    return {"id": advisory, "severity": "high", "component": component}


def _packages(response) -> list[dict]:
    return response.context["vulnerabilities"]["results"][0]["packages"]


@pytest.mark.django_db
def test_distinct_purl_namespaces_do_not_merge(sample_sbom: SBOM):  # noqa: F811
    """Two Maven groupIds sharing an artifact name and version stay separate rows."""
    _run(
        sample_sbom,
        "osv",
        [
            _finding("CVE-1", "com.foo:shared-artifact", purl="pkg:maven/com.foo/shared-artifact@1.0"),
            _finding("CVE-2", "com.bar:shared-artifact", purl="pkg:maven/com.bar/shared-artifact@1.0"),
        ],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    packages = _packages(response)
    assert len(packages) == 2
    names = sorted(p["package"]["name"] for p in packages)
    assert names == ["com.bar:shared-artifact", "com.foo:shared-artifact"]


@pytest.mark.django_db
def test_purl_less_provider_row_merges_with_single_namespace(sample_sbom: SBOM):  # noqa: F811
    """A purl-less provider row joins the tail's only purl-carrying group, so
    cross-provider merging keeps working (OSV group:artifact vs DT artifact)."""
    _run(
        sample_sbom,
        "osv",
        [_finding("GHSA-1", "com.foo:merge-me", purl="pkg:maven/com.foo/merge-me@1.0")],
    )
    _run(sample_sbom, "dependency-track", [_finding("GHSA-1", "merge-me")])
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    packages = _packages(response)
    assert len(packages) == 1
    assert len(packages[0]["vulnerabilities"]) == 1  # same advisory folded, not duplicated


@pytest.mark.django_db
def test_purl_less_row_stays_separate_when_namespaces_are_ambiguous(sample_sbom: SBOM):  # noqa: F811
    _run(
        sample_sbom,
        "osv",
        [
            _finding("CVE-1", "com.foo:ambig", purl="pkg:maven/com.foo/ambig@1.0"),
            _finding("CVE-2", "com.bar:ambig", purl="pkg:maven/com.bar/ambig@1.0"),
        ],
    )
    _run(sample_sbom, "dependency-track", [_finding("CVE-3", "ambig")])
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    # Two namespaces plus one unattributable purl-less row: never guess.
    assert len(_packages(response)) == 3
