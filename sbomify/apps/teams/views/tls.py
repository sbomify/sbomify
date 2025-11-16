"""TLS verification endpoint for Caddy on-demand TLS.

This endpoint is called by Caddy to determine if SSL certificates should be issued
for a given hostname.

IMPORTANT SECURITY NOTE:
This endpoint MUST NOT be exposed to the public internet. Access should be restricted
at the Caddy/reverse proxy level to only allow internal requests from Caddy itself.

Example Caddy configuration:
    @tls_internal {
        path /_tls/*
    }
    handle @tls_internal {
        # Only allow internal/Docker network access
        # Public internet traffic should never reach this endpoint
    }
"""

import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from sbomify.apps.teams.models import CustomDomain
from sbomify.apps.teams.utils import verify_custom_domain_dns
from sbomify.logging import getLogger

logger = getLogger(__name__)

# Rate limiting configuration
RATE_LIMIT_WINDOW = getattr(settings, "TLS_RATE_LIMIT_WINDOW", 60)  # seconds
MAX_REQUESTS_PER_MINUTE = getattr(settings, "TLS_MAX_REQUESTS_PER_MINUTE", 100)
MAX_REQUESTS_PER_DOMAIN = getattr(settings, "TLS_MAX_REQUESTS_PER_DOMAIN", 10)


def _check_rate_limit(hostname: str, client_ip: str) -> tuple[bool, str | None]:
    """Check rate limits for TLS verification requests.

    Implements two types of rate limiting:
    1. Per-IP rate limit (prevents abuse from single source)
    2. Per-domain rate limit (prevents excessive verification attempts)

    Args:
        hostname: The domain being verified
        client_ip: The client IP address

    Returns:
        Tuple of (is_allowed, error_message)
    """
    now = time.time()

    # Check per-IP rate limit
    ip_key = f"tls_rate_limit_ip_{client_ip}"
    ip_requests = cache.get(ip_key, [])
    ip_requests = [req_time for req_time in ip_requests if now - req_time < RATE_LIMIT_WINDOW]

    if len(ip_requests) >= MAX_REQUESTS_PER_MINUTE:
        logger.warning(f"[TLS] Rate limit exceeded for IP {client_ip}")
        return False, f"Rate limit exceeded: {MAX_REQUESTS_PER_MINUTE} requests per minute"

    # Check per-domain rate limit
    domain_key = f"tls_rate_limit_domain_{hostname}"
    domain_requests = cache.get(domain_key, [])
    domain_requests = [req_time for req_time in domain_requests if now - req_time < RATE_LIMIT_WINDOW]

    if len(domain_requests) >= MAX_REQUESTS_PER_DOMAIN:
        logger.warning(f"[TLS] Rate limit exceeded for domain {hostname}")
        return False, f"Rate limit exceeded for domain: {MAX_REQUESTS_PER_DOMAIN} attempts per minute"

    # Update rate limit counters
    ip_requests.append(now)
    domain_requests.append(now)
    cache.set(ip_key, ip_requests, RATE_LIMIT_WINDOW)
    cache.set(domain_key, domain_requests, RATE_LIMIT_WINDOW)

    return True, None


@csrf_exempt
@require_GET
def tls_allow_host(request: HttpRequest) -> HttpResponse:
    """Caddy on-demand TLS verification endpoint.

    This endpoint is called by Caddy with a 'domain' query parameter.
    Returns 200 if the domain should be allowed, 403 if it should be denied.

    SECURITY: This endpoint must be protected by Caddy configuration to prevent
    public access. Only Caddy itself should be able to call this endpoint.

    A domain is allowed if:
    1. It exists in CustomDomain table
    2. It is verified (is_verified=True)
    3. It is active (is_active=True)
    4. Its DNS CNAME still points to APP_BASE_URL domain (optional real-time check)

    Query parameters:
        domain: The hostname to check (e.g., trust.example.com)

    Returns:
        200 OK: Allow certificate issuance
        403 Forbidden: Deny certificate issuance
        400 Bad Request: Missing or invalid parameters
        429 Too Many Requests: Rate limit exceeded
    """
    # Get the hostname from query parameter
    hostname = request.GET.get("domain")

    if not hostname:
        logger.warning("[TLS] No domain parameter provided")
        return HttpResponse("Missing domain parameter", status=400)

    # Get client IP for rate limiting and logging
    client_ip = request.META.get("REMOTE_ADDR", "unknown")

    # Rate limiting
    is_allowed, error_msg = _check_rate_limit(hostname, client_ip)
    if not is_allowed:
        logger.warning(f"[TLS] Rate limit exceeded for {hostname} from {client_ip}")
        return HttpResponse(error_msg, status=429)

    logger.info(f"[TLS] Checking if certificate issuance allowed for: {hostname} (from {client_ip})")

    try:
        # Check if domain exists in database
        custom_domain = CustomDomain.objects.select_related("team").get(hostname=hostname)

        # Check if domain is active
        if not custom_domain.is_active:
            logger.info(f"[TLS] DENY: Domain {hostname} is not active (workspace: {custom_domain.team.name})")
            return HttpResponse("Domain is not active", status=403)

        # Check if domain is verified
        if not custom_domain.is_verified:
            logger.info(f"[TLS] DENY: Domain {hostname} is not verified (workspace: {custom_domain.team.name})")
            return HttpResponse("Domain is not verified", status=403)

        # Optionally perform real-time DNS check (can be disabled for performance)
        check_dns_realtime = getattr(settings, "TLS_VERIFY_DNS_REALTIME", True)

        if check_dns_realtime:
            if not verify_custom_domain_dns(hostname):
                logger.warning(
                    f"[TLS] DENY: Domain {hostname} DNS verification failed (workspace: {custom_domain.team.name})"
                )
                return HttpResponse("DNS verification failed", status=403)

        # All checks passed - allow certificate issuance
        logger.info(
            f"[TLS] ALLOW: Certificate issuance approved for {hostname} "
            f"(workspace: {custom_domain.team.name}, workspace_key: {custom_domain.team.key})"
        )
        return HttpResponse("OK", status=200)

    except CustomDomain.DoesNotExist:
        logger.info(f"[TLS] DENY: Domain {hostname} not found in database")
        return HttpResponse("Domain not found", status=403)

    except Exception as e:
        logger.error(f"[TLS] Error checking domain {hostname}: {e}", exc_info=True)
        return HttpResponse("Internal error", status=403)
