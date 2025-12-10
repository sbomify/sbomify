import ipaddress
import logging

from django.http import HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin

from sbomify.apps.core.utils import get_client_ip
from sbomify.apps.teams.utils import normalize_host

logger = logging.getLogger(__name__)


class DynamicHostValidationMiddleware:
    """
    Validate Host headers dynamically using Redis-backed cache.

    Performance:
    - Static hosts: O(1) in-memory set lookup (no cache/DB hit)
    - Cached domains: Single Redis GET (microseconds)
    - Cache miss: Single DB query, then cached for 1 hour

    The vast majority of requests hit Redis cache with no DB access.

    Note: This replaces the incompatible DynamicAllowedHosts approach.
    Django 4.0+ requires ALLOWED_HOSTS to be a plain list, so we use
    middleware for dynamic validation instead.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Static hosts checked in-memory (no cache/DB hit)
        self.static_hosts = frozenset(
            [
                "sbomify-backend",
                "localhost",
                "127.0.0.1",
                "testserver",
            ]
        )

        # Parse APP_BASE_URL once at initialization instead of on first request
        self._app_host = None
        try:
            from urllib.parse import urlparse

            from django.conf import settings

            if settings.APP_BASE_URL:
                self._app_host = urlparse(settings.APP_BASE_URL).hostname
        except (ImportError, AttributeError, ValueError) as e:
            # During tests or early startup, settings might not be ready
            # or APP_BASE_URL might be malformed
            logger.debug(f"Could not parse APP_BASE_URL during middleware init: {e}")

    def __call__(self, request):
        host = self.get_host_from_request(request)

        if not self.is_valid_host(host):
            logger.warning(f"Invalid host header rejected: {host}")
            return HttpResponseBadRequest("Invalid host header")

        return self.get_response(request)

    def get_host_from_request(self, request):
        """
        Extract and normalize the host from the request.

        Normalization performed:
        - Strips any port from the host (e.g., 'example.com:8000' -> 'example.com')
        - Converts the host to lowercase

        Returns:
            str: The normalized, lowercased hostname with any port removed.
        """
        return normalize_host(request.get_host())

    def is_valid_host(self, host):
        """
        Check if host is allowed with three-tier validation:
        1. Static hosts (in-memory set) - instant
        2. APP_BASE_URL check (parsed once at init) - instant
        3. Redis cache - microseconds
        4. Database query - only on cache miss

        Security: IP addresses are only allowed in the static hosts list.
        Custom domains must be FQDNs, not IPs.
        """
        # Tier 1: Static hosts (O(1) set lookup, no external calls)
        # These can include IPs for internal/development use
        if host in self.static_hosts:
            return True

        # Tier 2: Check APP_BASE_URL (parsed once at init, simple comparison)
        if self._app_host and host == self._app_host:
            return True

        # Security check: Reject IP addresses for custom domains
        # Custom domains must be FQDNs only
        if self._is_ip_address(host):
            logger.warning(f"Rejected IP address in Host header: {host}")
            return False

        # Tier 3: Custom domains (Redis cache + DB fallback)
        return self._check_custom_domain(host)

    def _is_ip_address(self, host: str) -> bool:
        """
        Check if host is an IP address (IPv4 or IPv6).

        Returns:
            bool: True if host is an IP address, False otherwise.
        """
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def _check_custom_domain(self, host):
        """
        Check if a custom domain is allowed, using Redis-backed caching.

        Returns:
            bool: True if the domain is allowed, False otherwise.

        Caching behavior:
        - Valid domains are cached for 24 hours (86400 seconds).
        - Invalid domains are cached for 5 minutes (300 seconds).

        Cache is explicitly invalidated when domains are added/removed/updated
        via the API (see invalidate_custom_domain_cache in teams.utils).
        """
        from django.core.cache import cache

        cache_key = f"allowed_host:{host}"

        # Try Redis cache first
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss - query database
        from sbomify.apps.teams.models import Team

        exists = Team.objects.filter(custom_domain=host).exists()

        # Cache result for 24 hours (valid domains) or 5 min (invalid)
        # Valid domains cached aggressively since they rarely change
        # Cache is invalidated explicitly when domains change
        # Invalid domains cached shorter to allow quick addition of new domains
        ttl = 86400 if exists else 300
        cache.set(cache_key, exists, ttl)

        return exists


class RealIPMiddleware(MiddlewareMixin):
    """
    Middleware to correct the REMOTE_ADDR using X-Real-IP header set by Caddy.

    This ensures that logging, Sentry, and views see the correct client IP.
    """

    def process_request(self, request):
        client_ip = get_client_ip(request)
        if client_ip:
            request.META["REMOTE_ADDR"] = client_ip
