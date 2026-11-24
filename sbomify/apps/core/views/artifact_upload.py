from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.services.artifact_upload import upload_targets
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ArtifactUploadView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Pick the component an upload is for, then open its upload dialog.

    One candidate needs no choice, so it redirects straight to the dialog.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        result = upload_targets(request, request.GET.get("type", ""))
        if not result.ok or result.value is None:
            status = result.status_code or 403
            return error_response(request, HttpResponse(result.error, status=status))
        rows = result.value["rows"]
        if len(rows) == 1:
            return redirect(rows[0]["url"])
        return render(request, "core/artifact_upload.html.j2", result.value)
