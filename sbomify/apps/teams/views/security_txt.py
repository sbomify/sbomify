"""RFC 9116 security.txt endpoint.

Serves a generated security.txt at /.well-known/security.txt for workspaces
that have it enabled. Team is resolved from the request by the
CustomDomainContextMiddleware (custom domain or trust center subdomain).
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.teams.services.security_txt import generate_security_txt
from sbomify.logging import getLogger

logger = getLogger(__name__)


class SecurityTxtView(View):
    """Serve RFC 9116 security.txt for the resolved workspace."""

    def get(self, request: HttpRequest) -> HttpResponse:
        team = getattr(request, "custom_domain_team", None)

        if not team or not team.is_public:
            return HttpResponse(status=404)

        content = generate_security_txt(team)
        if not content:
            return HttpResponse(status=404)

        return HttpResponse(content, content_type="text/plain; charset=utf-8")
