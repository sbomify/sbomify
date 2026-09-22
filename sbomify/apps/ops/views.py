"""Ops dashboard views.

Views hold no ORM. They ask a service for a panel and render it, so the
definition of every number stays in one place and can be tested without a
request.
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View
from django.views.generic import RedirectView

from .permissions import StaffRequiredMixin
from .services.overview import Overview, get_overview


def _chart_payloads(overview: Overview) -> dict[str, str]:
    """Serialise the chart series for the template's data attributes.

    Charts read their numbers from JSON in a data attribute rather than from
    values pasted into a script body. The old dashboard interpolated workspace
    names straight into JS string literals, where Django's HTML escaping turned
    an apostrophe into a visible ``&#x27;``, because entities are not decoded
    inside a script element.
    """
    return {
        "signup_days": json.dumps([point.day.isoformat() for point in overview.signups]),
        "signup_counts": json.dumps([point.count for point in overview.signups]),
        "plan_labels": json.dumps([plan.plan for plan in overview.plans]),
        "plan_counts": json.dumps([plan.count for plan in overview.plans]),
    }


class OverviewView(StaffRequiredMixin, View):
    """The ops landing page."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        result = get_overview()
        context: dict[str, Any] = {"active_section": "overview"}

        if not result.ok or result.value is None:
            context["error"] = result.error
            return render(request, "ops/overview.html.j2", context, status=result.status_code or 500)

        context["overview"] = result.value
        context["charts"] = _chart_payloads(result.value)
        return render(request, "ops/overview.html.j2", context)


class LegacyDashboardRedirectView(StaffRequiredMixin, RedirectView):
    """``/admin/dashboard/`` and its old sub-pages, kept working for bookmarks.

    Behind the same staff gate as the page it points at. An ungated redirect
    would answer 302 where a non-existent URL answers 404, which tells a
    signed-in customer the surface is there: exactly what the 404 on ``/ops/``
    is for. The alias has to be as quiet as its destination or it is not an
    alias, it is a disclosure.
    """

    pattern_name = "ops:overview"
    permanent = False
