from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.views import View

from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Component
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ComponentScopeView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Handle scope changes for document components via server-rendered form."""

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        try:
            component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return HttpResponseBadRequest("Component not found")

        if component.component_type != Component.ComponentType.DOCUMENT:
            return HttpResponseBadRequest("Only documents can be workspace-wide")

        if not can(request, "component:manage", component):
            return HttpResponseForbidden("Only owners and admins can change scope")

        target_scope = request.POST.get("target_scope")
        if target_scope not in ("workspace", "product"):
            return HttpResponseBadRequest("Invalid scope selection")

        is_global = target_scope == "workspace"
        component.is_global = is_global
        if is_global:
            # Belt-and-suspenders detach: ``Component.save()`` ALSO detaches
            # products when ``is_global=True`` (see sboms/models.py). The
            # explicit clear here keeps the pre-save state consistent for any
            # form/admin path that introspects the relationship between this
            # field-flip and the persist call.
            component.products.clear()
        component.save()

        if is_global:
            messages.success(request, "Component is now workspace-wide and visible on the Trust Center.")
        else:
            messages.success(request, "Component is now product-scoped.")

        return redirect("core:component_details", component_id=component.id)
