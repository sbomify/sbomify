"""Linked-only aggregates must retain the OIDC product read boundary."""

from typing import Any

import pytest
from django.test import Client

from sbomify.apps.core.models import Component, Release, ReleaseLink

from . import test_bot_release_read_scope as fixtures

bound_component = fixtures.bound_component
bot_token = fixtures.bot_token
own_release = fixtures.own_release
other_component = fixtures.other_component
other_release = fixtures.other_release
builders = fixtures.builders

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("publishes_to_target", [False, True])
def test_linked_only_download_checks_the_targets_read_scope(
    bot_token: str,
    own_release: Release,
    other_release: Release,
    bound_component: Component,
    builders: dict[str, Any],
    publishes_to_target: bool,
) -> None:
    own_release.artifacts.all().delete()
    ReleaseLink.objects.create(release=own_release, linked_release=other_release)
    if publishes_to_target:
        other_release.product.components.add(bound_component)

    response = Client().get(f"/api/v1/releases/{own_release.id}/download", HTTP_AUTHORIZATION=f"Bearer {bot_token}")

    assert response.status_code == (200 if publishes_to_target else 404), response.content
    assert builders["sbom"].called is publishes_to_target
    if publishes_to_target:
        assert builders["sbom"].call_args.kwargs["readable_product_ids"] == {other_release.product_id}
