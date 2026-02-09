from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View


class TailwindTestView(LoginRequiredMixin, View):
    """Test view for previewing Tailwind CSS components and styling."""

    def get(self, request: HttpRequest) -> HttpResponse:
        context = {
            "team": request.session.get("current_team", {}),
        }
        return render(request, "core/tw_test.html.j2", context)
