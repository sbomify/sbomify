from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE


@pytest.fixture
def s3(mocker):
    """In-memory S3 stand-in: uploads store bytes, reads return them."""
    store: dict[str, bytes] = {}

    def upload(content: bytes, *args: Any, **kwargs: Any) -> str:
        name = f"vexdoc-{len(store)}.json"
        store[name] = content
        return name

    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_sbom", side_effect=upload)
    mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data", side_effect=lambda name: store.get(name))
    mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object", return_value=None)
    return store


@pytest.fixture
def reapply_stub(mocker):
    return mocker.patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply", return_value=None)


def _cdx_vex(cve: str, purl: str = "pkg:npm/left-pad@1.0.0") -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [{"bom-ref": purl, "type": "library", "name": "left-pad", "version": "1.0.0", "purl": purl}],
        "vulnerabilities": [
            {
                "id": cve,
                "analysis": {"state": "not_affected", "justification": "code_not_present"},
                "affects": [{"ref": purl}],
            }
        ],
    }


def _store_vex(component: Component, s3: dict[str, bytes], source: str, cve: str, name: str) -> SBOM:
    s3[name] = json.dumps(_cdx_vex(cve)).encode()
    return SBOM.objects.create(
        name=component.name,
        component=component,
        format="cyclonedx",
        format_version="1.6",
        source=source,
        sbom_filename=name,
        bom_type=SBOM.BomType.VEX.value,
    )


def _client(user: Any, team: Any) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


@pytest.mark.django_db
class TestVexDocuments:
    def test_lists_uploaded_vex_and_excludes_triage(self, sample_user, sample_team_with_owner_member, s3) -> None:
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="vex-comp", team=team, component_type="bom")
        _store_vex(component, s3, "manual_upload", "CVE-2021-45046", name="u.json")
        # The in-app triage overlay must not appear in the uploaded-documents list.
        _store_vex(component, s3, TRIAGE_SOURCE, "CVE-TRIAGE", name="t.json")

        response = _client(sample_user, team).get(f"/component/{component.id}/vex/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "VEX Documents" in body
        assert "CVE-2021-45046" in body
        assert "Manual upload" in body
        assert "CVE-TRIAGE" not in body

    def test_gated_component_vex_content_not_leaked_to_unauthorized(self, sample_team_with_owner_member, s3) -> None:
        """A GATED component is publicly listable, but the VEX's derived CVE
        ids/states sit behind the same download gate — an unauthorized caller
        must not read them via the listing (which the download path 403s)."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="vex-gated", team=team, component_type="bom", visibility=Component.Visibility.GATED
        )
        _store_vex(component, s3, "manual_upload", "CVE-2021-45046", name="g.json")

        # Anonymous: reaches the public-listing gate but not component downloads.
        response = Client().get(f"/component/{component.id}/vex/")
        assert "CVE-2021-45046" not in response.content.decode()

    def test_empty_state(self, sample_user, sample_team_with_owner_member, s3) -> None:
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="vex-empty", team=team, component_type="bom")
        response = _client(sample_user, team).get(f"/component/{component.id}/vex/")
        assert response.status_code == 200
        assert "No VEX documents uploaded yet" in response.content.decode()

    def test_delete_removes_vex(self, sample_user, sample_team_with_owner_member, s3, reapply_stub) -> None:
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="vex-del", team=team, component_type="bom")
        row = _store_vex(component, s3, "manual_upload", "CVE-1", name="d.json")

        response = _client(sample_user, team).post(
            f"/component/{component.id}/vex/",
            {"_method": "DELETE", "sbom_id": row.id},
        )
        assert response.status_code == 200
        assert not SBOM.objects.filter(id=row.id).exists()
        # Deleting a VEX retracts its suppressions, so a re-annotate is scheduled.
        reapply_stub.assert_called_once()

    def test_unreadable_vex_is_flagged_not_fatal(self, sample_user, sample_team_with_owner_member, s3) -> None:
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="vex-bad", team=team, component_type="bom")
        # A VEX row whose S3 blob is missing must render as "unreadable", not 500.
        SBOM.objects.create(
            name=component.name,
            component=component,
            format="cyclonedx",
            format_version="1.6",
            source="manual_upload",
            sbom_filename="gone.json",
            bom_type=SBOM.BomType.VEX.value,
        )
        response = _client(sample_user, team).get(f"/component/{component.id}/vex/")
        assert response.status_code == 200
        assert "unreadable" in response.content.decode()
