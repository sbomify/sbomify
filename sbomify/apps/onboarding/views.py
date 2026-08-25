from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from sbomify.apps.billing.config import is_billing_enabled

if TYPE_CHECKING:
    from sbomify.apps.core.models import User


class OnboardingPlanSelectionView(LoginRequiredMixin, View):
    """Redirects to the wizard's plan step. Kept for backward compatibility with bookmarks/links."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")
        return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")

    def post(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")
        return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")


@method_decorator(csrf_exempt, name="dispatch")
class UnsubscribeView(View):
    """Opt a user out of the onboarding sequence from a link in an email.

    No login required: the signed token in the URL is the proof, and demanding a
    password before someone can stop receiving mail is exactly the pattern
    unsubscribe rules exist to prevent.

    GET only *offers* to unsubscribe, POST performs it. Mail scanners and
    prefetchers follow links in the background, so a GET that acted would opt
    people out who never clicked. RFC 8058 one-click clients POST, which this
    accepts directly, hence the CSRF exemption: the request comes from a mail
    provider that has no session or token, and the signed URL is the credential.
    """

    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        user = self._user_for(token)
        if user is None:
            return render(request, "onboarding/unsubscribe.html.j2", {"invalid": True}, status=400)

        # Read-only on purpose. get_or_create here would let a link-scanning
        # proxy create a status row for a user who has none, and since the drip
        # clock falls back to created_at when drip_started_at is unset, that row
        # would start the sequence from today.
        from .models import OnboardingStatus

        status = OnboardingStatus.objects.filter(user=user).first()
        return render(
            request,
            "onboarding/unsubscribe.html.j2",
            {
                "already": status.drip_unsubscribed if status else False,
                "email": user.email,
                "token": token,
            },
        )

    def post(self, request: HttpRequest, token: str) -> HttpResponse:
        user = self._user_for(token)
        if user is None:
            return render(request, "onboarding/unsubscribe.html.j2", {"invalid": True}, status=400)

        from .models import OnboardingStatus

        # The row is created here rather than on GET because this is a real
        # opt-out: someone with no status row still has to be recorded as
        # unsubscribed, or the next drip eligibility check would create one and
        # mail them.
        status, _ = OnboardingStatus.objects.get_or_create(user=user)
        status.unsubscribe_from_drip()
        return render(
            request,
            "onboarding/unsubscribe.html.j2",
            {"done": True, "email": user.email},
        )

    @staticmethod
    def _user_for(token: str) -> User | None:
        """The user a signed token names, or None if it is not ours."""
        from sbomify.apps.core.models import User

        from .utils import read_unsubscribe_token

        user_id = read_unsubscribe_token(token)
        if user_id is None:
            return None
        return User.objects.filter(pk=user_id).first()
