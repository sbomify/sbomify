"""Test public_url_tags template tags."""

import pytest
from django.template import Context, Template
from django.test import RequestFactory

from sbomify.apps.teams.fixtures import sample_team_with_owner_member


@pytest.mark.django_db
class TestWorkspacePublicUrlTag:
    """Test workspace_public_url template tag."""

    def test_workspace_public_url_on_custom_domain(self, sample_team_with_owner_member):
        """Test workspace_public_url returns '/' on custom domains."""
        team = sample_team_with_owner_member.team

        # Mock request on custom domain
        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        template = Template("""
            {% load public_url_tags %}
            {% workspace_public_url as url %}{{ url }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        assert result == "/"

    def test_workspace_public_url_on_main_domain_with_brand(self, sample_team_with_owner_member):
        """Test workspace_public_url returns workspace URL on main domain using brand context."""
        team = sample_team_with_owner_member.team

        # Mock request on main domain
        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = False

        # Provide brand context with workspace_key (as set by build_branding_context)
        brand = {"workspace_key": team.key}

        template = Template("""
            {% load public_url_tags %}
            {% workspace_public_url as url %}{{ url }}
        """)

        context = Context({"request": request, "brand": brand})
        result = template.render(context).strip()

        assert result == f"/public/workspace/{team.key}/"

    def test_workspace_public_url_on_main_domain_with_workspace_context(self, sample_team_with_owner_member):
        """Test workspace_public_url returns workspace URL using workspace context variable."""
        team = sample_team_with_owner_member.team

        # Mock request on main domain
        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = False

        # Provide workspace context (as used by workspace_public view)
        workspace = {"key": team.key, "name": team.name}

        template = Template("""
            {% load public_url_tags %}
            {% workspace_public_url as url %}{{ url }}
        """)

        context = Context({"request": request, "workspace": workspace})
        result = template.render(context).strip()

        assert result == f"/public/workspace/{team.key}/"

    def test_workspace_public_url_without_workspace_info(self):
        """Test workspace_public_url returns empty string when no workspace info available."""
        # Mock request without workspace info
        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = False

        template = Template("""
            {% load public_url_tags %}
            {% workspace_public_url as url %}{{ url }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        # Should return empty string when no workspace info is available
        assert result == ""

    def test_workspace_public_url_without_request(self):
        """Test workspace_public_url returns empty string when no request in context."""
        template = Template("""
            {% load public_url_tags %}
            {% workspace_public_url as url %}{{ url }}
        """)

        context = Context({})
        result = template.render(context).strip()

        # Should return empty string when no request
        assert result == ""


@pytest.mark.django_db
class TestIsOnCustomDomainTag:
    """Test is_on_custom_domain template tag."""

    def test_is_on_custom_domain_true(self, sample_team_with_owner_member):
        """Test is_on_custom_domain returns True when on custom domain."""
        team = sample_team_with_owner_member.team

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        template = Template("""
            {% load public_url_tags %}
            {% is_on_custom_domain as on_custom %}{{ on_custom }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        assert result == "True"

    def test_is_on_custom_domain_false(self):
        """Test is_on_custom_domain returns False when on main domain."""
        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = False

        template = Template("""
            {% load public_url_tags %}
            {% is_on_custom_domain as on_custom %}{{ on_custom }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        assert result == "False"


@pytest.mark.django_db
class TestPublicUrlTag:
    """Test public_url template tag."""

    def test_public_url_workspace_custom_domain(self, sample_team_with_owner_member):
        """Test public_url returns '/' for workspace on custom domain."""
        team = sample_team_with_owner_member.team

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        template = Template("""
            {% load public_url_tags %}
            {% public_url 'core:workspace_public' workspace_key='abc' as url %}{{ url }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        assert result == "/"

    def test_public_url_product_custom_domain(self, sample_team_with_owner_member):
        """Test public_url returns slug-based URL for product on custom domain."""
        team = sample_team_with_owner_member.team

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        template = Template("""
            {% load public_url_tags %}
            {% public_url 'core:product_details_public' product_id='123' product_slug='my-product' as url %}{{ url }}
        """)

        context = Context({"request": request})
        result = template.render(context).strip()

        assert result == "/product/my-product/"

    def test_public_url_product_main_domain(self, sample_team_with_owner_member):
        """Test public_url returns ID-based URL for product on main domain."""
        from sbomify.apps.core.models import Product

        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="Test Product", team=team, is_public=True)

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = False

        template = Template("""
            {% load public_url_tags %}
            {% public_url 'core:product_details_public' product_id=product.id product_slug=product.slug as url %}{{ url }}
        """)

        context = Context({"request": request, "product": product})
        result = template.render(context).strip()

        assert result == f"/public/product/{product.id}/"
