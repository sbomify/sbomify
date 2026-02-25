"""
Tests for CustomDomainContextMiddleware.

Tests that the middleware correctly detects custom domains, caches results,
and attaches appropriate context to requests.
"""

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from sbomify.apps.core.middleware import CustomDomainContextMiddleware
from sbomify.apps.teams.models import Team


@pytest.fixture
def middleware():
    """Create middleware instance."""

    def get_response(request):
        return None

    return CustomDomainContextMiddleware(get_response)


@pytest.fixture
def custom_domain_team(db):
    """Create a team with a validated custom domain."""
    team = Team.objects.create(
        name="Test Company",
        billing_plan="business",
        custom_domain="trust.example.com",
        custom_domain_validated=True,
    )
    # Set is_public after creation to bypass the save() override for paid plans
    team.is_public = True
    team.save(update_fields=["is_public"])
    return team


@pytest.fixture
def request_factory():
    """Provide a request factory."""
    return RequestFactory()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestCustomDomainDetection:
    """Test custom domain detection logic."""

    def test_detects_custom_domain(self, middleware, request_factory, custom_domain_team):
        """Test that middleware detects a custom domain."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "trust.example.com"

        # Simulate middleware processing
        is_custom = middleware._is_custom_domain("trust.example.com")
        assert is_custom is True

    def test_main_app_not_custom_domain(self, middleware, request_factory):
        """Test that main app domain is not detected as custom."""
        is_custom = middleware._is_custom_domain("app.sbomify.com")
        assert is_custom is False

    def test_localhost_not_custom_domain(self, middleware, request_factory):
        """Test that localhost is not detected as custom."""
        is_custom = middleware._is_custom_domain("localhost")
        assert is_custom is False

    def test_testserver_not_custom_domain(self, middleware, request_factory):
        """Test that testserver is not detected as custom."""
        is_custom = middleware._is_custom_domain("testserver")
        assert is_custom is False

    def test_nonexistent_domain_not_custom(self, middleware, db):
        """Test that non-existent domain is not detected as custom."""
        is_custom = middleware._is_custom_domain("fake.example.com")
        assert is_custom is False


@pytest.mark.django_db
class TestTeamRetrieval:
    """Test team retrieval for custom domains."""

    def test_gets_team_for_custom_domain(self, middleware, custom_domain_team):
        """Test that middleware retrieves correct team."""
        team = middleware._get_team_for_domain("trust.example.com")
        assert team is not None
        assert team.id == custom_domain_team.id
        assert team.custom_domain == "trust.example.com"

    def test_returns_none_for_nonexistent_domain(self, middleware, db):
        """Test that middleware returns None for non-existent domain."""
        team = middleware._get_team_for_domain("fake.example.com")
        assert team is None

    def test_returns_none_for_main_app_domain(self, middleware):
        """Test that middleware returns None for main app domain."""
        team = middleware._get_team_for_domain("app.sbomify.com")
        assert team is None


@pytest.mark.django_db
class TestRequestAttributes:
    """Test that middleware sets correct attributes on request."""

    def test_sets_custom_domain_attributes(self, middleware, request_factory, custom_domain_team):
        """Test that middleware sets is_custom_domain and custom_domain_team."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "trust.example.com"

        # Process request through middleware
        def get_response(req):
            # Check attributes set by middleware
            assert hasattr(req, "is_custom_domain")
            assert hasattr(req, "custom_domain_team")
            assert req.is_custom_domain is True
            assert req.custom_domain_team is not None
            assert req.custom_domain_team.id == custom_domain_team.id
            return None

        mw = CustomDomainContextMiddleware(get_response)
        mw(request)

    def test_sets_false_for_main_domain(self, middleware, request_factory):
        """Test that middleware sets is_custom_domain=False for main domain."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "app.sbomify.com"

        def get_response(req):
            assert hasattr(req, "is_custom_domain")
            assert hasattr(req, "custom_domain_team")
            assert req.is_custom_domain is False
            assert req.custom_domain_team is None
            return None

        mw = CustomDomainContextMiddleware(get_response)
        mw(request)


@pytest.mark.django_db
class TestCaching:
    """Test caching behavior of middleware."""

    def test_caches_custom_domain_check(self, middleware, custom_domain_team):
        """Test that custom domain check is cached."""
        # First call - should hit database
        is_custom1 = middleware._is_custom_domain("trust.example.com")
        assert is_custom1 is True

        # Check that it's cached
        cache_key = "is_custom_domain:trust.example.com"
        cached_value = cache.get(cache_key)
        assert cached_value is True

        # Second call - should use cache
        is_custom2 = middleware._is_custom_domain("trust.example.com")
        assert is_custom2 is True

    def test_caches_team_retrieval(self, middleware, custom_domain_team):
        """Test that team retrieval is cached."""
        # First call - should hit database
        team1 = middleware._get_team_for_domain("trust.example.com")
        assert team1 is not None

        # Check that team ID is cached
        cache_key = "custom_domain_team:trust.example.com"
        cached_team_id = cache.get(cache_key)
        assert cached_team_id == custom_domain_team.id

        # Second call - should use cache
        team2 = middleware._get_team_for_domain("trust.example.com")
        assert team2 is not None
        assert team2.id == team1.id

    def test_cache_miss_queries_db(self, middleware, custom_domain_team):
        """Test that cache miss triggers database query."""
        # Clear any existing cache
        cache.delete("is_custom_domain:trust.example.com")
        cache.delete("custom_domain_team:trust.example.com")

        # This should query the database and cache the result
        is_custom = middleware._is_custom_domain("trust.example.com")
        assert is_custom is True

        # Verify it's now cached
        cached_value = cache.get("is_custom_domain:trust.example.com")
        assert cached_value is True

    def test_stale_cache_cleared(self, middleware, custom_domain_team, db):
        """Test that stale cache is cleared if team is deleted."""
        # Cache the team
        team = middleware._get_team_for_domain("trust.example.com")
        assert team is not None

        # Delete the team
        team_id = team.id
        Team.objects.filter(id=team_id).delete()

        # Try to get team again - cache has old ID but team is gone
        team2 = middleware._get_team_for_domain("trust.example.com")
        # Should return None since team doesn't exist
        assert team2 is None


@pytest.mark.django_db
class TestAutoValidation:
    """Test auto-validation of custom domains."""

    def test_auto_validates_unvalidated_domain(self, request_factory, db):
        """Test that middleware auto-validates an unvalidated custom domain."""
        team = Team.objects.create(
            name="Unvalidated Co",
            billing_plan="business",
            custom_domain="unvalidated.example.com",
            custom_domain_validated=False,
        )

        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "unvalidated.example.com"

        def get_response(req):
            # By the time the response handler runs, the team should be validated
            assert req.custom_domain_team.custom_domain_validated is True
            return None

        mw = CustomDomainContextMiddleware(get_response)
        mw(request)

        # Verify the DB was updated
        team.refresh_from_db()
        assert team.custom_domain_validated is True
        assert team.custom_domain_verification_failures == 0

    def test_skips_already_validated_domain(self, request_factory, custom_domain_team):
        """Test that middleware does not write to DB for already-validated domains."""
        # Fixture creates team with validated=True, last_checked_at=None
        assert custom_domain_team.custom_domain_last_checked_at is None

        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "trust.example.com"

        def get_response(req):
            return None

        mw = CustomDomainContextMiddleware(get_response)
        mw(request)

        # If _auto_validate_domain had run, it would have set last_checked_at.
        # Verify no DB write occurred by checking it remains None.
        custom_domain_team.refresh_from_db()
        assert custom_domain_team.custom_domain_validated is True
        assert custom_domain_team.custom_domain_last_checked_at is None


@pytest.mark.django_db
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_port_in_host(self, middleware, request_factory, custom_domain_team):
        """Test that middleware handles host with port."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = "trust.example.com:8000"

        # normalize_host should remove port
        from sbomify.apps.teams.utils import normalize_host

        host = normalize_host(request.META["HTTP_HOST"])
        assert host == "trust.example.com"

        # Should still detect as custom domain
        is_custom = middleware._is_custom_domain(host)
        assert is_custom is True

    def test_handles_uppercase_domain(self, middleware, db):
        """Test that middleware handles uppercase domains."""
        # Create team with lowercase domain
        Team.objects.create(
            name="Test",
            custom_domain="UPPER.EXAMPLE.COM".lower(),  # Stored lowercase
            custom_domain_validated=True,
        )

        # Query with uppercase should still work (after normalization)
        from sbomify.apps.teams.utils import normalize_host

        host = normalize_host("UPPER.EXAMPLE.COM")
        is_custom = middleware._is_custom_domain(host)
        assert is_custom is True

    def test_handles_empty_host(self, middleware):
        """Test that middleware handles empty host gracefully."""
        is_custom = middleware._is_custom_domain("")
        assert is_custom is False

    def test_multiple_teams_different_domains(self, middleware, db):
        """Test that middleware distinguishes between different custom domains."""
        team1 = Team.objects.create(
            name="Team 1",
            custom_domain="team1.example.com",
            custom_domain_validated=True,
        )
        team2 = Team.objects.create(
            name="Team 2",
            custom_domain="team2.example.com",
            custom_domain_validated=True,
        )

        # Get team for each domain
        retrieved_team1 = middleware._get_team_for_domain("team1.example.com")
        retrieved_team2 = middleware._get_team_for_domain("team2.example.com")

        assert retrieved_team1.id == team1.id
        assert retrieved_team2.id == team2.id
        assert retrieved_team1.id != retrieved_team2.id
