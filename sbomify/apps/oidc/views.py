"""Workspace-owner UI for managing OIDC trusted-publisher bindings.

The module defines two HTMX-driven view classes —
``TrustedPublishersView`` (list + create) and
``TrustedPublisherDeleteView`` (delete) — both rendering partials
rather than full pages. The list partial is the source of truth for
what the user sees, and both create and delete return the refreshed
list so the page state matches the database in one round-trip.

Business-logic ORM calls (creating / deleting bindings, listing them
for a component) live in ``sbomify.apps.oidc.services`` and the views
are thin dispatch over ``ServiceResult[T]``. The one exception is the
``_component_or_error`` helper, which resolves a ``Component`` row
directly so the permission check (``can(.., "component:manage", ..)``) can run
before any service call — keeping permission checks in the view
layer matches the rest of the codebase.
"""

from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.authz import can
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.core.url_utils import get_base_url
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
        # Same reason as the audience: the workflow snippet has to call
        # the *actual* deployment, not a hardcoded ``sbomify.com``.
        # Staging, self-hosted, and air-gapped installs would otherwise
        # show users instructions that point to a different endpoint than
        # the one they're configuring against. Use the codebase's
        # ``get_base_url()`` helper so the value is consistently
        # scheme-prefixed and trailing-slash-stripped — ``APP_BASE_URL``
        # is commonly configured without a scheme (raw host), which
        # would otherwise emit an invalid ``curl host/api/...`` line.
        "api_base_url": get_base_url() or "https://sbomify.com",
    }


class _TrustedPublishersBase(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Shared helper: resolve the component AND check CRUD permission.

    Returns ``None`` and writes the error response into ``self._error``
    when access fails; subclasses check ``component is not None``.
    """

    _error: HttpResponse | None = None

    def _component_or_error(self, request: HttpRequest, component_id: str) -> Component | None:
        component = Component.objects.filter(pk=component_id).select_related("team").first()
        if component is None or not can(request, "component:manage", component):
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
            # Return 200 (not 400): the rendered partial IS the new section
            # state (form re-rendered with the field error). HTMX's default
            # ``responseHandling`` swaps only on 2xx — returning 400 here
            # would leave the user with no visible feedback (and trips the
            # ``django-htmx`` dev-mode debug shim that swaps the whole
            # ``<html>`` for any 4xx body). Validation failure is
            # client-state and gets surfaced inline; component-not-found /
            # GitHub upstream / other gating failures take a different
            # path — they go through ``htmx_error_response``, which
            # currently returns 200 + ``HX-Reswap: none`` so the toast
            # fires without disturbing the page.
            return render(request, SECTION_TEMPLATE, _list_context(component, form=form))

        result = create_binding(
            component=component,
            provider=form.cleaned_data["provider"],
            repository_slug=form.cleaned_data["repository"],
            requested_by=cast(User, request.user),
        )
        if not result.ok:
            form.add_error("repository", result.error or "Failed to add trusted publisher.")
            # 200 (not the service's status_code) — see comment on the
            # form-invalid branch above. HTMX needs a 2xx to swap, and the
            # rendered partial IS the new state for the user (form with
            # ``repository`` field error inline). The service's
            # ``status_code`` is intentionally discarded here (the user-
            # visible state is the form error); surfacing it as the HTTP
            # code would block the swap, and we don't include it in the
            # message text either — for now, debugging relies on the
            # service-layer log line in ``create_binding``.
            return render(request, SECTION_TEMPLATE, _list_context(component, form=form))

        binding = result.value
        assert binding is not None
        return htmx_success_response(
            f"Trusted publisher added: {binding.repository}",
            content=render(request, SECTION_TEMPLATE, _list_context(component)).content.decode(),
        )


class TrustedPublisherDeleteView(_TrustedPublishersBase):
    """Delete a single binding via POST (HTMX uses ``hx-post``).

    HTTP DELETE isn't used here because every consumer is an HTMX
    form-submit (``hx-post`` to this URL), and routing those through
    a Django POST endpoint avoids the surrounding form / CSRF
    plumbing needing a separate DELETE codepath. The view is
    delete-only in *behaviour* — the only mutation it performs is
    ``services.delete_binding`` — but mounted under POST.
    """

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
