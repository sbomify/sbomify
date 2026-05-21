"""Workspace-owner UI for managing OIDC trusted-publisher bindings.

The module defines two HTMX-driven view classes —
``TrustedPublishersView`` (list + create) and
``TrustedPublisherDeleteView`` (delete) — both rendering partials
rather than full pages. The list partial is the source of truth for
what the user sees, and both create and delete return the refreshed
list so the page state matches the database in one round-trip.

Every ORM call lives in ``sbomify.apps.oidc.services`` — these views
are thin dispatch over ``ServiceResult[T]``.
"""

from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.oidc.forms import OIDCBindingForm
from sbomify.apps.oidc.services import create_binding, delete_binding, list_bindings_for_component
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

SECTION_TEMPLATE = "oidc/_trusted_publishers_section.html.j2"


def _list_context(component: Component, form: OIDCBindingForm | None = None) -> dict[str, Any]:
    """Context dict for the bindings-list partial."""
    return {
        "component": component,
        "bindings": list_bindings_for_component(component),
        "form": form or OIDCBindingForm(),
        # Used in the embedded workflow snippet so the YAML stays
        # accurate when ``OIDC_GITHUB_AUDIENCE`` is overridden at the
        # deployment level (staging, self-hosted, etc.).
        "oidc_github_audience": settings.OIDC_GITHUB_AUDIENCE,
    }


class _TrustedPublishersBase(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Shared helper: resolve the component AND check CRUD permission.

    Returns ``None`` and writes the error response into ``self._error``
    when access fails; subclasses check ``component is not None``.
    """

    _error: HttpResponse | None = None

    def _component_or_error(self, request: HttpRequest, component_id: str) -> Component | None:
        component = Component.objects.filter(pk=component_id).select_related("team").first()
        if component is None or not verify_item_access(request, component, ["owner", "admin"]):
            self._error = htmx_error_response("Component not found or insufficient permissions.")
            return None
        return component


class TrustedPublishersView(_TrustedPublishersBase):
    """GET: render the section partial. POST: create a binding."""

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        component = self._component_or_error(request, component_id)
        if component is None:
            return cast(HttpResponse, self._error)
        return render(request, SECTION_TEMPLATE, _list_context(component))

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        component = self._component_or_error(request, component_id)
        if component is None:
            return cast(HttpResponse, self._error)

        form = OIDCBindingForm(request.POST)
        if not form.is_valid():
            return render(request, SECTION_TEMPLATE, _list_context(component, form=form), status=400)

        result = create_binding(
            component=component,
            provider=form.cleaned_data["provider"],
            repository_slug=form.cleaned_data["repository"],
            requested_by=cast(User, request.user),
        )
        if not result.ok:
            form.add_error("repository", result.error or "Failed to add trusted publisher.")
            return render(
                request,
                SECTION_TEMPLATE,
                _list_context(component, form=form),
                status=result.status_code or 400,
            )

        binding = result.value
        assert binding is not None
        return htmx_success_response(
            f"Trusted publisher added: {binding.repository}",
            content=render(request, SECTION_TEMPLATE, _list_context(component)).content.decode(),
        )


class TrustedPublisherDeleteView(_TrustedPublishersBase):
    """DELETE a single binding."""

    def post(self, request: HttpRequest, component_id: str, binding_id: str) -> HttpResponse:
        component = self._component_or_error(request, component_id)
        if component is None:
            return cast(HttpResponse, self._error)

        result = delete_binding(component=component, binding_id=binding_id)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to remove trusted publisher.")

        return htmx_success_response(
            f"Trusted publisher removed: {result.value}",
            content=render(request, SECTION_TEMPLATE, _list_context(component)).content.decode(),
        )
