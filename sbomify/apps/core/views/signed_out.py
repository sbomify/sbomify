from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView


class SignedOutView(TemplateView):
    """Where a sign-out lands when the identity provider cannot end its own session.

    Sending the browser to the login URL instead would go straight back to the
    provider, whose session is still live, and sign the user in again without a
    click. Someone who is signed in has nothing to see here, so they go home.
    """

    template_name = "core/signed_out.html.j2"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("core:home")
        return super().get(request, *args, **kwargs)
