from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.documents.services.reader_access import list_reader_access_requests


class TrustCenterAccessView(LoginRequiredMixin, View):
    """The Trust Centers the signed-in user has requested access to.

    Not behind ``GuestAccessBlockedMixin``: the people this page is for are
    mostly guests, and their current workspace is often the one they asked.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        result = list_reader_access_requests(request.user, secure=request.is_secure())
        if not result.ok:
            return error_response(request, HttpResponse(status=result.status_code or 400, content=result.error))
        return render(request, "core/trust_center_access.html.j2", {"access_requests": result.value})
