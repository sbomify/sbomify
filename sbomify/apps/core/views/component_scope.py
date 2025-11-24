from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.views import View

from sbomify.apps.core.models import Component
from sbomify.apps.core.utils import verify_item_access


class ComponentScopeView(LoginRequiredMixin, View):
    """Handle scope changes for document components via server-rendered form."""

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        try:
            component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return HttpResponseBadRequest("Component not found")

        if component.component_type != Component.ComponentType.DOCUMENT:
            return HttpResponseBadRequest("Only documents can be workspace-wide")

        if not verify_item_access(request, component, ["owner", "admin"]):
            return HttpResponseForbidden("Only owners and admins can change scope")

        target_scope = request.POST.get("target_scope")
        if target_scope not in ["workspace", "project"]:
            return HttpResponseBadRequest("Invalid scope selection")

        is_global = target_scope == "workspace"
        component.is_global = is_global
        if is_global:
            component.projects.clear()
        component.save()

        if is_global:
            messages.success(request, "Component is now workspace-wide and visible on the trust center.")
        else:
            messages.success(request, "Component is now project-scoped.")

        return redirect("core:component_details", component_id=component.id)
