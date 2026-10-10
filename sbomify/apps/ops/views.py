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


class StaffOnlyOverviewRedirectView(StaffRequiredMixin, RedirectView):
    """Every other spelling of the overview's URL, behind the overview's gate.

    Two groups of them: ``/admin/dashboard/`` and its old sub-pages, where the
    page used to live and bookmarks still point, and the slashless forms of
    both those and ``/ops`` itself.

    The slashless ones need a route rather than the middleware's help.
    ``APPEND_SLASH`` turns a slashless request into a 301 by resolving the
    URLconf, not by asking the view, so ``/ops`` answered 301 for anybody at
    all while an unknown URL answers 404. That difference is the disclosure,
    and it survives the gate on the destination because the redirect is
    decided before any view runs.

    An alias has to be exactly as quiet as what it points at. Otherwise it is
    not an alias, it is an announcement that the surface exists.
    """

    pattern_name = "ops:overview"
    permanent = False
