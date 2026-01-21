import html

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.sboms.models import ProductProject
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
def test_workspace_public_page_renders_products_and_global_artifacts():
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Create a product with a public project (required for product to be shown)
    product = Product.objects.create(name="Public Product", team=team, is_public=True)
    project = Project.objects.create(name="Public Project", team=team, is_public=True)
    ProductProject.objects.create(product=product, project=project)

    Component.objects.create(
        name="Global Artifact",
        team=team,
        visibility=Component.Visibility.PUBLIC,
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


@pytest.mark.django_db
def test_workspace_public_hides_products_with_no_public_projects():
    """Products with 0 public projects should not be shown."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Product with no projects
    Product.objects.create(name="Empty Product", team=team, is_public=True)

    # Product with private project only
    product_with_private = Product.objects.create(name="Private Projects Only", team=team, is_public=True)
    private_project = Project.objects.create(name="Private Project", team=team, is_public=False)
    ProductProject.objects.create(product=product_with_private, project=private_project)

    # Product with public project (should be shown)
    product_with_public = Product.objects.create(name="Has Public Project", team=team, is_public=True)
    public_project = Project.objects.create(name="Public Project", team=team, is_public=True)
    ProductProject.objects.create(product=product_with_public, project=public_project)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Only the product with public projects should be shown
    assert "Empty Product" not in content
    assert "Private Projects Only" not in content
    assert "Has Public Project" in content


@pytest.mark.django_db
def test_workspace_public_hides_products_section_when_empty():
    """Products section should be hidden when there are no products with public projects."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Create a product with no public projects
    product = Product.objects.create(name="Empty Product", team=team, is_public=True)
    private_project = Project.objects.create(name="Private Project", team=team, is_public=False)
    ProductProject.objects.create(product=product, project=private_project)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Section header should not be shown when there are no products
    assert "Public Products" not in content


@pytest.mark.django_db
def test_workspace_public_hides_artifacts_section_when_empty():
    """Organization Compliance Artifacts section should be hidden when empty."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Section header should not be shown when there are no global artifacts
    assert "Organization Compliance Artifacts" not in content


@pytest.mark.django_db
def test_workspace_public_hides_compliance_artifacts_badge_when_zero():
    """Compliance Artifacts badge in hero should be hidden when count is 0."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Add a product with public project to make the page have some content
    product = Product.objects.create(name="Public Product", team=team, is_public=True)
    public_project = Project.objects.create(name="Public Project", team=team, is_public=True)
    ProductProject.objects.create(product=product, project=public_project)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # "Compliance Artifact" badge text should not appear when count is 0
    assert "Compliance Artifact" not in content


@pytest.mark.django_db
def test_workspace_public_uses_configurable_description():
    """Trust center description should be configurable via branding info."""
    client = Client()
    custom_description = "Welcome to our custom trust center! Browse our SBOMs and compliance docs."
    team = Team.objects.create(
        name="Custom Description Workspace",
        is_public=True,
        branding_info={
            "trust_center_description": custom_description,
        },
    )

    # Add content so the page renders
    product = Product.objects.create(name="Product", team=team, is_public=True)
    public_project = Project.objects.create(name="Project", team=team, is_public=True)
    ProductProject.objects.create(product=product, project=public_project)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Custom description should be shown
    assert custom_description in content
    # Default description should not be shown
    assert "Your centralized hub for transparency and compliance" not in content


@pytest.mark.django_db
def test_workspace_public_uses_default_description_when_empty():
    """Trust center should use default description when no custom description is set."""
    client = Client()
    team = Team.objects.create(
        name="Default Description Workspace",
        is_public=True,
        branding_info={},
    )

    # Add content so the page renders
    product = Product.objects.create(name="Product", team=team, is_public=True)
    public_project = Project.objects.create(name="Project", team=team, is_public=True)
    ProductProject.objects.create(product=product, project=public_project)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Default description should be shown
    assert "Your centralized hub for transparency and compliance" in content


@pytest.mark.django_db
def test_workspace_public_og_image_uses_absolute_url():
    """og:image meta tag must contain an absolute URL for social media crawlers."""
    import re

    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # og:image must be an absolute URL (starts with http)
    # The meta tag may span multiple lines, so use regex with DOTALL
    og_image_pattern = r'property="og:image"\s+content="(http[^"]+)"'
    match = re.search(og_image_pattern, content)
    assert match, "og:image meta tag with absolute URL not found"
    og_image_url = match.group(1)

    # Should use the default social image (sbomify-social.png)
    assert "sbomify-social.png" in og_image_url
    # Should NOT use a relative path
    assert og_image_url.startswith("http")


@pytest.mark.django_db
def test_workspace_public_twitter_image_uses_absolute_url():
    """twitter:image meta tag must contain an absolute URL for social media crawlers."""
    import re

    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # twitter:image must be an absolute URL (starts with http)
    # The meta tag may span multiple lines, so use regex with DOTALL
    twitter_image_pattern = r'property="twitter:image"\s+content="(http[^"]+)"'
    match = re.search(twitter_image_pattern, content)
    assert match, "twitter:image meta tag with absolute URL not found"
    twitter_image_url = match.group(1)

    # Should use the default social image (sbomify-social.png)
    assert "sbomify-social.png" in twitter_image_url


@pytest.mark.django_db
def test_workspace_public_og_image_uses_custom_brand_image_when_absolute():
    """og:image should use custom brand image when it's an absolute URL."""
    import re

    client = Client()
    team = Team.objects.create(
        name="Branded Workspace",
        is_public=True,
        branding_info={
            "logo": "custom-logo.png",  # This will be converted to absolute URL by _build_media_url
            "branding_enabled": True,
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Should use the custom brand image (absolute URL from S3)
    expected_brand_url = f"{settings.AWS_MEDIA_STORAGE_BUCKET_URL}/custom-logo.png"
    og_image_pattern = r'property="og:image"\s+content="([^"]+)"'
    match = re.search(og_image_pattern, content)
    assert match, "og:image meta tag not found"
    og_image_url = match.group(1)
    assert og_image_url == expected_brand_url
    # Should NOT fall back to default social image
    assert "sbomify-social.png" not in og_image_url


@pytest.mark.django_db
def test_workspace_public_og_image_fallback_when_brand_image_relative():
    """og:image should fall back to default when brand_image is a relative path."""
    import re

    client = Client()
    # Workspace with branding_enabled but no custom logo/icon
    # This results in brand_image being the relative default path
    team = Team.objects.create(
        name="Partial Branding Workspace",
        is_public=True,
        branding_info={
            "brand_color": "#123456",
            "branding_enabled": True,
            # No logo or icon set - brand_image will be relative default
        },
    )

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Should still use the absolute fallback URL (not the relative brand_image)
    og_image_pattern = r'property="og:image"\s+content="(http[^"]+)"'
    match = re.search(og_image_pattern, content)
    assert match, "og:image meta tag with absolute URL not found"
    og_image_url = match.group(1)

    # Should use the default social image
    assert "sbomify-social.png" in og_image_url
    # Should NOT use relative path
    assert og_image_url.startswith("http")
