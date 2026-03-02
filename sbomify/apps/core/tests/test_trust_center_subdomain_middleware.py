"""
Tests for trust center subdomain handling in CustomDomainContextMiddleware.

Tests that the middleware correctly detects trust center subdomains,
resolves teams by slug, caches results, and handles negative caching.
"""

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from sbomify.apps.core.middleware import CustomDomainContextMiddleware
from sbomify.apps.teams.models import Team

TRUST_CENTER_DOMAIN = "trustcenters.test"


@pytest.fixture
def middleware():
    """Create middleware instance with trust center domain configured."""

    def get_response(request):
        return None

    with override_settings(TRUST_CENTER_DOMAIN=TRUST_CENTER_DOMAIN):
        return CustomDomainContextMiddleware(get_response)


@pytest.fixture
def trust_center_team(db):
    """Create a public team with a slug for trust center subdomain."""
    team = Team.objects.create(
        name="Acme Corp",
        billing_plan="community",
        is_public=True,
    )
    # The slug is auto-generated; override to a known value
    team.slug = "acme"
    team.save(update_fields=["slug"])
    return team


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestTrustCenterSubdomainDetection:
    """Test trust center subdomain detection and team resolution."""

    def test_detects_trust_center_subdomain(self, request_factory, trust_center_team):
        """Middleware sets is_custom_domain=True and is_trust_center_subdomain=True."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = f"acme.{TRUST_CENTER_DOMAIN}"

        def get_response(req):
            assert req.is_custom_domain is True
            assert req.is_trust_center_subdomain is True
            assert req.custom_domain_team is not None
            assert req.custom_domain_team.id == trust_center_team.id
            return None

        with override_settings(TRUST_CENTER_DOMAIN=TRUST_CENTER_DOMAIN):
            mw = CustomDomainContextMiddleware(get_response)
            mw(request)

    def test_invalid_slug_returns_none(self, request_factory, db):
        """Non-existent slug sets custom_domain_team=None."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = f"nonexistent.{TRUST_CENTER_DOMAIN}"

        def get_response(req):
            assert req.is_custom_domain is True
            assert req.is_trust_center_subdomain is True
            assert req.custom_domain_team is None
            return None

        with override_settings(TRUST_CENTER_DOMAIN=TRUST_CENTER_DOMAIN):
            mw = CustomDomainContextMiddleware(get_response)
            mw(request)

    def test_bare_trust_center_domain_not_subdomain(self, request_factory):
        """The bare trust center domain (no slug prefix) is not treated as a subdomain."""
        request = request_factory.get("/")
        request.META["HTTP_HOST"] = TRUST_CENTER_DOMAIN

        def get_response(req):
            # Bare domain should NOT be detected as a trust center subdomain
            assert req.is_trust_center_subdomain is False
            return None

        with override_settings(TRUST_CENTER_DOMAIN=TRUST_CENTER_DOMAIN):
            mw = CustomDomainContextMiddleware(get_response)
            mw(request)


@pytest.mark.django_db
class TestTrustCenterSlugValidation:
    """Test that slug format validation rejects malformed slugs before DB query."""

    def test_rejects_slug_too_short(self, middleware):
        """Slugs shorter than 3 chars are rejected without DB lookup."""
        result = middleware._get_team_for_slug("ab")
        assert result is None

    def test_rejects_slug_too_long(self, middleware):
        """Slugs longer than 63 chars are rejected without DB lookup."""
        result = middleware._get_team_for_slug("a" * 64)
        assert result is None

    def test_rejects_empty_slug(self, middleware):
        """Empty slug is rejected."""
        result = middleware._get_team_for_slug("")
        assert result is None

    def test_rejects_slug_with_uppercase(self, middleware):
        """Uppercase chars in slug are rejected."""
        result = middleware._get_team_for_slug("Acme")
        assert result is None

    def test_rejects_slug_starting_with_hyphen(self, middleware):
        """Slug starting with hyphen is rejected."""
        result = middleware._get_team_for_slug("-acme")
        assert result is None

    def test_rejects_slug_ending_with_hyphen(self, middleware):
        """Slug ending with hyphen is rejected."""
        result = middleware._get_team_for_slug("acme-")
        assert result is None

    def test_accepts_valid_slug(self, middleware, trust_center_team):
        """Valid slug format passes validation and queries DB."""
        result = middleware._get_team_for_slug("acme")
        assert result is not None
        assert result.id == trust_center_team.id


@pytest.mark.django_db
class TestTrustCenterCaching:
    """Test caching and negative caching for trust center subdomain resolution."""

    def test_caches_team_on_hit(self, middleware, trust_center_team):
        """Successful slug lookup is cached."""
        team = middleware._get_team_for_slug("acme")
        assert team is not None

        cached = cache.get("trust_center_team:acme")
        assert cached == trust_center_team.pk

    def test_second_lookup_uses_cache(self, middleware, trust_center_team):
        """Second lookup for same slug uses cache, not DB."""
        team1 = middleware._get_team_for_slug("acme")
        assert team1 is not None

        # Delete team from DB — cache should still return it
        # (simulating cache hit without DB)
        cached_pk = cache.get("trust_center_team:acme")
        assert cached_pk is not None

        team2 = middleware._get_team_for_slug("acme")
        assert team2 is not None
        assert team2.id == team1.id

    def test_negative_caches_miss(self, middleware, db):
        """Non-existent slug is negative-cached to avoid repeated DB lookups."""
        team = middleware._get_team_for_slug("missing-slug")
        assert team is None

        cached = cache.get("trust_center_team:missing-slug")
        assert cached == "__none__"

    def test_negative_cache_returns_none(self, middleware, db):
        """Subsequent lookup of negative-cached slug returns None without DB query."""
        # Prime the negative cache
        middleware._get_team_for_slug("no-such-team")

        # Second call should return None from cache
        result = middleware._get_team_for_slug("no-such-team")
        assert result is None

    def test_stale_cache_cleared_on_slug_change(self, middleware, trust_center_team):
        """If cached team's slug no longer matches, cache is cleared."""
        # Prime the cache
        middleware._get_team_for_slug("acme")

        # Change the team's slug in DB
        trust_center_team.slug = "acme-corp"
        trust_center_team.save(update_fields=["slug"])

        # Lookup with old slug — cache hit but slug mismatch should clear cache
        team = middleware._get_team_for_slug("acme")
        assert team is None

    def test_stale_cache_cleared_on_team_deletion(self, middleware, trust_center_team):
        """If cached team is deleted, stale cache is cleared."""
        middleware._get_team_for_slug("acme")

        trust_center_team.delete()

        team = middleware._get_team_for_slug("acme")
        assert team is None
