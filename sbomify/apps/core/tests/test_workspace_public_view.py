import html

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
def test_workspace_public_page_renders_products_and_global_artifacts():
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    Product.objects.create(name="Public Product", team=team, is_public=True)
    Component.objects.create(
        name="Global Artifact",
        team=team,
        is_public=True,
        is_global=True,
        component_type=Component.ComponentType.DOCUMENT,
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Public Product" in content
    assert "Global Artifact" in content


@pytest.mark.django_db
def test_workspace_public_page_returns_404_when_workspace_private():
    client = Client()
    team = Team.objects.create(name="Private Workspace", billing_plan="business", is_public=False)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 404


@pytest.mark.django_db
def test_workspace_public_page_uses_display_name_for_title():
    client = Client()
    team = Team.objects.create(name="Aurangzaib's Workspace", is_public=True)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = html.unescape(response.content.decode())
    # display_name strips "'s Workspace" suffix, so it becomes "Aurangzaib"
    # Title format is "<name> Trust Center"
    assert "Aurangzaib Trust Center" in content
    assert "Workspace Trust Center" not in content


@pytest.mark.django_db
def test_workspace_public_page_prefers_logo_when_available():
    client = Client()
    team = Team.objects.create(
        name="Public Workspace",
        is_public=True,
        branding_info={
            "icon": "workspace-icon.png",
            "logo": "workspace-logo.png",
            "brand_color": "",
            "accent_color": "",
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()
    expected_logo_url = (
        f"{settings.AWS_MEDIA_STORAGE_BUCKET_URL}/workspace-logo.png"
    )
    assert expected_logo_url in content
    assert "img/sbomify.svg" not in content
