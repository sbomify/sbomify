"""Tests for the document uniqueness constraint.

A document is identified by (component, name, version), so re-uploading the same
name at the same version is a duplicate. Different documents may share a version,
and the same name/version may exist under a different component.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.s3_fixtures import create_documents_api_mock
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.utils import is_duplicate_document_error
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401
from sbomify.apps.teams.models import Member


@pytest.fixture
def sample_document_component(sample_team, sample_user):  # noqa: F811
    """A document component owned by the sample user."""
    Member.objects.get_or_create(user=sample_user, team=sample_team, defaults={"role": "owner"})

    return Component.objects.create(
        name="Uniqueness Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=Component.Visibility.PRIVATE,
    )


@pytest.fixture
def other_document_component(sample_team, sample_user):  # noqa: F811
    """A second document component in the same workspace."""
    Member.objects.get_or_create(user=sample_user, team=sample_team, defaults={"role": "owner"})

    return Component.objects.create(
        name="Other Uniqueness Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=Component.Visibility.PRIVATE,
    )


def _make_document(component, name: str = "foobar", version: str = "1.0") -> Document:
    return Document.objects.create(
        name=name,
        version=version,
        document_filename=f"{name}-{version}.bin",
        component=component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
    )


def _upload(client: Client, component_id: str, filename: str = "foobar.pdf", version: str = "1.0"):
    return client.post(
        reverse("api-1:create_document"),
        {
            "document_file": SimpleUploadedFile(filename, b"document content", content_type="application/pdf"),
            "component_id": component_id,
            "version": version,
        },
        format="multipart",
    )


@pytest.mark.django_db
class TestDocumentUniquenessConstraint:
    """The database constraint itself."""

    def test_same_name_and_version_is_rejected(self, sample_document_component):
        _make_document(sample_document_component)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _make_document(sample_document_component)

    def test_same_version_different_name_is_allowed(self, sample_document_component):
        _make_document(sample_document_component, name="readme")
        _make_document(sample_document_component, name="license")

        assert Document.objects.filter(component=sample_document_component, version="1.0").count() == 2

    def test_same_name_different_version_is_allowed(self, sample_document_component):
        _make_document(sample_document_component, version="1.0")
        _make_document(sample_document_component, version="2.0")

        assert Document.objects.filter(component=sample_document_component, name="foobar").count() == 2

    def test_same_name_and_version_in_another_component_is_allowed(
        self, sample_document_component, other_document_component
    ):
        _make_document(sample_document_component)
        _make_document(other_document_component)

        assert Document.objects.filter(name="foobar", version="1.0").count() == 2


@pytest.mark.django_db
class TestDocumentUploadDuplicates:
    """The upload API turns a duplicate into a 409 rather than a second row."""

    def test_duplicate_file_upload_returns_409(
        self,
        mocker: MockerFixture,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        create_documents_api_mock(mocker, scenario="success")
        client.force_login(sample_user)

        first = _upload(client, sample_document_component.id)
        assert first.status_code == 201

        second = _upload(client, sample_document_component.id)
        assert second.status_code == 409

        data = json.loads(second.content)
        assert "already exists" in data["detail"]
        assert "foobar" in data["detail"]
        assert "1.0" in data["detail"]
        assert data["error_code"] == "DUPLICATE_ARTIFACT"

        assert Document.objects.filter(component=sample_document_component).count() == 1

    def test_duplicate_raw_upload_returns_409(
        self,
        mocker: MockerFixture,
        authenticated_api_client,
        sample_document_component,
    ):
        create_documents_api_mock(mocker, scenario="success")
        api_client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        url = reverse("api-1:create_document") + (
            f"?component_id={sample_document_component.id}&name=API Document&version=2.0"
        )

        first = api_client.post(url, b"document content", content_type="application/octet-stream", **headers)
        assert first.status_code == 201

        second = api_client.post(url, b"other content", content_type="application/octet-stream", **headers)
        assert second.status_code == 409
        assert json.loads(second.content)["error_code"] == "DUPLICATE_ARTIFACT"

        assert Document.objects.filter(component=sample_document_component).count() == 1

    def test_different_version_upload_succeeds(
        self,
        mocker: MockerFixture,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        create_documents_api_mock(mocker, scenario="success")
        client.force_login(sample_user)

        assert _upload(client, sample_document_component.id, version="1.0").status_code == 201
        assert _upload(client, sample_document_component.id, version="2.0").status_code == 201

        assert Document.objects.filter(component=sample_document_component).count() == 2

    def test_different_document_same_version_upload_succeeds(
        self,
        mocker: MockerFixture,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        create_documents_api_mock(mocker, scenario="success")
        client.force_login(sample_user)

        assert _upload(client, sample_document_component.id, filename="readme.pdf").status_code == 201
        assert _upload(client, sample_document_component.id, filename="license.pdf").status_code == 201

        assert Document.objects.filter(component=sample_document_component).count() == 2


@pytest.mark.django_db
class TestDocumentUpdateDuplicates:
    """An edit cannot rename a document onto a pair the component already holds."""

    def test_rename_onto_existing_pair_returns_409(
        self,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        _make_document(sample_document_component, name="readme", version="1.0")
        target = _make_document(sample_document_component, name="license", version="1.0")

        client.force_login(sample_user)
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": target.id}),
            json.dumps({"name": "readme"}),
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "already exists" in json.loads(response.content)["detail"]

        target.refresh_from_db()
        assert target.name == "license"

    def test_version_bump_onto_existing_version_returns_409(
        self,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        _make_document(sample_document_component, version="2.0")
        target = _make_document(sample_document_component, version="1.0")

        client.force_login(sample_user)
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": target.id}),
            json.dumps({"version": "2.0"}),
            content_type="application/json",
        )

        assert response.status_code == 409

        target.refresh_from_db()
        assert target.version == "1.0"

    def test_unchanged_name_and_version_still_updates(
        self,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        target = _make_document(sample_document_component)

        client.force_login(sample_user)
        response = client.patch(
            reverse("api-1:update_document", kwargs={"document_id": target.id}),
            json.dumps({"name": "foobar", "version": "1.0", "description": "Still fine"}),
            content_type="application/json",
        )

        assert response.status_code == 200

        target.refresh_from_db()
        assert target.description == "Still fine"


class TestDuplicateErrorDetection:
    """The helper must not swallow integrity errors from other constraints."""

    def test_unrelated_integrity_error_is_not_a_duplicate(self):
        assert not is_duplicate_document_error(IntegrityError('null value in column "name" violates not-null'))

    def test_constraint_name_in_message_is_a_duplicate(self):
        message = (
            'duplicate key value violates unique constraint '
            '"documents_document_unique_component_name_version"'
        )
        assert is_duplicate_document_error(IntegrityError(message))

    def test_sqlite_message_is_a_duplicate(self):
        table = Document._meta.db_table
        message = f"UNIQUE constraint failed: {table}.component_id, {table}.name, {table}.version"
        assert is_duplicate_document_error(IntegrityError(message))
