"""Public setup instructions and an explicit, session-authenticated token action."""

from pathlib import Path
from typing import cast

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.core.models import User
from sbomify.apps.core.services.repository_setup import create_setup_credential


class SetupCredentialForm(forms.Form):
    previous_id = forms.IntegerField(required=False, min_value=1)


@method_decorator(never_cache, name="dispatch")
class RepositorySetupTokenView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, workspace_key: str) -> JsonResponse:
        form = SetupCredentialForm(request.POST)
        if not form.is_valid():
            return JsonResponse({"detail": "Invalid setup token."}, status=400)
        result = create_setup_credential(cast(User, request.user), workspace_key, form.cleaned_data["previous_id"])
        if not result.ok:
            return JsonResponse({"detail": result.error}, status=result.status_code or 400)
        return JsonResponse(result.value or {})


class RepositorySetupInstructionsView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        instructions = Path(__file__).resolve().parent.parent / "data" / "repository-setup.md"
        return HttpResponse(instructions.read_text(), content_type="text/plain; charset=utf-8")
