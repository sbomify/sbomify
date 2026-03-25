from __future__ import annotations

import json

import pytest

from sbomify.apps.controls.models import ControlCatalog, ControlStatus
from sbomify.apps.controls.services.catalog_service import activate_builtin_catalog
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


@pytest.mark.django_db
class TestCatalogActivation:
    """Test catalog activation API endpoint."""

    def test_activate_catalog_returns_201(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/catalogs/activate/",
            data=json.dumps({"catalog_name": "soc2-type2"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "SOC 2 Type II"
        assert data["source"] == "builtin"
        assert data["is_active"] is True

    def test_duplicate_activation_returns_existing(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        r1 = client.post(
            "/api/v1/controls/catalogs/activate/",
            data=json.dumps({"catalog_name": "soc2-type2"}),
            content_type="application/json",
            **headers,
        )
        r2 = client.post(
            "/api/v1/controls/catalogs/activate/",
            data=json.dumps({"catalog_name": "soc2-type2"}),
            content_type="application/json",
            **headers,
        )

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

    def test_activate_unknown_catalog_returns_404(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/catalogs/activate/",
            data=json.dumps({"catalog_name": "nonexistent"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestListCatalogs:
    """Test catalog listing API endpoint."""

    def test_list_catalogs(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        team = sample_team_with_owner_member.team

        activate_builtin_catalog(team, "soc2-type2")

        response = client.get("/api/v1/controls/catalogs/", **headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "SOC 2 Type II"

    def test_list_catalogs_empty(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get("/api/v1/controls/catalogs/", **headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


@pytest.mark.django_db
class TestCatalogDetail:
    """Test catalog detail API endpoint."""

    def test_get_catalog_detail(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        team = sample_team_with_owner_member.team

        result = activate_builtin_catalog(team, "soc2-type2")
        assert result.ok
        catalog = result.value

        response = client.get(f"/api/v1/controls/catalogs/{catalog.id}/", **headers)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "SOC 2 Type II"
        assert data["controls_count"] > 0

    def test_get_nonexistent_catalog(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get("/api/v1/controls/catalogs/nonexistent123/", **headers)

        assert response.status_code == 404


@pytest.mark.django_db
class TestCatalogUpdate:
    """Test catalog PATCH (toggle is_active) endpoint."""

    def test_toggle_catalog_active(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        team = sample_team_with_owner_member.team

        result = activate_builtin_catalog(team, "soc2-type2")
        assert result.ok
        catalog = result.value

        response = client.patch(
            f"/api/v1/controls/catalogs/{catalog.id}/",
            data=json.dumps({"is_active": False}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False


@pytest.mark.django_db
class TestCatalogDelete:
    """Test catalog deletion endpoint."""

    def test_delete_catalog(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        team = sample_team_with_owner_member.team

        result = activate_builtin_catalog(team, "soc2-type2")
        assert result.ok
        catalog = result.value

        response = client.delete(f"/api/v1/controls/catalogs/{catalog.id}/", **headers)

        assert response.status_code == 204
        assert not ControlCatalog.objects.filter(id=catalog.id).exists()


@pytest.mark.django_db
class TestStatusUpsert:
    """Test control status upsert endpoint."""

    def test_upsert_status(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.put(
            f"/api/v1/controls/controls/{control.id}/status/",
            data=json.dumps({"status": "compliant", "notes": "All good"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compliant"
        assert data["notes"] == "All good"

    def test_upsert_status_invalid(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.put(
            f"/api/v1/controls/controls/{control.id}/status/",
            data=json.dumps({"status": "invalid_status"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400

    def test_upsert_status_updates_existing(
        self, authenticated_api_client, sample_team_with_owner_member, sample_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        # First upsert
        client.put(
            f"/api/v1/controls/controls/{control.id}/status/",
            data=json.dumps({"status": "partial"}),
            content_type="application/json",
            **headers,
        )

        # Second upsert to update
        response = client.put(
            f"/api/v1/controls/controls/{control.id}/status/",
            data=json.dumps({"status": "compliant", "notes": "Now fully compliant"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compliant"
        assert data["notes"] == "Now fully compliant"

        # Only one status record should exist
        assert ControlStatus.objects.filter(control=control, product__isnull=True).count() == 1


@pytest.mark.django_db
class TestBulkUpdate:
    """Test bulk status update endpoint."""

    def test_bulk_update(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        items = [
            {"control_id": sample_controls[0].id, "status": "compliant"},
            {"control_id": sample_controls[1].id, "status": "partial", "notes": "In progress"},
        ]

        response = client.post(
            "/api/v1/controls/status/bulk/",
            data=json.dumps({"items": items}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 2

    def test_bulk_update_invalid_status(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        items = [
            {"control_id": sample_controls[0].id, "status": "invalid_status"},
        ]

        response = client.post(
            "/api/v1/controls/status/bulk/",
            data=json.dumps({"items": items}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestListControls:
    """Test controls listing endpoint."""

    def test_list_controls_with_statuses(
        self, authenticated_api_client, sample_team_with_owner_member, sample_catalog, sample_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get(f"/api/v1/controls/catalogs/{sample_catalog.id}/controls/", **headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["control_id"] == "CC6.1"


@pytest.mark.django_db
class TestPublicSummary:
    """Test public controls summary endpoint (no auth required)."""

    def test_public_summary(self, sample_team_with_owner_member):
        from django.test import Client

        team = sample_team_with_owner_member.team
        activate_builtin_catalog(team, "soc2-type2")

        client = Client()
        response = client.get(f"/api/v1/controls/public/{team.key}/")

        assert response.status_code == 200
        data = response.json()
        assert data["catalog_name"] == "SOC 2 Type II"
        assert data["total"] > 0
        assert "by_status" in data
        assert "categories" in data
        assert response["Cache-Control"] == "public, max-age=3600"

    def test_public_summary_no_catalog(self, sample_team_with_owner_member):
        from django.test import Client

        team = sample_team_with_owner_member.team

        client = Client()
        response = client.get(f"/api/v1/controls/public/{team.key}/")

        assert response.status_code == 404

    def test_public_summary_invalid_workspace(self):
        from django.test import Client

        client = Client()
        response = client.get("/api/v1/controls/public/invalid_key/")

        assert response.status_code == 404
