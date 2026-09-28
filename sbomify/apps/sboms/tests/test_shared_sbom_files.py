"""A stored SBOM file is shared by every row with the same bytes, in any workspace.

Deleting one row, or the component holding it, must keep the file while another
row still references it, and remove it with the last reference.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.conf import settings
from django.db import connection, transaction
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.management.commands.create_test_sbom_environment import Command
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.services.sboms import deleting_sbom_files, upload_sbom_file
from sbomify.apps.teams.models import Team

BUCKET = settings.AWS_SBOMS_STORAGE_BUCKET_NAME


@pytest.fixture
def delete_object(mocker: MockerFixture) -> MagicMock:
    mocker.patch("boto3.resource")
    return mocker.patch("sbomify.apps.core.object_store.StorageClient.delete_object")


@pytest.fixture
def other_workspace_sbom(sample_sbom: SBOM) -> SBOM:
    """An SBOM in a second workspace holding the same stored file as ``sample_sbom``."""
    team = Team.objects.create(name="Other workspace")
    component = Component.objects.create(name="other component", team=team)
    return SBOM.objects.create(
        name="other", component=component, format="spdx", sbom_filename=sample_sbom.sbom_filename
    )


def _deleted_keys(delete_object: MagicMock) -> list[str]:
    return [call.args[1] for call in delete_object.call_args_list]


@pytest.mark.django_db
def test_deleting_an_sbom_keeps_a_file_another_workspace_uses(
    sample_sbom: SBOM,
    other_workspace_sbom: SBOM,
    sample_access_token: AccessToken,
    delete_object: MagicMock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})

    with django_capture_on_commit_callbacks(execute=True):
        response = Client().delete(url, **get_api_headers(sample_access_token))

    assert response.status_code == 204
    assert not SBOM.objects.filter(pk=sample_sbom.pk).exists()
    assert sample_sbom.sbom_filename not in _deleted_keys(delete_object)


@pytest.mark.django_db
def test_deleting_the_last_sbom_using_a_file_deletes_it(
    sample_sbom: SBOM,
    sample_access_token: AccessToken,
    delete_object: MagicMock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})

    with django_capture_on_commit_callbacks(execute=True):
        response = Client().delete(url, **get_api_headers(sample_access_token))

    assert response.status_code == 204
    delete_object.assert_called_once_with(BUCKET, sample_sbom.sbom_filename)


@pytest.mark.django_db
def test_deleting_a_component_keeps_a_file_another_workspace_uses(
    sample_sbom: SBOM,
    other_workspace_sbom: SBOM,
    sample_access_token: AccessToken,
    delete_object: MagicMock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse("api-1:delete_component", kwargs={"component_id": sample_sbom.component_id})

    with django_capture_on_commit_callbacks(execute=True):
        response = Client().delete(url, **get_api_headers(sample_access_token))

    assert response.status_code == 204
    assert not Component.objects.filter(pk=sample_sbom.component_id).exists()
    assert SBOM.objects.filter(pk=other_workspace_sbom.pk).exists()
    assert sample_sbom.sbom_filename not in _deleted_keys(delete_object)


@pytest.mark.django_db
def test_deleting_the_last_component_using_a_file_deletes_it(
    sample_sbom: SBOM,
    sample_access_token: AccessToken,
    delete_object: MagicMock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse("api-1:delete_component", kwargs={"component_id": sample_sbom.component_id})

    with django_capture_on_commit_callbacks(execute=True):
        response = Client().delete(url, **get_api_headers(sample_access_token))

    assert response.status_code == 204
    delete_object.assert_called_once_with(BUCKET, sample_sbom.sbom_filename)


@pytest.mark.django_db
def test_test_environment_cleanup_keeps_a_shared_file(
    sample_sbom: SBOM,
    other_workspace_sbom: SBOM,
    delete_object: MagicMock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    component = sample_sbom.component
    component.name = "test-component-1"
    component.save()
    own = SBOM.objects.create(
        name="own", component=component, format="spdx", version="own", sbom_filename="only-here.json"
    )

    with django_capture_on_commit_callbacks(execute=True):
        Command().cleanup_test_data(component.team)

    assert not SBOM.objects.filter(pk__in=[sample_sbom.pk, own.pk]).exists()
    assert _deleted_keys(delete_object) == ["only-here.json"]


@pytest.mark.django_db
def test_a_failed_delete_keeps_the_file(sample_sbom: SBOM, delete_object: MagicMock) -> None:
    with pytest.raises(RuntimeError):
        with deleting_sbom_files([sample_sbom.sbom_filename]):
            SBOM.objects.filter(pk=sample_sbom.pk).delete()
            raise RuntimeError("rolled back")

    assert SBOM.objects.filter(sbom_filename=sample_sbom.sbom_filename).exists()
    delete_object.assert_not_called()


@pytest.mark.django_db
def test_an_enclosing_rollback_keeps_the_file(
    sample_sbom: SBOM, delete_object: MagicMock, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                with deleting_sbom_files([sample_sbom.sbom_filename]):
                    SBOM.objects.filter(pk=sample_sbom.pk).delete()
                raise RuntimeError("rolled back")

    assert SBOM.objects.filter(pk=sample_sbom.pk).exists()
    delete_object.assert_not_called()


def test_upload_refuses_to_run_outside_a_transaction(mocker: MockerFixture) -> None:
    mocker.patch("sbomify.apps.sboms.services.sboms.transaction.get_autocommit", return_value=True)
    s3 = MagicMock()

    with pytest.raises(RuntimeError):
        upload_sbom_file(s3, b"{}")

    s3.upload_sbom.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_delete_waits_for_an_upload_of_the_same_bytes(sample_component: Component, delete_object: MagicMock) -> None:
    """A delete that starts while an upload of the same bytes is uncommitted sees the new row and keeps the file."""
    data = b'{"shared": true}'
    key = StorageClient.sbom_object_name(data)
    existing = SBOM.objects.create(name="old", component=sample_component, format="spdx", sbom_filename=key)
    s3 = MagicMock()
    s3.upload_sbom.return_value = key
    upload_locked = threading.Event()
    finish_upload = threading.Event()
    errors: list[BaseException] = []

    def upload() -> None:
        try:
            with transaction.atomic():
                filename = upload_sbom_file(s3, data)
                upload_locked.set()
                finish_upload.wait(10)
                SBOM.objects.create(
                    name="new", component=sample_component, format="spdx", version="2", sbom_filename=filename
                )
        except BaseException as exc:
            errors.append(exc)
        finally:
            connection.close()

    def delete() -> None:
        try:
            with deleting_sbom_files([key]):
                SBOM.objects.filter(pk=existing.pk).delete()
        except BaseException as exc:
            errors.append(exc)
        finally:
            connection.close()

    uploader = threading.Thread(target=upload)
    uploader.start()
    assert upload_locked.wait(10)
    deleter = threading.Thread(target=delete)
    deleter.start()
    deleter.join(1)
    assert deleter.is_alive(), "the delete must wait for the upload's lock"

    finish_upload.set()
    uploader.join(10)
    deleter.join(10)

    assert not errors
    assert list(SBOM.objects.filter(sbom_filename=key).values_list("name", flat=True)) == ["new"]
    delete_object.assert_not_called()
    SBOM.objects.filter(sbom_filename=key).delete()
