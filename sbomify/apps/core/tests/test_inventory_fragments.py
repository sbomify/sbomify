"""Inventory result requests retain the surrounding page and filter controls."""

import re

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_result_request_returns_only_results(
    client: Client, sample_team_with_owner_member: Member, mocker: MockerFixture, kind: str
) -> None:
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    response = client.get(
        reverse("core:products_dashboard"),
        {"view": kind, "search": "example", "sort": "name", "direction": "desc"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="inventory-content-results",
    )
    assert response.status_code == 200
    assert b'id="inventory-content-results"' in response.content
    assert re.search(rb'name="direction"\s+value="desc"', response.content)
    assert b"<html" not in response.content
    assert b"<form" not in response.content
    assert b'aria-label="Product inventory"' not in response.content
    assert "HX-Target" in response["Vary"]
