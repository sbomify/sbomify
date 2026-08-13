"""The four auditor-facing CSV exports: inventory, licenses, findings, vulnerabilities.

Everything a row carries — package names, licence ids, vulnerability titles —
originates in uploaded artifacts or scanner output, so the writer must be the
CSV-injection-safe one and unreadable artifacts must surface as explicit rows
rather than silently shrinking the export.
"""

from __future__ import annotations

import json

import pytest

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.services import csv_exports
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "version": 1,
    "components": [
        {
            "type": "library",
            "name": "requests",
            "version": "2.32.3",
            "purl": "pkg:pypi/requests@2.32.3",
            "supplier": {"name": "PSF"},
            "licenses": [{"license": {"id": "Apache-2.0"}}],
        },
        {
            "type": "library",
            "name": "=cmd|calc",
            "version": "1.0",
            "licenses": [{"expression": "MIT"}],
        },
    ],
}

SPDX = {
    "spdxVersion": "SPDX-2.3",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "spdx-doc",
    "packages": [
        {
            "name": "left-pad",
            "versionInfo": "1.3.0",
            "supplier": "Organization: npm",
            "licenseDeclared": "MIT",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE_MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": "pkg:npm/left-pad@1.3.0",
                }
            ],
        }
    ],
}


@pytest.fixture
def inventory(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(name="Prod", team=team)
    c1 = Component.objects.create(name="frontend", team=team)
    c2 = Component.objects.create(name="backend", team=team)
    c1.products.add(product)
    c2.products.add(product)
    s1 = SBOM.objects.create(
        name="frontend",
        version="1.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="f.json",
        component=c1,
    )
    s2 = SBOM.objects.create(
        name="backend",
        version="2.0",
        format="spdx",
        format_version="2.3",
        sbom_filename="b.json",
        component=c2,
    )
    return team, product, {s1.id: CYCLONEDX, s2.id: SPDX}


@pytest.fixture
def stub_sbom_bytes(inventory, monkeypatch):
    _, _, docs = inventory

    def fake(sbom_id):
        sbom = SBOM.objects.get(id=sbom_id)
        return sbom, json.dumps(docs[sbom_id]).encode()

    monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", fake)
    return docs


@pytest.mark.django_db
class TestInventoryCsv:
    def test_packages_across_both_formats(self, inventory, stub_sbom_bytes):
        team, product, _ = inventory
        result = csv_exports.export_inventory_csv(team, product=product)
        assert result.ok
        body = result.value
        assert "requests,2.32.3,PSF,Apache-2.0,pkg:pypi/requests@2.32.3" in body
        assert "left-pad,1.3.0,npm,MIT,pkg:npm/left-pad@1.3.0" in body

    def test_formula_injection_is_neutralised(self, inventory, stub_sbom_bytes):
        team, _, _ = inventory
        import csv as stdlib_csv
        import io

        result = csv_exports.export_inventory_csv(team)
        assert "'=cmd" in result.value
        for record in stdlib_csv.reader(io.StringIO(result.value)):
            for cell in record:
                assert not cell.startswith(("=", "+", "@", "\t"))

    def test_unreadable_sbom_gets_an_explicit_row(self, inventory, monkeypatch):
        team, _, docs = inventory

        def broken(sbom_id):
            raise csv_exports.SBOMDataError("gone")

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", broken)
        result = csv_exports.export_inventory_csv(team)
        assert result.ok
        assert result.value.count("(unreadable artifact)") == 2

    def test_only_latest_sbom_per_component(self, inventory, monkeypatch):
        team, _, docs = inventory
        component = Component.objects.get(name="frontend", team=team)
        newer = SBOM.objects.create(
            name="frontend",
            version="1.1",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="f2.json",
            component=component,
        )
        docs[newer.id] = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}

        def fake(sbom_id):
            return SBOM.objects.get(id=sbom_id), json.dumps(docs[sbom_id]).encode()

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", fake)
        result = csv_exports.export_inventory_csv(team)
        assert "requests" not in result.value


@pytest.mark.django_db
class TestLicensesCsv:
    def test_licences_aggregate_with_counts(self, inventory, stub_sbom_bytes):
        team, product, _ = inventory
        result = csv_exports.export_licenses_csv(team, product=product)
        assert result.ok
        lines = result.value.splitlines()
        assert lines[0] == "License,Packages,Components"
        assert "Apache-2.0,1,1" in lines
        assert "MIT,2,2" in lines


@pytest.mark.django_db
class TestFindingsCsv:
    def test_latest_compliance_run_rows(self, inventory):
        team, _, docs = inventory
        sbom = SBOM.objects.filter(component__team=team).first()
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia",
            plugin_version="1",
            plugin_config_hash="",
            category="compliance",
            run_reason="on_upload",
            status="completed",
            result={
                "findings": [
                    {"id": "ntia:supplier", "title": "Supplier", "status": "fail", "description": "missing"},
                ]
            },
        )
        result = csv_exports.export_findings_csv(sbom)
        assert result.ok
        assert "ntia,ntia:supplier,Supplier,fail,missing" in result.value


