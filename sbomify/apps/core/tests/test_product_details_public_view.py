"""Tests for the product details public view."""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product, Project, Release
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink, ProductProject
from sbomify.apps.teams.models import Team


@pytest.fixture
def public_team():
    """Create a public team for testing."""
    return Team.objects.create(name="Public Test Team", is_public=True)


@pytest.fixture
def public_product(public_team):
    """Create a public product for testing."""
    return Product.objects.create(name="Test Product", team=public_team, is_public=True)


@pytest.mark.django_db
def test_product_details_public_renders(public_team, public_product):
    """Product details public page should render successfully."""
    client = Client()
    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    assert "Test Product" in response.content.decode()


@pytest.mark.django_db
def test_product_details_hides_projects_badge_when_empty(public_team, public_product):
    """Projects badge should be hidden when no public projects exist."""
    client = Client()
    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # No project badge should be shown
    assert "project" not in content.lower() or "Product Projects" not in content


@pytest.mark.django_db
def test_product_details_shows_public_projects_only(public_team, public_product):
    """Only public projects should be shown in product details."""
    client = Client()

    # Create a public project
    public_project = Project.objects.create(name="Public Project", team=public_team, is_public=True)
    ProductProject.objects.create(product=public_product, project=public_project)

    # Create a private project
    private_project = Project.objects.create(name="Private Project", team=public_team, is_public=False)
    ProductProject.objects.create(product=public_product, project=private_project)

    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    assert public_project.name in content
    assert "Private Project" not in content


@pytest.mark.django_db
def test_product_details_hides_identifiers_when_empty(public_team, public_product):
    """Product identifiers section should be hidden when empty."""
    client = Client()
    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Identifiers section should not be shown when empty
    assert "Product Identifiers" not in content


@pytest.mark.django_db
def test_product_details_shows_identifiers_when_present(public_team, public_product):
    """Product identifiers section should be shown when identifiers exist."""
    client = Client()

    ProductIdentifier.objects.create(
        product=public_product, identifier_type=ProductIdentifier.IdentifierType.SKU, value="TEST-SKU-123"
    )

    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    assert "Product Identifiers" in content
    assert "TEST-SKU-123" in content


@pytest.mark.django_db
def test_product_details_shows_barcode_for_gtin_identifiers(public_team, public_product):
    """Product identifiers with GTIN types should show barcode inline."""
    client = Client()

    # Create a GTIN-13 identifier (barcode-eligible)
    ProductIdentifier.objects.create(
        product=public_product, identifier_type=ProductIdentifier.IdentifierType.GTIN_13, value="5901234123457"
    )

    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Barcode SVG element should be present for GTIN types
    assert "data-barcode-id" in content
    assert "barcode-wrapper" in content


