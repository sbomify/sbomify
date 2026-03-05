"""Tests for TEA API response caching."""

from unittest.mock import patch

import pytest
from django.apps import apps
from django.core.cache import cache
from django.test import Client, override_settings

from sbomify.apps.core.models import Component, Release, ReleaseArtifact
from sbomify.apps.tea.cache import get_tea_cache, invalidate_tea_cache, set_tea_cache, tea_cache_key
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.tea.signals import _INVALIDATION_SENDERS

TEA_URL_PREFIX = f"/tea/v{TEA_API_VERSION}"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear cache before and after each test."""
    cache.clear()
    yield
    cache.clear()


class TestCacheHelpers:
    """Unit tests for cache utility functions."""

    def test_tea_cache_key_format(self):
        key = tea_cache_key("ws123", "product", "abc")
        assert key == "tea:ws123:product:abc"

    def test_tea_cache_key_single_part(self):
        key = tea_cache_key("ws123", "discovery")
        assert key == "tea:ws123:discovery"

    @override_settings(TEA_CACHE_TTL=300)
    def test_get_set_cache(self):
        key = tea_cache_key("ws123", "test")
        assert get_tea_cache(key) is None
        set_tea_cache(key, {"data": "value"})
        assert get_tea_cache(key) == {"data": "value"}

    @override_settings(TEA_CACHE_TTL=0)
    def test_ttl_zero_disables_cache(self):
        key = tea_cache_key("ws123", "test")
        set_tea_cache(key, {"data": "value"})
        assert get_tea_cache(key) is None

    @override_settings(TEA_CACHE_TTL=300)
    def test_invalidate_calls_delete_pattern(self):
        """invalidate_tea_cache should call delete_pattern when available."""
        with patch.object(cache, "delete_pattern", create=True) as mock_delete:
            invalidate_tea_cache("ws123")
            mock_delete.assert_called_once_with("tea:ws123:*")

    @override_settings(TEA_CACHE_TTL=300)
    def test_invalidate_skips_when_no_delete_pattern(self):
        """invalidate_tea_cache should not raise when backend lacks delete_pattern."""
        # LocMemCache has no delete_pattern; just verify no exception
        invalidate_tea_cache("ws123")

    @override_settings(TEA_CACHE_TTL=300)
    def test_set_cache_handles_write_failure(self):
        """set_tea_cache should log but not raise on cache backend errors."""
        with patch.object(cache, "set", side_effect=ConnectionError("Redis down")):
            set_tea_cache(tea_cache_key("ws123", "test"), {"data": "value"})

    @override_settings(TEA_CACHE_TTL=300)
    def test_get_cache_handles_read_failure(self):
        """get_tea_cache should return None on cache backend errors."""
        with patch.object(cache, "get", side_effect=ConnectionError("Redis down")):
            assert get_tea_cache(tea_cache_key("ws123", "test")) is None


class TestSignalSendersResolve:
    """Verify all signal sender strings reference real Django models."""

    def test_all_invalidation_senders_are_valid_models(self):
        for sender in _INVALIDATION_SENDERS:
            app_label, model_name = sender.split(".")
            model = apps.get_model(app_label, model_name)
            assert model is not None, f"Signal sender '{sender}' does not resolve to a model"


@pytest.mark.django_db
class TestEndpointCaching:
    """Integration tests verifying cache hits on TEA endpoints."""

    @override_settings(TEA_CACHE_TTL=300)
    def test_get_product_uses_cache(self, tea_enabled_product):
        client = Client()
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}?workspace_key={tea_enabled_product.team.key}"

        # First request — cache miss, populates cache
        resp1 = client.get(url)
        assert resp1.status_code == 200

        # Verify cache key was set
        cache_key = tea_cache_key(tea_enabled_product.team.key, "product", str(tea_enabled_product.uuid))
        assert get_tea_cache(cache_key) is not None

        # Second request — should return same data (from cache)
        resp2 = client.get(url)
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    @override_settings(TEA_CACHE_TTL=300)
    def test_list_products_uses_cache(self, tea_enabled_product):
        client = Client()
        url = f"{TEA_URL_PREFIX}/products?workspace_key={tea_enabled_product.team.key}"

        resp1 = client.get(url)
        assert resp1.status_code == 200

        resp2 = client.get(url)
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    @override_settings(TEA_CACHE_TTL=300)
    def test_get_component_uses_cache(self, tea_enabled_component):
        client = Client()
        url = f"{TEA_URL_PREFIX}/component/{tea_enabled_component.uuid}?workspace_key={tea_enabled_component.team.key}"

        resp1 = client.get(url)
        assert resp1.status_code == 200

        cache_key = tea_cache_key(tea_enabled_component.team.key, "component", str(tea_enabled_component.uuid))
        assert get_tea_cache(cache_key) is not None

    @override_settings(TEA_CACHE_TTL=0)
    def test_cache_disabled_with_ttl_zero(self, tea_enabled_product):
        """When TEA_CACHE_TTL=0, no cache entries should be created."""
        client = Client()
        url = f"{TEA_URL_PREFIX}/product/{tea_enabled_product.uuid}?workspace_key={tea_enabled_product.team.key}"

        client.get(url)

        cache_key = tea_cache_key(tea_enabled_product.team.key, "product", str(tea_enabled_product.uuid))
        assert get_tea_cache(cache_key) is None

    @override_settings(TEA_CACHE_TTL=300)
    def test_error_responses_are_not_cached(self, tea_enabled_product):
        """Non-200 responses should not be cached."""
        client = Client()
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        url = f"{TEA_URL_PREFIX}/product/{fake_uuid}?workspace_key={tea_enabled_product.team.key}"

        resp = client.get(url)
        assert resp.status_code == 404

        cache_key = tea_cache_key(tea_enabled_product.team.key, "product", fake_uuid)
        assert get_tea_cache(cache_key) is None


@pytest.mark.django_db
class TestSignalInvalidation:
    """Tests that model saves trigger cache invalidation signals."""

    @override_settings(TEA_CACHE_TTL=300)
    def test_sbom_save_calls_invalidation(self, tea_conformance_data):
        """Saving an SBOM should call invalidate_tea_cache."""
        team, product, release, component, sbom = tea_conformance_data

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            sbom.name = "updated-sbom"
            sbom.save()
            mock_invalidate.assert_called_with(team.key)

    @override_settings(TEA_CACHE_TTL=300)
    def test_release_save_calls_invalidation(self, tea_conformance_data):
        """Saving a Release should call invalidate_tea_cache."""
        team, product, release, component, sbom = tea_conformance_data

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            release.name = "v2.0.0"
            release.save()
            mock_invalidate.assert_called_with(team.key)

    @override_settings(TEA_CACHE_TTL=300)
    def test_release_artifact_delete_calls_invalidation(self, tea_conformance_data):
        """Deleting a ReleaseArtifact should call invalidate_tea_cache."""
        team, product, release, component, sbom = tea_conformance_data

        artifact = ReleaseArtifact.objects.filter(release=release).first()
        assert artifact is not None

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            artifact.delete()
            mock_invalidate.assert_called_with(team.key)

    @override_settings(TEA_CACHE_TTL=300)
    def test_product_save_calls_invalidation(self, tea_conformance_data):
        """Saving a Product should call invalidate_tea_cache."""
        team, product, release, component, sbom = tea_conformance_data

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            product.name = "Updated Product Name"
            product.save()
            mock_invalidate.assert_called_with(team.key)

    @override_settings(TEA_CACHE_TTL=300)
    def test_component_save_calls_invalidation(self, tea_conformance_data):
        """Saving a Component should call invalidate_tea_cache."""
        team, product, release, component, sbom = tea_conformance_data

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            component.name = "Updated Component Name"
            component.save()
            mock_invalidate.assert_called_with(team.key)

    @override_settings(TEA_CACHE_TTL=300)
    def test_team_save_calls_invalidation(self, tea_conformance_data):
        """Saving a Team should call invalidate_tea_cache (e.g., disabling TEA)."""
        team, product, release, component, sbom = tea_conformance_data

        with patch("sbomify.apps.tea.signals.invalidate_tea_cache") as mock_invalidate:
            team.save()
            mock_invalidate.assert_called_with(team.key)
