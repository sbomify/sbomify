from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import list_components, list_products, list_projects
from sbomify.apps.core.errors import error_response


class DashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, products = list_products(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=products.get("detail", "Unknown error"))
            )

        status_code, projects = list_projects(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=projects.get("detail", "Unknown error"))
            )

        status_code, components = list_components(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=components.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})

        context = {
            "current_team": current_team,
            "data": {
                "products": len(products.items),
                "projects": len(projects.items),
                "components": len(components.items),
            },
        }

        return render(request, "core/dashboard.html.j2", context)
