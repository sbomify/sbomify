"""Public half of the CRA export keys, so anyone holding a bundle can verify its signature."""

from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.compliance.services.export_signing import public_key_pem


class ExportKeyView(View):
    """``/.well-known/sbomify/export-keys/<kid>.pem``: the current or a retired key, else 404.

    Retired keys stay here because a bundle names the key that signed it and
    must stay verifiable for the ten years Art. 13(15) asks it to be kept.
    """

    def get(self, request: HttpRequest, kid: str) -> HttpResponse:
        pem = public_key_pem(kid)
        if pem is None:
            raise Http404
        response = HttpResponse(pem, content_type="application/x-pem-file")
        response["Cache-Control"] = "public, max-age=3600"
        return response
