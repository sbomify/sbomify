"""Company NDA version allocation under the document uniqueness constraint.

The allocator guesses the next version by counting on from the newest NDA, so it
has to cope with a version that is already in use: documents are unique on
component, name and version.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.documents.models import Document
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member

PDF = b"%PDF-1.4 test nda"


def _post_nda(client: Client, team_key: str, filename: str = "nda.pdf"):
    return client.post(
        reverse("teams:team_settings", kwargs={"team_key": team_key}),
        {
            "company_nda_action": "upload",
            "company_nda_file": SimpleUploadedFile(filename, PDF, content_type="application/pdf"),
        },
    )


@pytest.fixture
def owner_client(client: Client, sample_team_with_owner_member: Member):  # noqa: F811
    client.force_login(sample_team_with_owner_member.user)
    return client, sample_team_with_owner_member.team


@pytest.mark.django_db
class TestCompanyNdaVersioning:
    def test_a_second_upload_of_the_same_file_gets_the_next_version(self, mocker: MockerFixture, owner_client):
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        client, team = owner_client

        _post_nda(client, team.key)
        _post_nda(client, team.key)

        versions = sorted(Document.objects.filter(name="nda.pdf").values_list("version", flat=True))
        assert versions == ["1.0", "1.1"]

    def test_a_version_already_in_use_is_stepped_over(self, mocker: MockerFixture, owner_client):
        """The newest NDA is not always the highest version: an out-of-order row,
        or one the duplicate migration suffixed, can send the allocator at a
        version that already exists."""
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        client, team = owner_client

        _post_nda(client, team.key)
        component = Document.objects.get(name="nda.pdf").component
        # A 1.1 that is older than the 1.0, so the allocator reads 1.0 as newest
        # and proposes the 1.1 that is already taken.
        Document.objects.create(
            name="nda.pdf",
            version="1.1",
            document_filename="other.bin",
            component=component,
            source="manual_upload",
            document_type=Document.DocumentType.NDA,
        )
        Document.objects.filter(version="1.1").update(created_at=Document.objects.get(version="1.0").created_at)

        response = _post_nda(client, team.key)

        assert response.status_code == 302, "the upload succeeds rather than erroring"
        versions = sorted(Document.objects.filter(name="nda.pdf").values_list("version", flat=True))
        assert versions == ["1.0", "1.1", "1.2"]

    def test_a_losing_insert_is_retried_rather_than_surfaced(self, mocker: MockerFixture, owner_client):
        """Two uploads can be handed the same free version, and one loses the
        constraint. That is a conflict to re-resolve, not an error to show."""
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        client, team = owner_client

        _post_nda(client, team.key)

        real_create = Document.objects.create
        calls: list[str] = []

        def create_losing_once(**kwargs):
            calls.append(kwargs["version"])
            if len(calls) == 1:
                raise IntegrityError(
                    'duplicate key value violates unique constraint "documents_document_unique_component_name_version"'
                )
            return real_create(**kwargs)

        mocker.patch.object(Document.objects, "create", side_effect=create_losing_once)

        response = _post_nda(client, team.key)

        assert response.status_code == 302, "the upload succeeds rather than erroring"
        assert len(calls) == 2, "the losing insert is retried"
        assert sorted(Document.objects.filter(name="nda.pdf").values_list("version", flat=True)) == ["1.0", "1.1"]

    def test_an_unrelated_integrity_error_is_not_retried(self, mocker: MockerFixture, owner_client):
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        client, team = owner_client

        calls: list[str] = []

        def create_failing(**kwargs):
            calls.append(kwargs["version"])
            raise IntegrityError('null value in column "name" violates not-null')

        mocker.patch.object(Document.objects, "create", side_effect=create_failing)

        _post_nda(client, team.key)

        assert len(calls) == 1, "only a duplicate is a conflict worth re-resolving"

    @pytest.mark.parametrize("stored_version", ["1E+999999999", "NaN", "Infinity", "not-a-version"])
    def test_a_version_that_cannot_be_counted_on_from_still_uploads(
        self, mocker: MockerFixture, owner_client, stored_version
    ):
        """The allocator guesses by arithmetic on whatever the newest NDA holds, and
        a user picks that. "1E+999999999" is the sharp one: it parses, it fits the
        column, and adding to it raises decimal.Overflow."""
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        client, team = owner_client

        _post_nda(client, team.key)
        Document.objects.filter(name="nda.pdf").update(version=stored_version)

        response = _post_nda(client, team.key)

        assert response.status_code == 302
        versions = list(Document.objects.filter(name="nda.pdf").values_list("version", flat=True))
        assert len(versions) == 2, "a second NDA was created rather than the upload failing"
        assert len(set(versions)) == 2


@pytest.mark.django_db
class TestTheNdaUploadFollowsTheConfiguredCeiling:
    """This upload used to carry its own 50MB literal.

    Every other artifact ceiling reads `ARTIFACT_MAX_UPLOAD_SIZE`, so raising
    `ARTIFACT_MAX_UPLOAD_SIZE_MB` on a deployment moved all of them except this
    one, and nothing said so.
    """

    def test_a_file_over_the_ceiling_is_refused(self, mocker: MockerFixture, owner_client, settings):
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        settings.ARTIFACT_MAX_UPLOAD_SIZE = 1024 * 1024
        client, team = owner_client

        oversized = SimpleUploadedFile(
            "nda.pdf", b"%PDF-1.4" + b"x" * (2 * 1024 * 1024), content_type="application/pdf"
        )
        response = client.post(
            reverse("teams:team_settings", kwargs={"team_key": team.key}),
            {"company_nda_action": "upload", "company_nda_file": oversized},
            follow=True,
        )

        # The message, not only the absence of a row: without it this passes
        # whenever the upload fails for any reason at all.
        assert "File size must be 1MB or smaller" in [m.message for m in response.context["messages"]]
        assert not Document.objects.filter(component__team=team).exists()

    def test_a_file_the_raised_ceiling_allows_is_accepted(self, mocker: MockerFixture, owner_client, settings):
        """The point of the setting: raising it has to actually raise this one."""
        mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
        settings.ARTIFACT_MAX_UPLOAD_SIZE = 100 * 1024 * 1024
        client, team = owner_client

        big = SimpleUploadedFile("nda.pdf", b"%PDF-1.4" + b"x" * (60 * 1024 * 1024), content_type="application/pdf")
        client.post(
            reverse("teams:team_settings", kwargs={"team_key": team.key}),
            {"company_nda_action": "upload", "company_nda_file": big},
        )

        assert Document.objects.filter(component__team=team).exists()

    def test_the_tab_states_the_ceiling_it_enforces(self, owner_client, settings):
        settings.ARTIFACT_MAX_UPLOAD_SIZE = 100 * 1024 * 1024
        client, team = owner_client

        body = client.get(
            reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "trust-center"})
        ).content.decode()

        assert "Max 100MB." in body
        assert "Max 50MB." not in body
