"""Editing a product or component tells the workspace, so open inventories repaint.

The inventory page already listens for ``product_updated`` and
``component_updated``; these pin that the edit endpoints send them, and only
once the change is committed.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_component,
    sample_product,
)


def _edit(url: str, method: str, body: dict[str, Any], token: Any) -> Any:
    send = getattr(Client(), method)
    return send(url, json.dumps(body), content_type="application/json", **get_api_headers(token))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("patch", {"name": "renamed product"}),
        ("put", {"name": "renamed product", "is_public": True}),
    ],
)
def test_editing_a_product_broadcasts_to_the_workspace(
    method: str,
    body: dict[str, Any],
    sample_product: Any,  # noqa: F811
    sample_access_token: Any,  # noqa: F811
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse(f"api-1:{'patch' if method == 'patch' else 'update'}_product", args=[sample_product.id])

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = _edit(url, method, body, sample_access_token)

    assert response.status_code == 200, response.content
    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args.kwargs["workspace_key"] == sample_product.team.key
    assert mock_broadcast.call_args.kwargs["message_type"] == "product_updated"
    assert mock_broadcast.call_args.kwargs["data"] == {"product_id": str(sample_product.id), "name": "renamed product"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("patch", {"name": "renamed component"}),
        ("put", {"name": "renamed component", "is_global": False}),
    ],
)
def test_editing_a_component_broadcasts_to_the_workspace(
    method: str,
    body: dict[str, Any],
    sample_component: Any,  # noqa: F811
    sample_access_token: Any,  # noqa: F811
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse(f"api-1:{'patch' if method == 'patch' else 'update'}_component", args=[sample_component.id])

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = _edit(url, method, body, sample_access_token)

    assert response.status_code == 200, response.content
    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args.kwargs["message_type"] == "component_updated"
    assert mock_broadcast.call_args.kwargs["data"] == {
        "component_id": str(sample_component.id),
        "name": "renamed component",
    }


@pytest.mark.django_db
def test_a_rejected_edit_broadcasts_nothing(
    sample_component: Any,  # noqa: F811
    sample_access_token: Any,  # noqa: F811
    django_capture_on_commit_callbacks: Any,
) -> None:
    url = reverse("api-1:patch_component", args=[sample_component.id])

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = _edit(url, "patch", {"name": ""}, sample_access_token)

    assert response.status_code >= 400
    mock_broadcast.assert_not_called()
