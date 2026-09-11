"""Tests for the document uniqueness constraint.

A document is identified by (component, name, version), so re-uploading the same
name at the same version is a duplicate. Different documents may share a version,
and the same name/version may exist under a different component.
"""

from __future__ import annotations

import importlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Product, Release, ReleaseArtifact
from sbomify.apps.core.object_store import ORPHANED_OBJECT_MARKER
from sbomify.apps.core.tests.s3_fixtures import create_documents_api_mock
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.documents.models import DOCUMENT_UNIQUE_CONSTRAINT, Document
from sbomify.apps.documents.utils import (
    VERSION_MAX_LENGTH,
    is_duplicate_document_error,
    next_free_document_version,
    normalize_decimal_version,
)
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401
from sbomify.apps.teams.models import Member

# The migration module name starts with a digit, so it cannot be imported directly.
mark_duplicate_documents = importlib.import_module(
    "sbomify.apps.documents.migrations.0015_document_unique_component_name_version"
).mark_duplicate_documents


class _SchemaEditor:
    """Stands in for the editor Django hands a RunPython, which the data step uses
    only to reach the connection (to take the table lock on PostgreSQL)."""

    def __init__(self) -> None:
        self.connection = connection


def _run_migration_step() -> None:
    """Run the data step the way a migration does: inside a transaction, which is
    what its LOCK TABLE needs and what holds the lock until AddConstraint."""
    with transaction.atomic():
        mark_duplicate_documents(global_apps, _SchemaEditor())


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
        # Not derived from the version: these tests use versions at max_length.
        document_filename=f"{name}.bin",
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
        storage = create_documents_api_mock(mocker, scenario="success")
        client.force_login(sample_user)

        first = _upload(client, sample_document_component.id)
        assert first.status_code == 201
        assert storage.upload_document.call_count == 1

        second = _upload(client, sample_document_component.id)
        assert second.status_code == 409

        # The pre-check runs before the object is stored, so the rejected upload
        # must not have written anything to S3.
        assert storage.upload_document.call_count == 1

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
        storage = create_documents_api_mock(mocker, scenario="success")
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

        # Different bytes, so a stored object here would be a real orphan.
        assert storage.upload_document.call_count == 1

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
        body = json.loads(response.content)
        assert "already exists" in body["detail"]
        assert body["error_code"] == "DUPLICATE_ARTIFACT"

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
        message = 'duplicate key value violates unique constraint "documents_document_unique_component_name_version"'
        assert is_duplicate_document_error(IntegrityError(message))

    def test_sqlite_message_is_a_duplicate(self):
        table = Document._meta.db_table
        message = f"UNIQUE constraint failed: {table}.component_id, {table}.name, {table}.version"
        assert is_duplicate_document_error(IntegrityError(message))


@pytest.fixture
def without_unique_constraint():
    """Drop the uniqueness constraint so a test can seed the duplicates that predate
    it, then put it back.

    Needs a transactional test: SQLite refuses to run its schema editor inside the
    atomic block the plain ``django_db`` marker wraps around each test.
    """
    original = Document._meta.constraints
    constraint = next(c for c in original if c.name == DOCUMENT_UNIQUE_CONSTRAINT)

    # SQLite implements a plain UniqueConstraint as part of CREATE TABLE, so its
    # schema editor rebuilds the table from the model. The model has to stop
    # declaring the constraint or the rebuild just puts it back.
    Document._meta.constraints = [c for c in original if c.name != DOCUMENT_UNIQUE_CONSTRAINT]
    with connection.schema_editor(atomic=False) as editor:
        editor.remove_constraint(Document, constraint)
    try:
        yield
    finally:
        Document.objects.all().delete()
        Document._meta.constraints = original
        with connection.schema_editor(atomic=False) as editor:
            editor.add_constraint(Document, constraint)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("without_unique_constraint")
