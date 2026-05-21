"""Tier 2 PostHog tests for entity create + visibility events.

Covers events fired from the API layer when a workspace owner adds a
new product / component / release, and the HTMX visibility toggle that
shifts entities between public / private / gated.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.posthog_helpers import (
    assert_workspace_attribution,
    called_events,
    find_call,
    patch_capture,
)
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Team


@pytest.mark.django_db(transaction=True)
def test_create_product_captures_product_created(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("api-1:create_product"),
        data=json.dumps({"name": "Tier 2 Test Product"}),
        content_type="application/json",
    )

    assert response.status_code == 201, f"Unexpected status: {response.content!r}"
    assert "product:created" in called_events(mock_capture)
    call = find_call(mock_capture, "product:created")
    assert "product_id" in call.args[2]
    assert "is_public" in call.args[2]
    assert team_with_business_plan.key is not None
    assert_workspace_attribution(mock_capture, "product:created", team_with_business_plan.key)


@pytest.mark.django_db(transaction=True)
def test_create_component_captures_component_created(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("api-1:create_component"),
        data=json.dumps({"name": "Tier 2 Test Component"}),
        content_type="application/json",
    )

    assert response.status_code == 201, f"Unexpected status: {response.content!r}"
    assert "component:created" in called_events(mock_capture)
    call = find_call(mock_capture, "component:created")
    assert "component_id" in call.args[2]
    assert "component_type" in call.args[2]
    # visibility must be a plain string (the ComponentVisibility enum value),
    # not the enum object — PostHog can't serialize Django enums.
    visibility = call.args[2]["visibility"]
    assert isinstance(visibility, str), f"visibility must be a str, got {type(visibility).__name__}"
    assert team_with_business_plan.key is not None
    assert_workspace_attribution(mock_capture, "component:created", team_with_business_plan.key)


@pytest.mark.django_db(transaction=True)
def test_create_release_captures_release_created(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """First create a product to attach the release to, then create the release."""
    from sbomify.apps.core.models import Product

    product = Product.objects.create(name="Release Test Product", team=team_with_business_plan)

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("api-1:create_release"),
        data=json.dumps({"product_id": str(product.id), "name": "v1.0.0"}),
        content_type="application/json",
    )

    assert response.status_code == 201, f"Unexpected status: {response.content!r}"
    assert "release:created" in called_events(mock_capture)
    call = find_call(mock_capture, "release:created")
    assert call.args[2]["product_id"] == str(product.id)
    assert "release_id" in call.args[2]
    assert "is_prerelease" in call.args[2]
    assert team_with_business_plan.key is not None
    assert_workspace_attribution(mock_capture, "release:created", team_with_business_plan.key)


@pytest.mark.django_db(transaction=True)
def test_toggle_component_visibility_captures_event(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Components support 'public' / 'private' / 'gated' — exercise 'gated' too."""
    from sbomify.apps.core.models import Component

    component = Component.objects.create(name="Visibility Test", team=team_with_business_plan)

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("core:toggle_public_status", kwargs={"item_type": "component", "item_id": component.id}),
        data={"visibility": "gated"},
    )

    assert response.status_code == 200, f"Unexpected status: {response.content!r}"
    assert "item:visibility_toggled" in called_events(mock_capture)
    call = find_call(mock_capture, "item:visibility_toggled")
    assert call.args[2]["item_type"] == "component"
    assert call.args[2]["item_id"] == component.id
    assert call.args[2]["new_visibility"] == "gated"


@pytest.mark.django_db(transaction=True)
def test_toggle_product_visibility_captures_event(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    from sbomify.apps.core.models import Product

    product = Product.objects.create(name="Product Visibility Test", team=team_with_business_plan)

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(
        reverse("core:toggle_public_status", kwargs={"item_type": "product", "item_id": product.id}),
        data={"is_public": "on"},
    )

    assert response.status_code == 200, f"Unexpected status: {response.content!r}"
    assert "item:visibility_toggled" in called_events(mock_capture)
    call = find_call(mock_capture, "item:visibility_toggled")
    assert call.args[2]["item_type"] == "product"
    assert call.args[2]["item_id"] == product.id
    assert call.args[2]["new_visibility"] == "public"


@pytest.mark.django_db(transaction=True)
def test_delete_unscoped_token_does_not_capture(
    mocker: MockerFixture,
    sample_user: Any,
) -> None:
    """Unscoped legacy tokens (no workspace) intentionally skip api_token:deleted.

    Tier 2 convention is workspace-keyed distinct_id; firing this event
    with a user PK fallback would mix scopes for the same event name.
    """
    from sbomify.apps.access_tokens.models import AccessToken

    # Build a token with no team (legacy unscoped)
    token = AccessToken.objects.create(
        encoded_token="dummy-unscoped",
        user=sample_user,
        description="legacy",
        team=None,
    )

    mock_capture = patch_capture(mocker)
    client = Client()
    client.force_login(sample_user)

    response = client.delete(reverse("core:delete_access_token", kwargs={"token_id": token.id}))

    assert response.status_code == 200
    assert "api_token:deleted" not in called_events(mock_capture)
