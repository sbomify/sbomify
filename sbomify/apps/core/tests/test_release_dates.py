"""A release date the caller sends must not become an internal server error.

``ReleaseCreateSchema.released_at`` is a ``datetime``, and an ISO-8601 string
without an offset parses to a naive one. ``Release.clean()`` then compared it
against ``created_at``, which is always aware, and Python raised

    TypeError: can't compare offset-naive and offset-aware datetimes

which the endpoint's ``except Exception`` turned into a 400 reading "Internal
server error". Two separate wrongs in one call: the comparison should not have
raised, and a date the caller got wrong should say so rather than pointing at us.

Both were seen in production within a minute of each other, from what looks like
someone importing historical releases: eighteen rejections whose message never
reached them, then the crash when they tried dropping the timezone.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_component,
    sample_product,
)
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


def _post_release(client: Client, token: AccessToken, payload: dict):
    return client.post(
        reverse("api-1:create_release"),
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token.encoded_token}",
    )


@pytest.fixture
def api_client(sample_product: Product):  # noqa: F811
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())
    return client


@pytest.mark.django_db
def test_a_release_date_without_a_timezone_is_accepted(
    api_client: Client,
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """The crash. A bare timestamp is a normal thing for a caller to send.

    ``created_at`` is deliberately left out, which is what makes the two sides
    disagree: it defaults to ``timezone.now()`` and is therefore aware, while
    the ``released_at`` that was sent is not. Sending both naive compares two
    naive datetimes and never reproduced this.

    The value is read as local time, which is what Django does with a naive
    datetime everywhere else, and stored aware so nothing downstream has to
    think about it again.
    """
    future = dj_timezone.localtime(dj_timezone.now()).replace(tzinfo=None) + timedelta(days=30)
    response = _post_release(
        api_client,
        sample_access_token,
        {
            "name": "v1.0.0",
            "product_id": str(sample_product.id),
            "released_at": future.isoformat(),
        },
    )

    assert response.status_code == 201, response.json()

    release = Release.objects.get(id=response.json()["id"])
    assert dj_timezone.is_aware(release.released_at)
    assert dj_timezone.is_aware(release.created_at)


@pytest.mark.django_db
def test_a_naive_release_date_still_gets_compared(
    api_client: Client,
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Not-crashing must not mean not-checking.

    The easy wrong fix is to skip the comparison whenever either side is naive.
    A release dated before its own creation is still wrong, and normalising both
    sides is what lets it be caught — and caught by name, rather than as the
    ``TypeError`` the comparison used to raise.
    """
    past = dj_timezone.localtime(dj_timezone.now()).replace(tzinfo=None) - timedelta(days=30)
    response = _post_release(
        api_client,
        sample_access_token,
        {
            "name": "v1.0.0",
            "product_id": str(sample_product.id),
            "released_at": past.isoformat(),
        },
    )

    assert response.status_code == 400
    assert "earlier than creation date" in response.json()["detail"]


@pytest.mark.django_db
def test_a_rejected_date_says_what_is_wrong_with_it(
    api_client: Client,
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """The other half. "Internal server error" is not a thing to act on.

    This is the case with 18 occurrences in one minute: a caller backdating a
    release past its default creation time, retrying, and being told nothing
    each time. It also stops a plain 400 from being filed as a fault.
    """
    response = _post_release(
        api_client,
        sample_access_token,
        {
            "name": "v1.0.0",
            "product_id": str(sample_product.id),
            "released_at": datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Internal server error" not in detail
    assert "earlier than creation date" in detail


@pytest.mark.django_db
def test_updating_a_release_to_a_naive_date_is_accepted(
    api_client: Client,
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """PUT and PATCH reach the same model save, and had the same two handlers."""
    release = Release.objects.create(
        product=sample_product,
        name="v1.0.0",
        created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        released_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )

    response = api_client.patch(
        reverse("api-1:patch_release", kwargs={"release_id": release.id}),
        json.dumps({"released_at": datetime(2024, 6, 1, 12, 0).isoformat()}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200, response.json()

    release.refresh_from_db()
    assert dj_timezone.is_aware(release.released_at)
    assert release.released_at.year == 2024