@pytest.mark.django_db
class TestVulnerabilitiesCsv:
    def test_rows_carry_analysis_state(self, inventory):
        team, product, docs = inventory
        sbom = SBOM.objects.filter(component__team=team, format="cyclonedx").first()
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1",
            plugin_config_hash="",
            category="security",
            run_reason="on_upload",
            status="completed",
            result={
                "findings": [
                    {
                        "id": "CVE-2025-1",
                        "severity": "high",
                        "cvss_score": 8.1,
                        "component": {"name": "requests", "version": "2.32.3"},
                        "analysis_state": "not_affected",
                    },
                    {
                        "id": "CVE-2025-2",
                        "severity": "critical",
                        "component": {"name": "requests", "version": "2.32.3"},
                    },
                ]
            },
        )
        result = csv_exports.export_vulnerabilities_csv(team, component=sbom.component)
        assert result.ok
        assert "CVE-2025-2,critical" in result.value
        suppressed_line = next(line for line in result.value.splitlines() if line.startswith("CVE-2025-1"))
        assert "not_affected" in suppressed_line

    def test_release_scope_uses_pinned_sboms(self, inventory):
        team, product, docs = inventory
        release = Release.objects.create(product=product, name="v1")
        result = csv_exports.export_vulnerabilities_csv(team, release=release)
        assert result.ok
        assert result.value.splitlines()[0].startswith("Vulnerability")


@pytest.mark.django_db
class TestEndpoints:
    def test_inventory_endpoint_returns_csv(self, authenticated_api_client, inventory, stub_sbom_bytes):
        client, token = authenticated_api_client
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        team, _, _ = inventory
        response = client.get("/api/v1/exports/inventory.csv", **get_api_headers(token))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment" in response["Content-Disposition"]

    def test_another_user_sees_none_of_this_workspaces_data(self, inventory, stub_sbom_bytes, guest_user, client):
        """Signup gives every user their own workspace, so the export succeeds —
        against their workspace, never this one."""
        client.force_login(guest_user)
        response = client.get("/api/v1/exports/inventory.csv")
        if response.status_code == 200:
            body = response.content.decode()
            assert "requests" not in body
            assert "frontend" not in body
        else:
            assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestNoticeReport:
    def test_text_notice_groups_and_flags_unknown(self, inventory, stub_sbom_bytes):
        team, product, docs = inventory
        result = csv_exports.export_notice_text(team, product=product)
        assert result.ok
        body = result.value
        assert "Third-Party Notices" in body
        assert "requests 2.32.3" in body
        assert "Apache-2.0" in body
        # the =cmd|calc package has a licence (MIT); nothing lands in unknown here
        assert "left-pad 1.3.0" in body

    def test_packages_without_licence_land_in_unknown_section(self, inventory, monkeypatch):
        team, _, docs = inventory
        bare = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "library", "name": "mystery", "version": "0.1"}],
        }

        def fake(sbom_id):
            return SBOM.objects.get(id=sbom_id), json.dumps(bare).encode()

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", fake)
        result = csv_exports.export_notice_text(team)
        assert "Components without license data" in result.value
        assert "mystery 0.1" in result.value

    def test_html_notice_escapes_supplier_controlled_strings(self, inventory, monkeypatch):
        team, _, docs = inventory
        hostile = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [
                {
                    "type": "library",
                    "name": "<script>alert(1)</script>",
                    "version": "1.0",
                    "licenses": [{"expression": "MIT"}],
                    "copyright": "(c) <b>Evil</b>",
                }
            ],
        }

        def fake(sbom_id):
            return SBOM.objects.get(id=sbom_id), json.dumps(hostile).encode()

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", fake)
        result = csv_exports.export_notice_html(team)
        assert result.ok
        assert "<script>alert(1)</script>" not in result.value
        assert "&lt;script&gt;" in result.value

    def test_release_aggregate_covers_pinned_sboms(self, inventory, stub_sbom_bytes):
        team, product, docs = inventory
        from sbomify.apps.core.models import ReleaseArtifact

        release = Release.objects.create(product=product, name="v1")
        for sbom in SBOM.objects.filter(component__team=team):
            ReleaseArtifact.objects.create(release=release, sbom=sbom)
        result = csv_exports.export_notice_text(team, release=release)
        assert "requests 2.32.3" in result.value
        assert "left-pad 1.3.0" in result.value

    def test_notice_endpoint_serves_both_formats(self, authenticated_api_client, inventory, stub_sbom_bytes):
        client, token = authenticated_api_client
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        text = client.get("/api/v1/exports/notice?format=text", **get_api_headers(token))
        assert text.status_code == 200
        assert text["Content-Type"].startswith("text/plain")
        html = client.get("/api/v1/exports/notice?format=html", **get_api_headers(token))
        assert html.status_code == 200
        assert html["Content-Type"].startswith("text/html")


@pytest.mark.django_db
class TestUnreadableSurfacing:
    def test_licenses_csv_counts_unreadable_artifacts(self, inventory, monkeypatch):
        team, _, _ = inventory

        def broken(sbom_id):
            raise csv_exports.SBOMDataError("gone")

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", broken)
        result = csv_exports.export_licenses_csv(team)
        assert "(unreadable artifact)" in result.value

    def test_notice_lists_unreadable_artifacts(self, inventory, monkeypatch):
        team, _, _ = inventory

        def broken(sbom_id):
            raise csv_exports.SBOMDataError("gone")

        monkeypatch.setattr(csv_exports, "get_sbom_data_bytes", broken)
        result = csv_exports.export_notice_text(team)
        assert "Artifacts that could not be read" in result.value

    def test_unknown_notice_format_is_rejected(self, authenticated_api_client, inventory, stub_sbom_bytes):
        client, token = authenticated_api_client
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        response = client.get("/api/v1/exports/notice?format=pdf", **get_api_headers(token))
        assert response.status_code == 400
