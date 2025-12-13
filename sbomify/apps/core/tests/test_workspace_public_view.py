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


@pytest.mark.django_db
def test_workspace_public_page_renders_css_variables():
    """Test that valid branding colors render correctly with RGB values."""
    client = Client()
    brand_color = "#123456"
    accent_color = "#654321"
    team = Team.objects.create(
        name="Branded Workspace",
        is_public=True,
        branding_info={
            "brand_color": brand_color,
            "accent_color": accent_color,
            "branding_enabled": True,
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Check for CSS variables
    assert f"--brand-color: {brand_color}" in content
    assert f"--accent-color: {accent_color}" in content

    # Check for pre-computed RGB values
    assert "--brand-color-rgb: 18, 52, 86" in content
    assert "--accent-color-rgb: 101, 67, 33" in content

    # Check for Bootstrap overrides
    assert "--bs-primary: var(--accent-color)" in content


@pytest.mark.django_db
def test_workspace_public_rejects_xss_in_brand_color():
    """XSS attempt via brand color should be sanitized to fallback."""
    client = Client()
    team = Team.objects.create(
        name="Evil Corp",
        is_public=True,
        branding_info={
            "brand_color": "#000; } </style><script>alert('xss')</script><style>",
            "accent_color": "#6366f1",
            "branding_enabled": True,
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Should not inject script tag
    assert "<script>" not in content
    assert "alert('xss')" not in content

    # Should fall back to default brand color (better UX than gray)
    assert "--brand-color: #4f46e5" in content


@pytest.mark.django_db
def test_workspace_public_sanitizes_malformed_hex_colors():
    """Malformed hex colors should fall back to defaults."""
    client = Client()
    team = Team.objects.create(
        name="Malformed Colors Workspace",
        is_public=True,
        branding_info={
            "brand_color": "#zzzzzz",  # Invalid hex
            "accent_color": "12345",  # Missing #
            "branding_enabled": True,
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Should fall back to defaults (brand colors, not gray)
    assert "--brand-color: #4f46e5" in content
    assert "--accent-color: #7c8b9d" in content


@pytest.mark.django_db
def test_workspace_public_handles_none_colors():
    """None/empty color values should use defaults."""
    client = Client()
    team = Team.objects.create(
        name="No Colors Workspace",
        is_public=True,
        branding_info={
"brand_color": "",
            "accent_color": "",
            "branding_enabled": True,
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Should use defaults
    assert "--brand-color: #4f46e5" in content
    assert "--accent-color: #7c8b9d" in content
