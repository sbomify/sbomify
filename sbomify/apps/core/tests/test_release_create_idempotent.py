"""Creating a release twice.

Two CI matrix legs tag the same release concurrently. Both read "absent", both
insert, and the loser used to get a 400 that failed its build.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Release
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db


def _create(client: Client, product, **extra):
    return client.post(
        reverse("api-1:create_release"),
        data={"product_id": product.id, "name": "a87242d", **extra},
        content_type="application/json",
    )


def test_the_first_create_returns_201(client: Client, sample_product, sample_team_with_owner_member):
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    assert _create(client, sample_product).status_code == 201


def test_creating_the_same_name_again_returns_the_existing_one(
    client: Client, sample_product, sample_team_with_owner_member
):
    """The loser of the race gets the release rather than a 400, so tagging is
    deterministic however the two jobs interleave."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)
    first = _create(client, sample_product)

    second = _create(client, sample_product)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert Release.objects.filter(product=sample_product, name="a87242d").count() == 1


def test_a_version_collision_is_still_a_conflict(client: Client, sample_product, sample_team_with_owner_member):
    """Idempotence is only for the same name. Reusing a version under a
    different name is a genuine mistake and must not be swallowed."""
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)
    _create(client, sample_product, version="1.0.0")

    clash = client.post(
        reverse("api-1:create_release"),
        data={"product_id": sample_product.id, "name": "different-name", "version": "1.0.0"},
        content_type="application/json",
    )

    assert clash.status_code == 400


def test_an_unrelated_integrity_error_is_not_rewritten(
    client: Client, sample_product, sample_team_with_owner_member, monkeypatch
):
    """Idempotence is scoped to a name collision. Anything else — a foreign key,
    a NOT NULL, a constraint added later — must surface as itself rather than
    being dressed up as a duplicate."""
    from django.db import IntegrityError

    from sbomify.apps.core.models import Release as ReleaseModel

    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    def boom(*args, **kwargs):
        raise IntegrityError('null value in column "product_id" violates not-null constraint')

    monkeypatch.setattr(ReleaseModel.objects, "create", boom)

    response = _create(client, sample_product)

    # The generic handler reports it as the server fault it is, not as a
    # duplicate. A NOT NULL violation reaching the view is our bug, not the
    # caller's, so it must not come back as a 4xx.
    assert response.status_code == 500
    assert "already exists" not in response.json()["detail"]