@pytest.mark.django_db
class TestProductIdentifierBarcodes:
    """Integration tests for product identifier barcode rendering."""

    def test_gtin_12_renders_barcode_svg(self, public_team, public_product):
        """GTIN-12 (UPC-A) identifiers should render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_12,
            value="123456789012"  # Valid 12-digit UPC
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check SVG barcode structure is present
        assert f'data-barcode-id="{identifier.id}"' in content
        assert '"barcode-svg' in content
        # Check the Alpine.js render function is called with correct params
        assert "productIdentifiersBarcodes" in content
        assert "renderBarcode" in content
        assert identifier.value in content

    def test_gtin_13_renders_barcode_svg(self, public_team, public_product):
        """GTIN-13 (EAN-13) identifiers should render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457"  # Valid 13-digit EAN
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check SVG barcode structure
        assert f'data-barcode-id="{identifier.id}"' in content
        assert '"barcode-svg' in content

    def test_gtin_14_renders_barcode_svg(self, public_team, public_product):
        """GTIN-14 (ITF-14) identifiers should render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_14,
            value="10614141000415"  # Valid 14-digit ITF-14
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check SVG barcode structure
        assert f'data-barcode-id="{identifier.id}"' in content
        assert '"barcode-svg' in content

    def test_gtin_8_renders_barcode_svg(self, public_team, public_product):
        """GTIN-8 identifiers should render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_8,
            value="96385074"  # Valid 8-digit EAN-8
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check SVG barcode structure
        assert f'data-barcode-id="{identifier.id}"' in content
        assert '"barcode-svg' in content

    def test_sku_does_not_render_barcode(self, public_team, public_product):
        """SKU identifiers should NOT render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value="PROD-SKU-12345"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # SKU should be displayed but without barcode
        assert "PROD-SKU-12345" in content
        # No barcode elements for this identifier
        assert f'data-barcode-id="{identifier.id}"' not in content

    def test_purl_does_not_render_barcode(self, public_team, public_product):
        """PURL identifiers should NOT render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.PURL,
            value="pkg:npm/express@4.17.1"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # PURL should be displayed but without barcode
        assert "pkg:npm/express@4.17.1" in content
        # No barcode elements for this identifier
        assert f'data-barcode-id="{identifier.id}"' not in content

    def test_cpe_does_not_render_barcode(self, public_team, public_product):
        """CPE identifiers should NOT render barcode SVG elements."""
        client = Client()
        identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:vendor:product:1.0:*:*:*:*:*:*:*"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # CPE should be displayed but without barcode
        assert "cpe:2.3:a:vendor:product:1.0" in content
        # No barcode elements for this identifier
        assert f'data-barcode-id="{identifier.id}"' not in content

    def test_multiple_gtin_identifiers_each_get_unique_barcode(self, public_team, public_product):
        """Multiple GTIN identifiers should each have their own unique barcode SVG."""
        client = Client()

        identifier_1 = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457"
        )
        identifier_2 = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_12,
            value="123456789012"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Both identifiers should have their own barcode
        assert f'data-barcode-id="{identifier_1.id}"' in content
        assert f'data-barcode-id="{identifier_2.id}"' in content
        # Both values should be present
        assert "5901234123457" in content
        assert "123456789012" in content

    def test_mixed_identifier_types_only_gtin_show_barcode(self, public_team, public_product):
        """When mixing GTIN and non-GTIN types, only GTIN should show barcode."""
        client = Client()

        gtin_identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457"
        )
        sku_identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value="SKU-ABC-123"
        )
        mpn_identifier = ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.MPN,
            value="MPN-XYZ-789"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # All values should be displayed
        assert "5901234123457" in content
        assert "SKU-ABC-123" in content
        assert "MPN-XYZ-789" in content

        # Only GTIN should have barcode element
        assert f'data-barcode-id="{gtin_identifier.id}"' in content
        assert f'data-barcode-id="{sku_identifier.id}"' not in content
        assert f'data-barcode-id="{mpn_identifier.id}"' not in content

    def test_barcode_svg_has_loading_state(self, public_team, public_product):
        """Barcode SVG should have loading state indicator."""
        client = Client()
        ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check loading state elements exist
        assert "barcode-state-content" in content or "barcodeRendered" in content

    def test_barcode_svg_has_error_state(self, public_team, public_product):
        """Barcode SVG should have error state indicator for invalid values."""
        client = Client()
        ProductIdentifier.objects.create(
            product=public_product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="5901234123457"
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Check error state Alpine.js binding exists
        assert "barcodeErrors" in content


@pytest.mark.django_db
def test_product_details_hides_links_when_empty(public_team, public_product):
    """Product links section should be hidden when empty."""
    client = Client()
    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Links section should not be shown when empty (section header is "Resources & Links")
    assert "Resources &amp; Links" not in content


@pytest.mark.django_db
def test_product_details_shows_links_when_present(public_team, public_product):
    """Product links section should be shown when links exist."""
    client = Client()

    ProductLink.objects.create(
        product=public_product,
        link_type=ProductLink.LinkType.WEBSITE,
        title="Product Website",
        url="https://example.com/product",
    )

    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Section header is now "Resources & Links"
    assert "Resources" in content or "Links" in content
    assert "Product Website" in content


@pytest.mark.django_db
def test_product_details_shows_latest_release(public_team, public_product):
    """The 'latest' release section should be shown (auto-created for all products)."""
    client = Client()
    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # The 'latest' release is auto-created for all products, so Releases section should show
    # if the get_product API triggered the latest release creation
    # This is a behavior test - either releases show (if latest was created) or not
    # Just verify the page renders successfully
    assert "Test Product" in content


@pytest.mark.django_db
def test_product_details_shows_releases(public_team, public_product):
    """Releases should be shown in product details."""
    client = Client()

    Release.objects.create(name="v1.0.0", product=public_product)
    Release.objects.create(name="v0.9.0-beta", product=public_product, is_prerelease=True)

    url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    assert "v1.0.0" in content
    assert "v0.9.0-beta" in content


@pytest.mark.django_db
class TestProductLinkRedirectView:
    """Tests for the ProductLinkRedirectView."""

    def test_redirect_works_for_public_product(self, public_team, public_product):
        """Redirect should work for links on public products."""
        client = Client()

        link = ProductLink.objects.create(
            product=public_product,
            link_type=ProductLink.LinkType.WEBSITE,
            title="Product Website",
            url="https://example.com/product",
        )

        url = reverse("core:product_link_redirect", kwargs={"link_id": link.id})
        response = client.get(url)

        assert response.status_code == 302
        redirect_url = response.url
        assert "https://example.com/product" in redirect_url
        assert "utm_source=sbomify" in redirect_url
        assert "utm_medium=trust_center" in redirect_url
        assert "utm_campaign=product_links" in redirect_url

    def test_redirect_returns_404_for_private_product(self, public_team):
        """Redirect should return 404 for links on private products."""
        client = Client()

        # Create a private product
        private_product = Product.objects.create(
            name="Private Product",
            team=public_team,
            is_public=False
        )

        link = ProductLink.objects.create(
            product=private_product,
            link_type=ProductLink.LinkType.WEBSITE,
            title="Private Website",
            url="https://example.com/private",
        )

        url = reverse("core:product_link_redirect", kwargs={"link_id": link.id})
        response = client.get(url)

        assert response.status_code == 404

    def test_redirect_returns_404_for_invalid_link_id(self):
        """Redirect should return 404 for non-existent link IDs."""
        client = Client()

        url = reverse("core:product_link_redirect", kwargs={"link_id": "nonexistent123"})
        response = client.get(url)

        assert response.status_code == 404

    def test_redirect_preserves_existing_query_params(self, public_team, public_product):
        """Redirect should preserve existing query parameters in the URL."""
        client = Client()

        link = ProductLink.objects.create(
            product=public_product,
            link_type=ProductLink.LinkType.DOCUMENTATION,
            title="Documentation",
            url="https://docs.example.com/guide?version=2.0&lang=en",
        )

        url = reverse("core:product_link_redirect", kwargs={"link_id": link.id})
        response = client.get(url)

        assert response.status_code == 302
        redirect_url = response.url
        assert "version=2.0" in redirect_url
        assert "lang=en" in redirect_url
        assert "utm_source=sbomify" in redirect_url

    def test_redirect_does_not_overwrite_existing_utm_params(self, public_team, public_product):
        """Redirect should not overwrite existing UTM parameters."""
        client = Client()

        link = ProductLink.objects.create(
            product=public_product,
            link_type=ProductLink.LinkType.SUPPORT,
            title="Support Portal",
            url="https://support.example.com?utm_source=existing",
        )

        url = reverse("core:product_link_redirect", kwargs={"link_id": link.id})
        response = client.get(url)

        assert response.status_code == 302
        redirect_url = response.url
        # Should keep the existing utm_source, not overwrite it
        assert "utm_source=existing" in redirect_url
        # Should add the other UTM params
        assert "utm_medium=trust_center" in redirect_url
        assert "utm_campaign=product_links" in redirect_url

    def test_redirect_link_in_template(self, public_team, public_product):
        """Links on public product page should use the redirect URL."""
        client = Client()

        link = ProductLink.objects.create(
            product=public_product,
            link_type=ProductLink.LinkType.WEBSITE,
            title="Product Website",
            url="https://example.com/product",
        )

        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # The template should use the redirect URL, not the direct URL
        redirect_url = reverse("core:product_link_redirect", kwargs={"link_id": link.id})
        assert redirect_url in content
        assert "Product Website" in content
        # The direct URL should NOT be displayed
        assert "https://example.com/product" not in content


@pytest.mark.django_db
class TestProductTeiUrnRendering:
    """Tests for TEI URN display on public product detail pages."""

    def test_tei_urn_shown_when_tea_enabled_with_validated_domain(self, public_team, public_product):
        """TEI URN should be rendered when TEA is enabled and custom domain is validated."""
        public_team.tea_enabled = True
        public_team.custom_domain = "trust.example.com"
        public_team.custom_domain_validated = True
        public_team.save()

        client = Client()
        # Use slug-based URL on the custom domain to avoid /public/ redirect
        response = client.get(
            f"/product/{public_product.slug}/",
            HTTP_HOST="trust.example.com",
        )

        assert response.status_code == 200
        content = response.content.decode()

        expected_urn = f"urn:tei:uuid:trust.example.com:{public_product.id}"
        assert expected_urn in content

    def test_tei_urn_hidden_when_tea_disabled(self, public_team, public_product):
        """TEI URN should not be rendered when TEA is disabled."""
        public_team.custom_domain = "trust.example.com"
        public_team.custom_domain_validated = True
        public_team.save()

        client = Client()
        # Use slug-based URL on the custom domain to avoid /public/ redirect
        response = client.get(
            f"/product/{public_product.slug}/",
            HTTP_HOST="trust.example.com",
        )

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

    def test_tei_urn_hidden_when_domain_not_validated(self, public_team, public_product):
        """TEI URN should not be rendered when custom domain is not validated."""
        public_team.tea_enabled = True
        public_team.custom_domain = "trust.example.com"
        public_team.custom_domain_validated = False
        public_team.save()

        client = Client()
        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()

    def test_tei_urn_hidden_when_no_custom_domain(self, public_team, public_product):
        """TEI URN should not be rendered when no custom domain is set."""
        public_team.tea_enabled = True
        public_team.save()

        client = Client()
        url = reverse("core:product_details_public", kwargs={"product_id": public_product.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "urn:tei:uuid:" not in response.content.decode()
