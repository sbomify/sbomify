"""Editing a document's metadata tells the workspace, so open document tables repaint.

The documents table listens for ``document_updated``; every edit path (the API
and the table's own edit form) runs through ``update_document_metadata``, which
sends it once the edit commits.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

BROADCAST = "sbomify.apps.documents.services.documents.broadcast_to_workspace"


@pytest.fixture
def document(sample_team: Any, sample_user: Any) -> Document:  # noqa: F811
    Member.objects.get_or_create(user=sample_user, team=sample_team, defaults={"role": "owner"})
    component = Component.objects.create(name="Docs", team=sample_team, component_type=Component.ComponentType.DOCUMENT)
    return Document.objects.create(name="Policy", version="1.0", document_filename="p.pdf", component=component)


def _assert_document_updated(mock_broadcast: Any, document: Document, name: str) -> None:
    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args.kwargs["workspace_key"] == document.component.team.key
    assert mock_broadcast.call_args.kwargs["message_type"] == "document_updated"
    assert mock_broadcast.call_args.kwargs["data"] == {
        "document_id": str(document.id),
        "component_id": str(document.component_id),
        "name": name,
    }


def test_editing_a_document_through_the_api_broadcasts_it(
    client: Client, sample_user: Any, document: Document, django_capture_on_commit_callbacks: Any
) -> None:
    client.force_login(sample_user)

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": document.id}),
            json.dumps({"name": "Renamed policy"}),
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    _assert_document_updated(mock_broadcast, document, "Renamed policy")


def test_an_edit_that_changes_nothing_broadcasts_nothing(
    client: Client, sample_user: Any, document: Document, django_capture_on_commit_callbacks: Any
) -> None:
    client.force_login(sample_user)

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": document.id}),
            json.dumps({}),
            content_type="application/json",
        )

    assert response.status_code == 200
    mock_broadcast.assert_not_called()


def test_a_rejected_edit_broadcasts_nothing(
    client: Client, sample_user: Any, document: Document, django_capture_on_commit_callbacks: Any
) -> None:
    Document.objects.create(name="Taken", version="1.0", document_filename="t.pdf", component=document.component)
    client.force_login(sample_user)

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": document.id}),
            json.dumps({"name": "Taken"}),
            content_type="application/json",
        )

    assert response.status_code == 409
    mock_broadcast.assert_not_called()


def test_editing_a_document_from_the_table_broadcasts_it(
    authenticated_web_client: Client,
    sample_user: Any,
    document: Document,
    django_capture_on_commit_callbacks: Any,
) -> None:
    setup_authenticated_client_session(authenticated_web_client, document.component.team, sample_user)

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        response = authenticated_web_client.post(
            reverse("documents:documents_table", kwargs={"component_id": document.component_id}),
            {
                "_method": "PATCH",
                "document_id": document.id,
                "name": "Edited in table",
                "version": "1.0",
                "document_type": "manual",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200, response.content
    _assert_document_updated(mock_broadcast, document, "Edited in table")


def test_the_documents_table_repaints_on_document_updated_and_resync(
    authenticated_web_client: Client, sample_user: Any, document: Document
) -> None:
    setup_authenticated_client_session(authenticated_web_client, document.component.team, sample_user)

    response = authenticated_web_client.get(
        reverse("documents:documents_table", kwargs={"component_id": document.component_id}),
        HTTP_HX_REQUEST="true",
    )

    html = response.content.decode()
    assert "'document_updated'" in html
    assert "$event.detail.type === 'resync'" in html
