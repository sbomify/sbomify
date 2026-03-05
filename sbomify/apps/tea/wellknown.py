"""
TEA .well-known/tea server discovery endpoint.

Per RFC 8615 and TEA specification, this endpoint returns metadata about
where TEA API endpoints are available for this domain.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views import View

from sbomify.apps.tea.cache import cache_origin, get_tea_cache, set_tea_cache, tea_cache_key
from sbomify.apps.tea.mappers import TEA_API_VERSION, build_tea_server_url
from sbomify.apps.tea.schemas import TEAWellKnownEndpoint, TEAWellKnownResponse
from sbomify.logging import getLogger

log = getLogger(__name__)


class TEAWellKnownView(View):
    """RFC 8615 .well-known endpoint for TEA server discovery.

    Returns TEA server metadata for this workspace's preferred public domain
    (custom domain or trust center subdomain). Only available when TEA is enabled.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """Handle GET request for TEA .well-known discovery."""
        team = getattr(request, "custom_domain_team", None)
        is_custom_domain = getattr(request, "is_custom_domain", False)

        if not is_custom_domain or not team:
            log.info("Well-known: request is not on a preferred public domain")
            return JsonResponse(
                {"error": "TEA .well-known is only available on custom domains or trust center subdomains"}, status=400
            )

        is_trust_center_subdomain = getattr(request, "is_trust_center_subdomain", False)
        if not is_trust_center_subdomain and not team.custom_domain_validated:
            log.warning("Well-known: custom domain not validated (key=%s)", team.key)
            return JsonResponse({"error": "Custom domain is not validated"}, status=400)

        if not team.is_public:
            log.warning("Well-known: workspace not public (key=%s)", team.key)
            return JsonResponse({"error": "TEA is not available for this workspace"}, status=404)

        if not team.tea_enabled:
            log.info("Well-known: TEA not enabled (key=%s)", team.key)
            return JsonResponse({"error": "TEA is not enabled for this workspace"}, status=403)

        if not is_trust_center_subdomain and not team.custom_domain:
            log.warning("Well-known: custom domain not configured (key=%s)", team.key)
            return JsonResponse({"error": "Custom domain is not configured"}, status=400)

        cache_key = tea_cache_key(team.key, cache_origin(request), "wellknown")
        cached = get_tea_cache(cache_key)
        if cached is not None:
            return JsonResponse(cached)

        base_url = build_tea_server_url(team, request=request)

        response = TEAWellKnownResponse(
            schema_version=1,
            endpoints=(
                TEAWellKnownEndpoint(
                    url=base_url,
                    versions=(TEA_API_VERSION,),
                    priority=1.0,
                ),
            ),
        )

        try:
            response_data = response.model_dump(by_alias=True)
        except Exception:
            log.exception("Failed to serialize TEA well-known response for workspace %s", team.key)
            return JsonResponse({"error": "Internal server error"}, status=500)

        set_tea_cache(cache_key, response_data)
        return JsonResponse(response_data)
