"""Workspace-owner UI for managing OIDC trusted-publisher bindings.

All three views render HTMX partials (no full-page reloads). The
list partial is the source of truth for what the user sees, and
both create + delete return the refreshed list so the page state
matches the database in one round-trip.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.oidc.forms import OIDCBindingForm
from sbomify.apps.oidc.github_api import GitHubResolveError, resolve_repository
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


def _get_component_with_crud(request: HttpRequest, component_id: str) -> Component | None:
    """Return the component IF the request user can CRUD it, else None."""
    from sbomify.apps.core.utils import verify_item_access

    component = Component.objects.filter(pk=component_id).select_related("team").first()
    if component is None:
        return None
    if not verify_item_access(request, component, ["owner", "admin"]):
        return None
    return component


def _list_context(component: Component) -> dict[str, Any]:
    """Context dict for the bindings-list partial."""
    return {
        "component": component,
        "bindings": (
            OIDCBinding.objects.filter(component=component).select_related("created_by").order_by("-created_at")
        ),
        "form": OIDCBindingForm(),
    }


class TrustedPublishersView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """GET: render the section partial. POST: create a binding."""

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        component = _get_component_with_crud(request, component_id)
        if component is None:
            return htmx_error_response("Component not found or insufficient permissions.")
        return render(request, "oidc/_trusted_publishers_section.html.j2", _list_context(component))

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        component = _get_component_with_crud(request, component_id)
        if component is None:
            return htmx_error_response("Component not found or insufficient permissions.")

        form = OIDCBindingForm(request.POST)
        if not form.is_valid():
            # Render the section with form errors visible
            ctx = _list_context(component)
            ctx["form"] = form
            return render(
                request,
                "oidc/_trusted_publishers_section.html.j2",
                ctx,
                status=400,
            )

        repository_slug = form.cleaned_data["repository"]
        provider = form.cleaned_data["provider"]

        # Resolve to immutable IDs via GitHub REST API. This is the
        # account-resurrection guard — we NEVER store only the name.
        try:
            resolved = resolve_repository(repository_slug)
        except GitHubResolveError as exc:
            form.add_error("repository", str(exc))
            ctx = _list_context(component)
            ctx["form"] = form
            return render(
                request,
                "oidc/_trusted_publishers_section.html.j2",
                ctx,
                status=400,
            )

        # Provision the bot user + binding atomically. The OneToOne
        # constraint on bot_user means we need to attach the bot AFTER
        # the binding's primary key is generated, so we create the
        # binding with a placeholder, provision, then attach.
        try:
            with transaction.atomic():
                placeholder = User.objects.create_user(
                    username=f"oidc-placeholder-{resolved.repository_id}-{component.id}",
                    is_active=False,
                )
                placeholder.set_unusable_password()
                placeholder.save(update_fields=["password"])
                binding = OIDCBinding.objects.create(
                    component=component,
                    provider=provider,
                    repository=resolved.repository.lower(),
                    repository_id=resolved.repository_id,
                    repository_owner_id=resolved.repository_owner_id,
                    bot_user=placeholder,
                    created_by=cast(User, request.user),
                )
                bot = provision_bot_user_for_binding(binding)
                binding.bot_user = bot
                binding.save(update_fields=["bot_user"])
                placeholder.delete()
        except IntegrityError:
            form.add_error(
                "repository",
                "This repository is already bound to this component.",
            )
            ctx = _list_context(component)
            ctx["form"] = form
            return render(
                request,
                "oidc/_trusted_publishers_section.html.j2",
                ctx,
                status=409,
            )

        return htmx_success_response(
            f"Trusted publisher added: {resolved.repository}",
            content=render(
                request,
                "oidc/_trusted_publishers_section.html.j2",
                _list_context(component),
            ).content.decode(),
        )


class TrustedPublisherDeleteView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """DELETE a single binding."""

    def post(self, request: HttpRequest, component_id: str, binding_id: str) -> HttpResponse:
        component = _get_component_with_crud(request, component_id)
        if component is None:
            return htmx_error_response("Component not found or insufficient permissions.")

        binding = OIDCBinding.objects.filter(component=component, pk=binding_id).first()
        if binding is None:
            return htmx_error_response("Trusted publisher not found.")

        # Cascade: delete the binding → post_delete signal reaps the
        # bot User → FK CASCADE removes every short-lived AccessToken
        # the binding ever issued.
        repo_label = binding.repository
        binding.delete()

        return htmx_success_response(
            f"Trusted publisher removed: {repo_label}",
            content=render(
                request,
                "oidc/_trusted_publishers_section.html.j2",
                _list_context(component),
            ).content.decode(),
        )
