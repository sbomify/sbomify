"""CSAF 2.0 discovery endpoints under ``/.well-known/csaf/``.

Gating is deliberately the same three checks ``SecurityTxtView`` makes, in the
same order: a custom-domain or trust-center context, a public workspace, and a
validated domain for BYOD. A workspace that may not serve a ``security.txt``
may not advertise a CSAF provider either, and keeping the two rules identical
means they cannot drift apart into a gap.

Everything served here is TLP:WHITE for every reader; see ``csaf_provider``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views import View

from sbomify.apps.core.url_utils import build_custom_domain_url, get_base_url
from sbomify.apps.plugins.utils import get_sbomify_version
from sbomify.apps.security_advisories import csaf_provider


class _WellKnownCsafView(View):
    """Resolve the workspace from the domain, or refuse."""

    def _team(self, request: HttpRequest) -> Any:
        if not getattr(request, "is_custom_domain", False):
            return None
        team = getattr(request, "custom_domain_team", None)
        if not team or not team.is_public:
            return None
        if not getattr(request, "is_trust_center_subdomain", False) and not getattr(
            team, "custom_domain_validated", False
        ):
            return None
        return team

    def _base_url(self, request: HttpRequest, team: Any) -> str:
        # Absolute URLs are mandatory in CSAF, and the document is fetched by
        # its canonical hostname, so the workspace's own domain comes first.
        base = build_custom_domain_url(team, "/", request.is_secure()) or get_base_url() or ""
        return base.rstrip("/")

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> JsonResponse:
        response = JsonResponse(payload, status=status)
        # The document is the same for everyone, but access to it is revocable:
        # a re-embargo, a deletion or a workspace turning private has to take
        # effect now. A shared cache holding it would keep serving withdrawn
        # content, and the stored marker cannot reach a cache that never asks
        # again. Every request re-evaluates the ACL instead.
        response["Cache-Control"] = "no-store"
        return response

    def _not_found(self) -> JsonResponse:
        return self._json({"error": "Not found"}, status=404)


class ProviderMetadataView(_WellKnownCsafView):
    """``/.well-known/csaf/provider-metadata.json`` — CSAF 2.0 section 7.1.8."""

    def get(self, request: HttpRequest) -> JsonResponse:
        team = self._team(request)
        if team is None:
            return self._not_found()
        return self._json(csaf_provider.provider_metadata(team, base_url=self._base_url(request, team)))


class WhiteFeedView(_WellKnownCsafView):
    """``/.well-known/csaf/white/feed-tlp-white.json`` — the ROLIE feed."""

    def get(self, request: HttpRequest) -> JsonResponse:
        team = self._team(request)
        if team is None:
            return self._not_found()
        return self._json(csaf_provider.rolie_feed(team, base_url=self._base_url(request, team)))


class WhiteDocumentView(_WellKnownCsafView):
    """One TLP:WHITE CSAF document, at the filename CSAF 2.0 section 5.1 requires."""

    def get(self, request: HttpRequest, year: str, filename: str) -> JsonResponse:
        team = self._team(request)
        if team is None:
            return self._not_found()
        document = csaf_provider.white_document(
            team,
            year,
            filename,
            base_url=self._base_url(request, team),
            generator=get_sbomify_version(),
        )
        if document is None:
            return self._not_found()
        return self._json(document)
