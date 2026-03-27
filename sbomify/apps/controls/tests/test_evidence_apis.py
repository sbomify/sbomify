from __future__ import annotations

import json

import pytest

from sbomify.apps.controls.models import ControlEvidence
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


@pytest.mark.django_db
class TestEvidence:
    """Test evidence CRUD endpoints."""

    def test_list_evidence_empty(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.get(f"/api/v1/controls/controls/{control.id}/evidence/", **headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_add_url_evidence(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps(
                {
                    "evidence_type": "url",
                    "title": "Security audit report",
                    "url": "https://example.com/audit.pdf",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["evidence_type"] == "url"
        assert data["title"] == "Security audit report"
        assert data["url"] == "https://example.com/audit.pdf"
        assert data["id"]

    def test_add_note_evidence(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps(
                {
                    "evidence_type": "note",
                    "title": "Manual review note",
                    "description": "Reviewed and approved by security team.",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["evidence_type"] == "note"
        assert data["description"] == "Reviewed and approved by security team."

    def test_add_document_evidence(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps(
                {
                    "evidence_type": "document",
                    "title": "SOC 2 report",
                    "document_id": "doc123abc",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["evidence_type"] == "document"
        assert data["document_id"] == "doc123abc"

    def test_add_evidence_invalid_type(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        response = client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps(
                {
                    "evidence_type": "invalid",
                    "title": "Bad type",
                }
            ),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400

    def test_list_evidence_returns_created(
        self, authenticated_api_client, sample_team_with_owner_member, sample_controls
    ):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        # Create two evidence items
        client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps({"evidence_type": "url", "title": "Link 1", "url": "https://example.com/1"}),
            content_type="application/json",
            **headers,
        )
        client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps({"evidence_type": "note", "title": "Note 1", "description": "A note"}),
            content_type="application/json",
            **headers,
        )

        response = client.get(f"/api/v1/controls/controls/{control.id}/evidence/", **headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_delete_evidence(self, authenticated_api_client, sample_team_with_owner_member, sample_controls):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        control = sample_controls[0]

        # Create evidence
        create_response = client.post(
            f"/api/v1/controls/controls/{control.id}/evidence/",
            data=json.dumps({"evidence_type": "note", "title": "To delete", "description": "temp"}),
            content_type="application/json",
            **headers,
        )
        evidence_id = create_response.json()["id"]

        # Delete it
        response = client.delete(f"/api/v1/controls/evidence/{evidence_id}/", **headers)

        assert response.status_code == 204
        assert not ControlEvidence.objects.filter(id=evidence_id).exists()

    def test_delete_nonexistent_evidence(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.delete("/api/v1/controls/evidence/nonexistent123/", **headers)

        assert response.status_code == 404

    def test_add_evidence_control_not_found(self, authenticated_api_client, sample_team_with_owner_member):
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.post(
            "/api/v1/controls/controls/nonexistent123/evidence/",
            data=json.dumps({"evidence_type": "url", "title": "Test", "url": "https://example.com"}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 404
