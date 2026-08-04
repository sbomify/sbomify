import html

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product
from sbomify.apps.sboms.models import ProductComponent
from sbomify.apps.teams.models import Member, Team


@pytest.mark.django_db
def test_workspace_public_page_renders_products_and_global_artifacts():
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Create a product with a public component (required for product to be shown)
    product = Product.objects.create(name="Public Product", team=team, is_public=True)
    component = Component.objects.create(
        name="Public Component",
        team=team,
        visibility=Component.Visibility.PUBLIC,
    )
    ProductComponent.objects.create(product=product, component=component)

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

    # The malicious XSS payload should not be present in the output
    assert "alert('xss')" not in content
    # The malicious script injection should be blocked
    assert "</style><script>" not in content

    # Should fall back to default brand color (better UX than gray)
    assert "--brand-color: #25293F" in content


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
    assert "--brand-color: #25293F" in content
    assert "--accent-color: #4263EB" in content


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
    assert "--brand-color: #25293F" in content
    assert "--accent-color: #4263EB" in content


@pytest.mark.django_db
def test_workspace_public_hides_products_with_no_public_components():
    """Products with 0 public components should not be shown."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Product with no components
    Product.objects.create(name="Empty Product", team=team, is_public=True)

    # Product with private component only
    product_with_private = Product.objects.create(name="Private Components Only", team=team, is_public=True)
    private_component = Component.objects.create(
        name="Private Component", team=team, visibility=Component.Visibility.PRIVATE
    )
    ProductComponent.objects.create(product=product_with_private, component=private_component)

    # Product with public component (should be shown)
    product_with_public = Product.objects.create(name="Has Public Component", team=team, is_public=True)
    public_component = Component.objects.create(
        name="Public Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    ProductComponent.objects.create(product=product_with_public, component=public_component)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Only the product with public components should be shown
    assert "Empty Product" not in content
    assert "Private Components Only" not in content
    assert "Has Public Component" in content


@pytest.mark.django_db
def test_workspace_public_hides_products_section_when_empty():
    """Products section should be hidden when there are no products with public components."""
    client = Client()
    team = Team.objects.create(name="Public Workspace", is_public=True)

    # Create a product with no public components
    product = Product.objects.create(name="Empty Product", team=team, is_public=True)
    private_component = Component.objects.create(
        name="Private Component", team=team, visibility=Component.Visibility.PRIVATE
    )
    ProductComponent.objects.create(product=product, component=private_component)

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

    # Add a product with public component to make the page have some content
    product = Product.objects.create(name="Public Product", team=team, is_public=True)
    public_component = Component.objects.create(
        name="Public Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    ProductComponent.objects.create(product=product, component=public_component)

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
    public_component = Component.objects.create(
        name="Public Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    ProductComponent.objects.create(product=product, component=public_component)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Custom description should be shown
    assert custom_description in content
    # Default description should not be shown
    assert "Security advisories, software bills of materials, and compliance artifacts" not in content


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
    public_component = Component.objects.create(
        name="Public Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    ProductComponent.objects.create(product=product, component=public_component)

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))

    assert response.status_code == 200
    content = response.content.decode()

    # Default description should be shown
    assert "Security advisories, software bills of materials, and compliance artifacts" in content


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


# --- the "enable vulnerability scanning" admin prompt -------------------------
#
# It links into workspace settings, so it must only reach someone who can act on
# it: a signed-in owner or admin *of the workspace being viewed*. The trust
# centre is a public page, so every other viewer — anonymous, a signed-in
# stranger, a guest, and an admin of some other workspace — must not see it.

ADMIN_PROMPT = "Enable vulnerability scanning to show security status on your products"


def _public_workspace(name: str) -> Team:
    """A public workspace with one public product, so the page renders its sections."""
    team = Team.objects.create(name=name, is_public=True)
    product = Product.objects.create(name=f"{name} Product", team=team, is_public=True)
    component = Component.objects.create(
        name=f"{name} Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    ProductComponent.objects.create(product=product, component=component)
    return team


def _visit(team: Team, user=None) -> str:
    client = Client()
    if user is not None:
        client.force_login(user)
    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))
    assert response.status_code == 200
    return response.content.decode()


@pytest.mark.django_db
def test_scanning_prompt_hidden_from_anonymous_visitors():
    assert ADMIN_PROMPT not in _visit(_public_workspace("Anon Workspace"))


@pytest.mark.django_db
def test_scanning_prompt_shown_to_an_owner_of_the_workspace_viewed(sample_user):
    team = _public_workspace("Owner Workspace")
    Member.objects.create(team=team, user=sample_user, role="owner")
    assert ADMIN_PROMPT in _visit(team, sample_user)


@pytest.mark.django_db
def test_scanning_prompt_shown_to_an_admin_of_the_workspace_viewed(sample_user):
    team = _public_workspace("Admin Workspace")
    Member.objects.create(team=team, user=sample_user, role="admin")
    assert ADMIN_PROMPT in _visit(team, sample_user)


@pytest.mark.django_db
def test_scanning_prompt_hidden_from_a_signed_in_non_member(sample_user):
    """Being logged in is not the same as having anything to do with this workspace."""
    assert ADMIN_PROMPT not in _visit(_public_workspace("Stranger Workspace"), sample_user)


@pytest.mark.django_db
def test_scanning_prompt_hidden_from_a_guest_member(sample_user):
    """A guest cannot reach workspace settings, so the prompt would be a dead end."""
    team = _public_workspace("Guest Workspace")
    Member.objects.create(team=team, user=sample_user, role="guest")
    assert ADMIN_PROMPT not in _visit(team, sample_user)


@pytest.mark.django_db
def test_scanning_prompt_hidden_when_admin_of_a_different_workspace(sample_user):
    """The check is per-workspace, not "is this person an admin somewhere".

    Owning workspace A must not surface A's settings link on B's trust centre.
    """
    own = _public_workspace("My Workspace")
    Member.objects.create(team=own, user=sample_user, role="owner")
    other = _public_workspace("Someone Elses Workspace")

    assert ADMIN_PROMPT in _visit(own, sample_user)
    assert ADMIN_PROMPT not in _visit(other, sample_user)


@pytest.mark.django_db
def test_scanning_prompt_hidden_once_a_scanner_is_enabled(sample_user):
    from sbomify.apps.plugins.models import TeamPluginSettings

    team = _public_workspace("Scanning Workspace")
    Member.objects.create(team=team, user=sample_user, role="owner")
    TeamPluginSettings.objects.create(team=team, enabled_plugins=["osv"])

    assert ADMIN_PROMPT not in _visit(team, sample_user)
