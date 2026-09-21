"""The populations are the whole point, so they are tested first."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import User
from sbomify.apps.ops.services.populations import bot_identities, people


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

    def test_a_person_whose_email_merely_contains_the_domain_is_still_a_person(self):
        User.objects.create_user(
            username="careful",
            email="sbomify.local.user@example.com",
            password="x",
        )

        assert people().count() == 1
