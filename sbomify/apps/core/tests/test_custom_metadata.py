"""Custom key/value metadata on products and components."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.custom_metadata import (
    MAX_PAIRS,
    CustomMetadataError,
    custom_metadata_from_pairs,
    normalize_custom_metadata,
)
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
)
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

# =============================================================================
# Validation rules
# =============================================================================


def test_normalize_strips_and_sorts_by_key() -> None:
    assert normalize_custom_metadata({" owner ": " platform ", "tier": ""}) == {"owner": "platform", "tier": ""}
    assert list(normalize_custom_metadata({"b": "1", "a": "2"})) == ["a", "b"]


def test_normalize_treats_none_as_empty() -> None:
    assert normalize_custom_metadata(None) == {}


@pytest.mark.parametrize(
    "raw",
    [
        ["owner", "platform"],
        {"": "value"},
        {"   ": "value"},
        {"owner": 1},
        {"owner": None},
        {"owner": {"nested": "no"}},
        {"k" * 129: "v"},
        {"k": "v" * 1025},
        {"owner": "a", " owner": "b"},
        {f"k{i}": "v" for i in range(MAX_PAIRS + 1)},
    ],
)
def test_normalize_rejects_bad_input(raw: object) -> None:
    with pytest.raises(CustomMetadataError):
        normalize_custom_metadata(raw)


def test_pairs_drop_blank_rows() -> None:
    assert custom_metadata_from_pairs(["owner", "", " "], ["platform", "", ""]) == {"owner": "platform"}


def test_pairs_reject_value_without_key() -> None:
    with pytest.raises(CustomMetadataError):
        custom_metadata_from_pairs(["", "owner"], ["orphan", "platform"])


# =============================================================================
# API
# =============================================================================


def _client_for(item: Product | Component) -> Client:
    client = Client()
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, item.team, item.team.members.first())
    return client


@pytest.mark.django_db
def test_patch_product_sets_and_returns_custom_metadata(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    client = _client_for(sample_product)
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    response = client.patch(
        url,
        json.dumps({"custom_metadata": {"owner": "platform-team", "tier": "critical"}}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {"owner": "platform-team", "tier": "critical"}
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {"owner": "platform-team", "tier": "critical"}

    get_response = client.get(
        reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
        **get_api_headers(sample_access_token),
    )
    assert get_response.json()["custom_metadata"] == {"owner": "platform-team", "tier": "critical"}


@pytest.mark.django_db
def test_patch_product_null_clears_and_omitted_keeps(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    sample_product.custom_metadata = {"owner": "platform-team"}
    sample_product.save()
    client = _client_for(sample_product)
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    client.patch(
        url, json.dumps({"name": "Renamed"}), content_type="application/json", **get_api_headers(sample_access_token)
    )
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {"owner": "platform-team"}

    client.patch(
        url,
        json.dumps({"custom_metadata": None}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {}


@pytest.mark.django_db
def test_put_product_without_custom_metadata_keeps_it(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    sample_product.custom_metadata = {"owner": "platform-team"}
    sample_product.save()
    client = _client_for(sample_product)

    response = client.put(
        reverse("api-1:update_product", kwargs={"product_id": sample_product.id}),
        json.dumps({"name": sample_product.name, "description": "", "is_public": sample_product.is_public}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200, response.content
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {"owner": "platform-team"}


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [{"owner": 1}, {"owner": {"x": "y"}}, ["owner"], {"": "x"}])
def test_patch_product_rejects_non_string_pairs(
    bad: object,
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    client = _client_for(sample_product)
    response = client.patch(
        reverse("api-1:patch_product", kwargs={"product_id": sample_product.id}),
        json.dumps({"custom_metadata": bad}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code in (400, 422), response.content
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {}


@pytest.mark.django_db
def test_public_product_hides_custom_metadata_from_anonymous(
    sample_product: Product,  # noqa: F811
) -> None:
    sample_product.is_public = True
    sample_product.custom_metadata = {"cost-centre": "CC-1042"}
    sample_product.save()

    response = Client().get(reverse("api-1:get_product", kwargs={"product_id": sample_product.id}))

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {}


@pytest.mark.django_db
def test_component_metadata_endpoint_round_trips_custom_metadata(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    client = _client_for(sample_component)
    url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})

    response = client.patch(
        url,
        json.dumps({"custom_metadata": {"owner": "payments", "pci-scope": "yes"}}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204, response.content

    response = client.get(
        reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id}),
        **get_api_headers(sample_access_token),
    )
    assert response.json()["custom_metadata"] == {"owner": "payments", "pci-scope": "yes"}

    # A metadata patch that leaves the field out does not touch it.
    client.patch(
        url,
        json.dumps({"lifecycle_phase": "build"}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    sample_component.refresh_from_db()
    assert sample_component.custom_metadata == {"owner": "payments", "pci-scope": "yes"}


@pytest.mark.django_db
def test_patch_component_sets_custom_metadata(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    client = _client_for(sample_component)

    response = client.patch(
        reverse("api-1:patch_component", kwargs={"component_id": sample_component.id}),
        json.dumps({"custom_metadata": {"owner": "payments"}}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {"owner": "payments"}


# =============================================================================
# Product card (HTMX)
# =============================================================================


@pytest.mark.django_db
def test_product_card_saves_rows(sample_product: Product) -> None:  # noqa: F811
    client = _client_for(sample_product)
    url = reverse("core:product_custom_metadata", kwargs={"product_id": sample_product.id})

    response = client.post(
        url,
        {"meta_key": ["owner", "", "tier"], "meta_value": ["platform-team", "", "critical"]},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200, response.content
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {"owner": "platform-team", "tier": "critical"}
    assert b"platform-team" in response.content


@pytest.mark.django_db
def test_product_card_rejects_duplicate_keys(sample_product: Product) -> None:  # noqa: F811
    client = _client_for(sample_product)
    url = reverse("core:product_custom_metadata", kwargs={"product_id": sample_product.id})

    response = client.post(url, {"meta_key": ["owner", "owner"], "meta_value": ["a", "b"]}, HTTP_HX_REQUEST="true")

    assert response.headers.get("HX-Reswap") == "none"
    sample_product.refresh_from_db()
    assert sample_product.custom_metadata == {}


@pytest.mark.django_db
def test_api_returns_keys_sorted_whatever_jsonb_stores(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    sample_product.custom_metadata = {"tier": "1", "owner": "2", "cost-centre": "3"}
    sample_product.save()
    client = _client_for(sample_product)

    response = client.get(
        reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
        **get_api_headers(sample_access_token),
    )

    assert list(response.json()["custom_metadata"]) == ["cost-centre", "owner", "tier"]


# =============================================================================
# Visibility: authenticated callers only
# =============================================================================


@pytest.mark.django_db
def test_public_component_hides_custom_metadata_from_anonymous(
    sample_component: Component,  # noqa: F811
) -> None:
    sample_component.visibility = Component.Visibility.PUBLIC
    sample_component.custom_metadata = {"owner": "payments"}
    sample_component.save()
    anonymous = Client()

    item = anonymous.get(reverse("api-1:get_component", kwargs={"component_id": sample_component.id}))
    meta = anonymous.get(reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id}))

    assert item.status_code == 200, item.content
    assert item.json()["custom_metadata"] == {}
    assert meta.status_code == 200, meta.content
    assert meta.json()["custom_metadata"] == {}


@pytest.mark.django_db
def test_v2_hides_custom_metadata_from_anonymous(sample_product: Product) -> None:  # noqa: F811
    sample_product.is_public = True
    sample_product.custom_metadata = {"cost-centre": "CC-1042"}
    sample_product.save()

    response = Client().get(f"/api/v2/products/{sample_product.id}")

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {}


@pytest.mark.django_db
def test_any_signed_in_user_sees_custom_metadata_on_a_public_product(
    sample_product: Product,  # noqa: F811
    guest_user: Any,  # noqa: F811
) -> None:
    sample_product.is_public = True
    sample_product.custom_metadata = {"cost-centre": "CC-1042"}
    sample_product.save()
    client = Client()
    client.force_login(guest_user)

    response = client.get(reverse("api-1:get_product", kwargs={"product_id": sample_product.id}))

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {"cost-centre": "CC-1042"}


@pytest.mark.django_db
def test_token_caller_sees_custom_metadata_on_v2(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
) -> None:
    sample_product.custom_metadata = {"owner": "platform-team"}
    sample_product.save()

    response = Client().get(f"/api/v2/products/{sample_product.id}", **get_api_headers(sample_access_token))

    assert response.status_code == 200, response.content
    assert response.json()["custom_metadata"] == {"owner": "platform-team"}
