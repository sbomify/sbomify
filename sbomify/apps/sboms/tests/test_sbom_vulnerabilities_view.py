"""Flat report rows merge matching advisories without conflating package namespaces."""

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


def _rows(response) -> list[dict]:
    return response.context["scan_panel"]["rows"]


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

    packages = _rows(response)
    assert len(packages) == 2
    names = sorted(p["package"] for p in packages)
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

    packages = _rows(response)
    assert len(packages) == 1
    assert packages[0]["id"] == "GHSA-1"  # same advisory folded, not duplicated


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
    assert len(_rows(response)) == 3


@pytest.mark.django_db
def test_one_package_under_two_ecosystem_spellings_is_one_row(sample_sbom: SBOM):
    """OSV says "Go" where a purl says golang. Two spellings of one package must
    not read as two packages carrying the same advisory."""
    _run(
        sample_sbom,
        "osv",
        [
            {
                "id": "GHSA-x",
                "aliases": ["CVE-1"],
                "severity": "high",
                "component": {"name": "golang.org/x/net", "version": "0.1.0", "ecosystem": "Go"},
            }
        ],
    )
    _run(
        sample_sbom,
        "dependency-track",
        [
            {
                "id": "CVE-1",
                "severity": "high",
                "component": {
                    "name": "golang.org/x/net",
                    "version": "0.1.0",
                    "ecosystem": "golang",
                    "purl": "pkg:golang/golang.org/x/net@0.1.0",
                },
            }
        ],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert [row["id"] for row in _rows(response)] == ["CVE-1"]


@pytest.mark.django_db
def test_a_row_keeps_the_ecosystem_spelling_its_scanner_used(sample_sbom: SBOM):
    """The newest scanner opens the package. Rows from the other still read as that scanner wrote them."""
    _run(
        sample_sbom,
        "osv",
        [
            {
                "id": "DEBIAN-CVE-1",
                "severity": "high",
                "component": {"name": "glibc", "version": "2.40", "ecosystem": "Debian"},
            }
        ],
    )
    _run(
        sample_sbom,
        "dependency-track",
        [
            {
                "id": "CVE-2",
                "severity": "high",
                "component": {
                    "name": "glibc",
                    "version": "2.40",
                    "ecosystem": "deb",
                    "purl": "pkg:deb/debian/glibc@2.40",
                },
            }
        ],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert {row["id"]: row["ecosystem"] for row in _rows(response)} == {"DEBIAN-CVE-1": "Debian", "CVE-2": "deb"}


@pytest.mark.django_db
def test_the_report_counts_what_the_sbom_card_counts(sample_sbom: SBOM):
    """One advisory on glibc 2.40 reported for a CPE-only, a deb and a generic
    component is three vulnerabilities on the report and on the card alike."""
    from sbomify.apps.vulnerability_scanning.utils import merge_findings_by_alias

    component = {"name": "glibc", "version": "2.40"}
    advisory = {"id": "CVE-2019-1010025", "severity": "low"}
    run = _run(
        sample_sbom,
        "dependency-track",
        [
            {**advisory, "component": {**component, "ecosystem": "unknown"}},
            {**advisory, "component": {**component, "ecosystem": "deb", "purl": "pkg:deb/debian/glibc@2.40"}},
            {**advisory, "component": {**component, "ecosystem": "generic", "purl": "pkg:generic/glibc@2.40"}},
        ],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert len(_rows(response)) == len(merge_findings_by_alias([run.result])["findings"]) == 3


@pytest.mark.django_db
def test_a_finding_that_ties_two_advisories_together_makes_them_one_row(sample_sbom: SBOM):
    """A third report naming both ids joins the two earlier ones, on the report as on the card."""
    from sbomify.apps.vulnerability_scanning.utils import merge_findings_by_alias

    component = {"name": "lodash", "version": "4.17.15", "ecosystem": "npm"}
    osv = _run(
        sample_sbom,
        "osv",
        [
            {"id": "GHSA-x", "severity": "high", "cvss_score": 7.0, "component": component},
            {
                "id": "OSV-9",
                "aliases": ["CVE-1", "GHSA-x"],
                "severity": "critical",
                "cvss_score": 9.1,
                "component": component,
            },
        ],
    )
    dt = _run(
        sample_sbom,
        "dependency-track",
        [{"id": "CVE-1", "severity": "medium", "cvss_score": 5.0, "component": component}],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    rows = _rows(response)
    assert len(rows) == len(merge_findings_by_alias([dt.result, osv.result])["findings"]) == 1
    assert rows[0]["id"] == "CVE-1"
    assert set(rows[0]["aliases"]) == {"GHSA-x", "OSV-9"}
    assert (rows[0]["severity"], rows[0]["cvss_score"]) == ("critical", 9.1)


@pytest.mark.django_db
def test_a_bare_string_alias_does_not_fold_unrelated_advisories(sample_sbom: SBOM):
    """Older stored results hold an alias as a bare string. Read as a list of
    characters, "CVE-2026-1" and "CVE-2026-2" share a "C" and read as one advisory."""
    component = {"name": "lodash", "version": "4.17.15", "ecosystem": "npm"}
    _run(
        sample_sbom,
        "osv",
        [
            {"id": "GHSA-a", "aliases": "CVE-2026-1", "severity": "high", "component": component},
            {"id": "GHSA-b", "aliases": "CVE-2026-2", "severity": "high", "component": component},
        ],
    )
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert sorted(row["id"] for row in _rows(response)) == ["GHSA-a", "GHSA-b"]


@pytest.mark.django_db
def test_scanner_status_markers_are_not_vulnerability_rows(sample_sbom: SBOM):  # noqa: F811
    """A skipped Dependency Track run reports its state through the findings
    array (dependency-track:no-product). That marker is for the error panel,
    not the package table — it must not surface as an "Unknown" package with
    one vulnerability."""
    _run(
        sample_sbom,
        "dependency-track",
        [
            {
                "id": "dependency-track:no-product",
                "severity": "info",
                "status": "info",
                "component": {},
            }
        ],
    )
    _run(sample_sbom, "osv", [_finding("CVE-2025-1111", "django", purl="pkg:pypi/django@5.2.3")])

    client = Client()
    setup_test_session(client, sample_sbom.component.team, sample_sbom.component.team.members.first())
    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))
    assert response.status_code == 200

    packages = _rows(response)
    names = [p["package"] for p in packages]
    assert "django" in names
    assert len(packages) == 1


@pytest.mark.django_db
def test_the_advisory_body_reaches_the_page_as_prose(sample_sbom: SBOM):  # noqa: F811
    """OSV serves GHSA's CommonMark verbatim, and the card showed it raw: the
    page carried the literal text "### Impact" and backticked package names."""
    finding = _finding("GHSA-5jgf-p345-68v8", "fast-uri", version="3.1.5")
    finding["description"] = (
        "### Impact\n`fast-uri` decodes percent-encoded characters in the scheme "
        "component with the legacy global `unescape()` and serializes the result back."
    )
    _run(sample_sbom, "osv", [finding])
    client = Client()
    team = sample_sbom.component.team
    setup_test_session(client, team, team.members.first())

    response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    # Asserted before the strings below, so a redirect or an error page cannot
    # pass this test by simply not containing the markup it is looking for.
    assert response.status_code == 200
    html = response.content.decode()
    assert "### Impact" not in html
    assert "`fast-uri`" not in html
    assert "Impact fast-uri decodes percent-encoded characters" in html