class TestMarkDuplicateDocuments:
    """The migration's data step, which only ever runs against a schema that still
    allows duplicates."""

    def test_keeps_the_release_pinned_row_and_suffixes_the_rest(self, sample_document_component, sample_team):
        pinned = _make_document(sample_document_component, version="2.0")
        newer = _make_document(sample_document_component, version="2.0")
        Document.objects.filter(pk=pinned.pk).update(created_at=timezone.now() - timedelta(days=5))

        product = Product.objects.create(name="Pinned product", team=sample_team)
        release = Release.objects.create(product=product, name="r1", version="1")
        ReleaseArtifact.objects.create(release=release, document=pinned)

        _run_migration_step()

        pinned.refresh_from_db()
        newer.refresh_from_db()
        assert pinned.version == "2.0", "the row a release points at keeps its version"
        assert newer.version == "2.0 (duplicate 1)"

    def test_newest_row_wins_when_nothing_is_pinned(self, sample_document_component):
        older = _make_document(sample_document_component)
        newer = _make_document(sample_document_component)
        Document.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=5))

        _run_migration_step()

        older.refresh_from_db()
        newer.refresh_from_db()
        assert newer.version == "1.0"
        assert older.version == "1.0 (duplicate 1)"

    def test_skips_a_suffix_a_sibling_already_holds(self, sample_document_component):
        _make_document(sample_document_component, version="1.0")
        _make_document(sample_document_component, version="1.0")
        squatter = _make_document(sample_document_component, version="1.0 (duplicate 1)")

        _run_migration_step()

        squatter.refresh_from_db()
        assert squatter.version == "1.0 (duplicate 1)", "an existing row is never renamed out of the way"

        versions = sorted(
            Document.objects.filter(component=sample_document_component).values_list("version", flat=True)
        )
        assert versions == ["1.0", "1.0 (duplicate 1)", "1.0 (duplicate 2)"]

    def test_truncates_so_the_suffixed_version_still_fits(self, sample_document_component):
        long_version = "v" * 255
        _make_document(sample_document_component, version=long_version)
        _make_document(sample_document_component, version=long_version)

        _run_migration_step()

        versions = list(Document.objects.filter(component=sample_document_component).values_list("version", flat=True))
        assert len(versions) == len(set(versions)), "the group is now unique"
        assert max(len(v) for v in versions) <= 255

    def test_does_not_group_the_same_pair_across_components(self, sample_document_component, other_document_component):
        """The sibling query is scoped to real (component, name) pairs, so a row
        that merely shares a name and version with another component is untouched."""
        _make_document(sample_document_component, version="1.0")
        _make_document(sample_document_component, version="1.0")
        elsewhere = _make_document(other_document_component, version="1.0")

        _run_migration_step()

        elsewhere.refresh_from_db()
        assert elsewhere.version == "1.0"
        assert sorted(
            Document.objects.filter(component=sample_document_component).values_list("version", flat=True)
        ) == ["1.0", "1.0 (duplicate 1)"]

    def test_leaves_rows_that_were_never_duplicates_alone(self, sample_document_component):
        readme = _make_document(sample_document_component, name="readme", version="1.0")
        license_doc = _make_document(sample_document_component, name="license", version="1.0")

        _run_migration_step()

        readme.refresh_from_db()
        license_doc.refresh_from_db()
        assert readme.version == "1.0"
        assert license_doc.version == "1.0"


@pytest.mark.django_db
class TestNextFreeDocumentVersion:
    """The allocator the company NDA upload uses to avoid the new constraint."""

    def test_returns_the_candidate_when_it_is_free(self, sample_document_component):
        assert next_free_document_version(sample_document_component.id, "foobar", "1.0") == "1.0"

    def test_counts_on_past_a_taken_decimal(self, sample_document_component):
        _make_document(sample_document_component, version="1.0")
        _make_document(sample_document_component, version="1.1")

        assert next_free_document_version(sample_document_component.id, "foobar", "1.0") == "1.2"

    def test_suffixes_a_candidate_that_is_not_a_number(self, sample_document_component):
        _make_document(sample_document_component, version="alpha")

        assert next_free_document_version(sample_document_component.id, "foobar", "alpha") == "alpha (2)"

    def test_a_suffixed_version_still_fits_the_column(self, sample_document_component):
        """A candidate can already be at max_length, and a version the column
        cannot hold would just fail the insert this is here to avoid."""
        candidate = "v" * VERSION_MAX_LENGTH
        _make_document(sample_document_component, version=candidate)

        result = next_free_document_version(sample_document_component.id, "foobar", candidate)

        assert len(result) == VERSION_MAX_LENGTH
        assert result.endswith(" (2)")
        assert result not in {candidate}

    def test_is_scoped_to_the_name(self, sample_document_component):
        _make_document(sample_document_component, name="readme", version="1.0")

        assert next_free_document_version(sample_document_component.id, "license", "1.0") == "1.0"

    def test_a_non_finite_candidate_does_not_loop(self, sample_document_component):
        """Decimal parses "NaN" and "Infinity", and adding to either returns it
        unchanged, so counting on from one would never terminate."""
        for candidate in ("NaN", "Infinity", "-Infinity", "sNaN"):
            _make_document(sample_document_component, name=candidate, version=candidate)

            assert next_free_document_version(sample_document_component.id, candidate, candidate) == f"{candidate} (2)"

    def test_a_candidate_that_cannot_advance_falls_back_to_a_suffix(self, sample_document_component):
        """Past the decimal context precision, adding 0.1 rounds straight back, so
        counting on would never reach a free version."""
        candidate = "9" * 28
        _make_document(sample_document_component, name=candidate, version=candidate)

        assert next_free_document_version(sample_document_component.id, candidate, candidate) == f"{candidate} (2)"

    def test_a_scientific_candidate_resolves_without_changing_magnitude(self, sample_document_component):
        """ "1E+30" cannot advance either, but normalising it to plain notation is
        already a free version, and one of the same magnitude."""
        _make_document(sample_document_component, name="sci", version="1E+30")

        result = next_free_document_version(sample_document_component.id, "sci", "1E+30")

        assert result == "1" + "0" * 30
        assert Decimal(result) == Decimal("1E+30")

    def test_suffixes_walk_past_taken_suffixes(self, sample_document_component):
        _make_document(sample_document_component, version="alpha")
        _make_document(sample_document_component, version="alpha (2)")

        assert next_free_document_version(sample_document_component.id, "foobar", "alpha") == "alpha (3)"


