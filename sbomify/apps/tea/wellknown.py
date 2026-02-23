"""
TEA .well-known/tea server discovery endpoint.

Per RFC 8615 and TEA specification, this endpoint returns metadata about
where TEA API endpoints are available for this domain.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views import View

from sbomify.apps.tea.mappers import TEA_API_VERSION, build_tea_server_url
from sbomify.apps.tea.schemas import TEAWellKnownEndpoint, TEAWellKnownResponse
from sbomify.logging import getLogger

log = getLogger(__name__)


class TEAWellKnownView(View):
    """RFC 8615 .well-known endpoint for TEA server discovery.

    Returns TEA server metadata for this workspace's custom domain.
    Only available on validated custom domains with TEA enabled.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """Handle GET request for TEA .well-known discovery."""
        team = getattr(request, "custom_domain_team", None)
        is_custom_domain = getattr(request, "is_custom_domain", False)

        if not is_custom_domain or not team:
            log.info("Well-known: request is not on a custom domain")
            return JsonResponse({"error": "TEA .well-known is only available on custom domains"}, status=400)

        if not team.custom_domain_validated:
            log.warning("Well-known: custom domain not validated (key=%s)", team.key)
            return JsonResponse({"error": "Custom domain is not validated"}, status=400)

        if not team.is_public:
            log.warning("Well-known: workspace not public (key=%s)", team.key)
            return JsonResponse({"error": "TEA is not available for this workspace"}, status=404)

        if not team.tea_enabled:
            log.info("Well-known: TEA not enabled (key=%s)", team.key)
            return JsonResponse({"error": "TEA is not enabled for this workspace"}, status=403)

        if not team.custom_domain:
            log.warning("Well-known: custom domain not configured (key=%s)", team.key)
            return JsonResponse({"error": "Custom domain is not configured"}, status=400)

        base_url = build_tea_server_url(team, request=request)

        response = TEAWellKnownResponse(
            schemaVersion=1,
            endpoints=[
                TEAWellKnownEndpoint(
                    url=base_url,
                    versions=[TEA_API_VERSION],
                    priority=1,
                )
            ],
        )

        return JsonResponse(response.model_dump())
