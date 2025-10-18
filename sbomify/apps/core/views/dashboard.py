from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.models import Component, Product, Project


class DashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})

        context = {
            "current_team": current_team,
            "data": {
                "products": Product.objects.filter(team_id=current_team.get("id")).count(),
                "projects": Project.objects.filter(team_id=current_team.get("id")).count(),
                "components": Component.objects.filter(team_id=current_team.get("id")).count(),
            },
        }

        return render(request, "core/dashboard.html.j2", context)
