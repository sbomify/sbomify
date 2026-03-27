from __future__ import annotations

import json

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog, ControlMapping
from sbomify.apps.controls.services.mapping_service import create_mapping
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


@pytest.fixture
def second_catalog(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return ControlCatalog.objects.create(
        team=team, name="ISO 27001", version="2022", source=ControlCatalog.Source.BUILTIN
    )


@pytest.fixture
def iso_controls(second_catalog):
    controls = []
    for i, (cid, title, group) in enumerate(
        [
            ("A.8.1", "Asset management", "Asset Management"),
            ("A.9.1", "Access control policy", "Access Control"),
        ]
    ):
        controls.append(
            Control.objects.create(catalog=second_catalog, group=group, control_id=cid, title=title, sort_order=i)
        )
    return controls


@pytest.mark.django_db
class TestListControlMappings:
    def test_list_mappings_for_control(
        self, authenticated_api_client, sample_team_with_owner_member, sample_controls, iso_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        create_mapping(sample_controls[0], iso_controls[0], "equivalent")

        response = client.get(
            f"/api/v1/controls/controls/{sample_controls[0].id}/mappings/",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source_control_label"] == "CC6.1"
        assert data[0]["target_control_label"] == "A.8.1"
        assert data[0]["relation_type"] == "equivalent"

    def test_list_mappings_empty(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get(
            f"/api/v1/controls/controls/{sample_controls[0].id}/mappings/",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_list_mappings_nonexistent_control(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get(
            "/api/v1/controls/controls/nonexistent123/mappings/",
            **headers,
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestCreateControlMapping:
    def test_create_mapping(
        self, authenticated_api_client, sample_team_with_owner_member, sample_controls, iso_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/mappings/",
            data=json.dumps(
                {
                    "source_control_id": sample_controls[0].id,
                    "target_control_id": iso_controls[0].id,
                    "relation_type": "equivalent",
                    "notes": "Direct mapping",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["source_control_label"] == "CC6.1"
        assert data["target_control_label"] == "A.8.1"
        assert data["source_catalog_name"] == "SOC 2 Type II"
        assert data["target_catalog_name"] == "ISO 27001"
        assert data["relation_type"] == "equivalent"
        assert data["notes"] == "Direct mapping"
        assert ControlMapping.objects.count() == 1

    def test_create_mapping_source_not_found(
        self, authenticated_api_client, sample_team_with_owner_member, iso_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/mappings/",
            data=json.dumps(
                {
                    "source_control_id": "nonexistent",
                    "target_control_id": iso_controls[0].id,
                    "relation_type": "equivalent",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 404

    def test_create_mapping_duplicate_returns_409(
        self, authenticated_api_client, sample_team_with_owner_member, sample_controls, iso_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        create_mapping(sample_controls[0], iso_controls[0], "equivalent")

        response = client.post(
            "/api/v1/controls/mappings/",
            data=json.dumps(
                {
                    "source_control_id": sample_controls[0].id,
                    "target_control_id": iso_controls[0].id,
                    "relation_type": "partial",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409


@pytest.mark.django_db
class TestBulkImportMappings:
    def test_bulk_import(self, authenticated_api_client, sample_team_with_owner_member, sample_controls, iso_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/mappings/bulk/",
            data=json.dumps(
                {
                    "items": [
                        {
                            "source_control_id": sample_controls[0].id,
                            "target_control_id": iso_controls[0].id,
                            "relation_type": "equivalent",
                        },
                        {
                            "source_control_id": sample_controls[1].id,
                            "target_control_id": iso_controls[1].id,
                            "relation_type": "partial",
                            "notes": "Overlapping scope",
                        },
                    ]
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 2
        assert ControlMapping.objects.count() == 2

    def test_bulk_import_empty_returns_400(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/mappings/bulk/",
            data=json.dumps({"items": []}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
