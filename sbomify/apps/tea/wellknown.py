"""
TEA .well-known/tea server discovery endpoint.

Per RFC 8615 and TEA specification, this endpoint returns metadata about
where TEA API endpoints are available for this domain.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from sbomify.apps.tea.mappers import TEA_API_VERSION


def tea_wellknown(request: HttpRequest) -> JsonResponse:
    """
    RFC 8615 .well-known endpoint for TEA server discovery.

    Returns TEA server metadata for this workspace's custom domain.
    Only available on validated custom domains with TEA enabled.

    Returns:
        JSON response conforming to tea-well-known.schema.json
    """
    # Check if request is from a custom domain
    team = getattr(request, "custom_domain_team", None)
    is_custom_domain = getattr(request, "is_custom_domain", False)

    if not is_custom_domain or not team:
        return JsonResponse({"error": "TEA .well-known is only available on custom domains"}, status=400)

    if not team.custom_domain_validated:
        return JsonResponse({"error": "Custom domain is not validated"}, status=400)

    if not team.tea_enabled:
        return JsonResponse({"error": "TEA is not enabled for this workspace"}, status=404)

    # Build the TEA API URL for this custom domain
    base_url = f"https://{team.custom_domain}/tea/v1"

    return JsonResponse(
        {"schemaVersion": 1, "endpoints": [{"url": base_url, "versions": [TEA_API_VERSION], "priority": 1}]}
    )