@pytest.mark.django_db
class TestOrphanedObjectLogging:
    """An object is stored before its row, so any failed insert strands it."""

    def test_a_non_duplicate_integrity_error_is_still_recorded(
        self,
        mocker: MockerFixture,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        storage = create_documents_api_mock(mocker, scenario="success")
        recorded = mocker.patch("sbomify.apps.documents.apis.log_orphaned_object")
        mocker.patch.object(Document, "save", side_effect=IntegrityError('null value in column "name"'))
        client.force_login(sample_user)

        response = _upload(client, sample_document_component.id)

        # The outer handler turns the re-raised error into a 400, but the object
        # must still be recorded: it is stored with no row pointing at it.
        assert response.status_code == 400
        recorded.assert_called_once_with(storage.upload_document.return_value)

    def test_losing_the_constraint_race_is_a_409_and_a_recorded_object(
        self,
        mocker: MockerFixture,
        client: Client,
        sample_user: AbstractBaseUser,
        sample_document_component,
    ):
        """The pre-check cannot catch a concurrent upload, so the constraint does.
        This is the branch that a regression in constraint-name detection would
        silently turn into the generic 400."""
        storage = create_documents_api_mock(mocker, scenario="success")
        recorded = mocker.patch("sbomify.apps.documents.apis.log_orphaned_object")
        mocker.patch.object(
            Document,
            "save",
            side_effect=IntegrityError(
                "duplicate key value violates unique constraint "
                f'"{DOCUMENT_UNIQUE_CONSTRAINT}"'
            ),
        )
        client.force_login(sample_user)

        response = _upload(client, sample_document_component.id)

        assert response.status_code == 409
        body = json.loads(response.content)
        assert body["error_code"] == "DUPLICATE_ARTIFACT"
        assert "already exists" in body["detail"]
        recorded.assert_called_once_with(storage.upload_document.return_value)
        assert not Document.objects.filter(component=sample_document_component).exists()

    def test_the_marker_is_one_string_for_every_artifact_path(self):
        assert ORPHANED_OBJECT_MARKER == "Potential orphaned S3 object after IntegrityError"


class TestNormalizeDecimalVersion:
    """str(Decimal) is not a safe source for this: it goes scientific for large
    values, and stripping zeroes from "1E+30" would eat the exponent."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("1.10"), "1.1"),
            (Decimal("1.0"), "1"),
            (Decimal("2.5"), "2.5"),
            (Decimal("100"), "100"),
            (Decimal("100.0"), "100"),
            (Decimal("1E+30"), "1" + "0" * 30),
        ],
    )
    def test_renders_without_changing_magnitude(self, value, expected):
        assert normalize_decimal_version(value) == expected


@pytest.mark.django_db
class TestNextFreeDocumentVersionAlwaysFits:
    """Whatever path it takes, the result has to be insertable."""

    @pytest.mark.parametrize(
        "candidate",
        [
            "9" * VERSION_MAX_LENGTH,  # a decimal bump rounds up into 256 characters
            "v" * VERSION_MAX_LENGTH,  # the suffix path, base already at the limit
            "9" * (VERSION_MAX_LENGTH + 1),  # a candidate that never fit to begin with
            "1E+999999999",  # finite, fits the field, and overflows the arithmetic
            "1E-999999999",  # finite, fits the field, a gigabyte in fixed point
            "1.0",
        ],
    )
    def test_every_result_fits_the_column(self, sample_document_component, candidate):
        _make_document(sample_document_component, version=candidate[:VERSION_MAX_LENGTH])

        result = next_free_document_version(sample_document_component.id, "foobar", candidate)

        assert len(result) <= VERSION_MAX_LENGTH
        # And it is actually insertable, which is the whole point.
        Document.objects.create(
            name="foobar",
            version=result,
            document_filename="fits.bin",
            component=sample_document_component,
            source="manual_upload",
        )
