"""Reachable controls pages keep live permission and workspace boundaries."""

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus
from sbomify.apps.core.models import Product, User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", ["owner", "admin", "member", "guest"])
def test_controls_permissions_use_live_membership(
    client: Client, sample_user: User, team_with_business_plan: Team, role: str
) -> None:
    workspace = team_with_business_plan
    setup_authenticated_client_session(client, workspace, sample_user)
    Member.objects.filter(user=sample_user, team=workspace).update(role=role)
    catalog = ControlCatalog.objects.create(team=workspace, name="Audit", version="1")
    control = Control.objects.create(catalog=catalog, control_id="A-1", title="Access review", group="Access")
    product = Product.objects.create(team=workspace, name="Controls product")
    settings_url = reverse("teams:team_settings_tab", args=[workspace.key, "controls"])
    response = client.get(settings_url)
    if role in ("owner", "admin"):
        assert response.status_code == 200
        assert b"Compliance controls" in response.content
    else:
        assert response.status_code in (302, 403)

    response = client.get(reverse("controls:product_controls", args=[workspace.key, product.pk]))
    if role == "guest":
        assert response.status_code in (302, 403)
    else:
        assert response.status_code == 200
        assert b"Access review" in response.content
        assert (b'name="status"' in response.content) == (role != "member")

    for url in (
        reverse("controls:status_update", args=[workspace.key]),
        reverse("controls:product_status_update", args=[workspace.key, product.pk]),
    ):
        response = client.post(url, {"control_id": control.pk, "status": "compliant"}, HTTP_HX_REQUEST="true")
        assert response.status_code == (200 if role in ("owner", "admin") else 403)
    assert ControlStatus.objects.filter(control=control).count() == (2 if role in ("owner", "admin") else 0)


def test_product_controls_reject_foreign_workspace(
    client: Client, sample_user: User, team_with_business_plan: Team, sample_team: Team
) -> None:
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    product = Product.objects.create(team=sample_team, name="Other workspace product")
    response = client.get(reverse("controls:product_controls", args=[team_with_business_plan.key, product.pk]))
    assert response["HX-Reswap"] == "none"
    assert json.loads(response["HX-Trigger"])["messages"][0]["type"] == "error"
    assert b"Other workspace product" not in response.content


def test_bulk_response_stays_on_changed_catalog(
    client: Client, sample_user: User, team_with_business_plan: Team
) -> None:
    workspace = team_with_business_plan
    setup_authenticated_client_session(client, workspace, sample_user)
    target = ControlCatalog.objects.create(team=workspace, name="Target", version="1")
    other = ControlCatalog.objects.create(team=workspace, name="Other", version="1")
    control = Control.objects.create(catalog=target, control_id="T-1", title="Target control", group="Access")
    Control.objects.create(catalog=other, control_id="O-1", title="Other control", group="Access")
    response = client.post(
        reverse("controls:bulk_category_update", args=[workspace.key]),
        {"catalog_id": target.pk, "category": "Access", "status": "partial"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert f'id="controls-table-{target.pk}"'.encode() in response.content
    assert b"Other control" not in response.content
    assert ControlStatus.objects.get(control=control).status == "partial"
    assert not ControlStatus.objects.filter(control__catalog=other).exists()
