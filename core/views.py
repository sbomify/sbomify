from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import redirect, render
from django.urls import reverse

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token

from .errors import error_response
from .forms import CreateAccessTokenForm


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    return redirect("social:begin", backend="auth0")


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    context = {"current_team": request.session.get("current_team", {})}
    return render(request, "core/dashboard.html", context)


@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    create_access_token_form = CreateAccessTokenForm()
    context = dict(create_access_token_form=create_access_token_form)

    if request.method == "POST":
        form = CreateAccessTokenForm(request.POST)
        if form.is_valid():
            access_token_str = create_personal_access_token(request.user)
            token = AccessToken(
                encoded_token=access_token_str,
                user=request.user,
                description=form.cleaned_data["description"],
            )
            token.save()

            context["new_encoded_access_token"] = access_token_str
            messages.add_message(
                request,
                messages.INFO,
                "New access token created",
            )

    access_tokens = AccessToken.objects.filter(user=request.user).only("id", "description", "created_at").all()
    context["access_tokens"] = access_tokens
    return render(request, "core/settings.html", context)


@login_required
def delete_access_token(request: HttpRequest, token_id: int):
    try:
        token = AccessToken.objects.get(pk=token_id)

        if token.user_id != request.user.id:
            return error_response(request, HttpResponseForbidden("Not allowed"))

        messages.add_message(
            request,
            messages.INFO,
            "Access token removed",
        )
        token.delete()

    except AccessToken.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Access token not found"))

    return redirect(reverse("core:settings"))


@login_required
def logout(request: HttpRequest) -> HttpResponse:
    django_logout(request)
    domain = settings.SOCIAL_AUTH_AUTH0_DOMAIN
    client_id = settings.SOCIAL_AUTH_AUTH0_KEY

    return_to = settings.APP_BASE_URL

    redirect_url = f"https://{domain}/v2/logout?client_id={client_id}&returnTo={return_to}"

    return redirect(redirect_url)
