"""The populations are the whole point, so they are tested first."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, User
from sbomify.apps.documents.models import Document
from sbomify.apps.ops.services.populations import (
    artifact_count,
    bot_identities,
    people,
    workspaces_publishing_since,
)
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestPeople:
    def test_a_normal_user_is_a_person(self):
        User.objects.create_user(username="real-person", email="real@example.com", password="x")

        assert people().count() == 1

    def test_a_soft_deleted_user_is_not_counted(self):
        """The row survives the deletion request by up to the grace period."""
        user = User.objects.create_user(username="leaving", email="leaving@example.com", password="x")
        user.is_active = False
        user.deleted_at = timezone.now() - timedelta(days=1)
        user.save(update_fields=["is_active", "deleted_at"])

        assert people().count() == 0

    def test_an_oidc_bot_is_not_a_person(self):
        """Matched on the username prefix, as oidc.services does."""
        User.objects.create_user(
            username="oidc-bot-abc123",
            email="oidc-bot-abc123@sbomify.local",
            password="x",
        )

        assert people().count() == 0
        assert bot_identities().count() == 1

    def test_a_bot_is_matched_by_its_email_domain_too(self):
        User.objects.create_user(username="renamed-bot", email="renamed@SBOMIFY.LOCAL", password="x")

        assert people().count() == 0
        assert bot_identities().count() == 1

    def test_a_deactivated_user_is_not_counted_even_with_no_deleted_at(self):
        """Keycloak's DELETE_ACCOUNT webhook sets is_active=False and nothing else.

        Filtering on deleted_at alone left every Keycloak-side deletion in the
        headline count, in new signups, and in the signup trend, permanently.
        """
        user = User.objects.create_user(username="gone", email="gone@example.com", password="x")
        user.is_active = False
        user.save(update_fields=["is_active"])

        assert user.deleted_at is None
        assert people().count() == 0

    def test_a_person_whose_email_merely_contains_the_domain_is_still_a_person(self):
        User.objects.create_user(
            username="careful",
            email="sbomify.local.user@example.com",
            password="x",
        )

        assert people().count() == 1


@pytest.fixture
def component(db) -> Component:
    return Component.objects.create(team=Team.objects.create(name="Publisher"), name="backend")


@pytest.mark.django_db
class TestArtifacts:
    """An artifact is a BOM or a document. The glossary says so, and a
    documents-only workspace is using the product either way."""

    def test_a_bom_is_an_artifact(self, component):
        SBOM.objects.create(component=component, name="backend", format="spdx")

        assert artifact_count() == 1

    def test_a_document_is_an_artifact_too(self, component):
        Document.objects.create(component=component, name="Threat model")

        assert artifact_count() == 1

    def test_both_kinds_are_counted_together(self, component):
        SBOM.objects.create(component=component, name="backend", format="spdx")
        Document.objects.create(component=component, name="Threat model")

        assert artifact_count() == 2

    def test_the_window_applies_to_both_kinds(self, component):
        SBOM.objects.create(component=component, name="backend", format="spdx")
        Document.objects.create(component=component, name="Threat model")

        assert artifact_count(since=timezone.now() - timedelta(minutes=1)) == 2
        assert artifact_count(since=timezone.now() + timedelta(minutes=1)) == 0


@pytest.mark.django_db
class TestWorkspacesPublishingSince:
    def test_publishing_a_bom_makes_a_workspace_active(self, component):
        SBOM.objects.create(component=component, name="backend", format="spdx")

        assert workspaces_publishing_since(timezone.now() - timedelta(days=7)).count() == 1

    def test_publishing_only_documents_makes_a_workspace_active(self, component):
        """The regression: a documents-only workspace read as dormant."""
        Document.objects.create(component=component, name="Threat model")

        assert workspaces_publishing_since(timezone.now() - timedelta(days=7)).count() == 1

    def test_a_workspace_publishing_both_is_counted_once(self, component):
        SBOM.objects.create(component=component, name="backend", format="spdx")
        Document.objects.create(component=component, name="Threat model")

        assert workspaces_publishing_since(timezone.now() - timedelta(days=7)).count() == 1

    def test_a_workspace_that_published_nothing_is_not_active(self, component):
        assert workspaces_publishing_since(timezone.now() - timedelta(days=7)).count() == 0
