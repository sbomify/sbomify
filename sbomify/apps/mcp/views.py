"""The one Django view the MCP server has: its OAuth discovery document."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views import View

from . import oauth


class ProtectedResourceMetadataView(View):
    """RFC 9728 metadata for ``/mcp``: which authorization server to sign in with, and for what scope.

    An MCP client fetches it from the URL in the 401's ``WWW-Authenticate``
    challenge. It is public, like the authorization server's own metadata.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        return JsonResponse(oauth.protected_resource_metadata())
