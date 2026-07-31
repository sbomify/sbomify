"""Security advisory list and detail.

The UI and its vocabulary are Luc's first pass (#1172); this reads the real
``security_advisories`` models through the service layer instead of the dummy
projection that pass shipped with.

Two status axes reach the templates, and the distinction is the thing to hold on
to. ``status`` is **remediation** — identified, investigating, fix in progress,
resolved, won't fix — and it is what the Status column means. ``publication_*``
is draft / published / withdrawn, whether anyone outside the workspace can read
it. An advisory can be resolved and unpublished, or published mid-fix, so
neither collapses into the other.

Writes still do not persist. Creating advisories, posting updates and linking
VEX land in the following passes, and the handlers below say so rather than
pretending otherwise.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.models import User
from sbomify.apps.security_advisories.services.advisories import (
    REMEDIATION_META,
    advisory_counts,
    get_advisory,
    list_advisories,
)
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

# The kinds the "post an update" control offers. Status-setting kinds write a
# status_change event and move the advisory; "update" is a note that appears in
# the timeline without moving anything.
NOTE_ONLY_KIND = "update"
UPDATE_KINDS: dict[str, dict[str, Any]] = {
    kind: {**meta, "sets_status": True} for kind, meta in REMEDIATION_META.items()
}
UPDATE_KINDS[NOTE_ONLY_KIND] = {
    # Matches the option the user actually picks, so the confirmation names
    # the same thing the select did.
    "label": "Note only",
    "variant": "secondary",
    "icon": "fas fa-comment",
    "sets_status": False,
}


def _current_team(request: HttpRequest) -> Team | None:
    """The workspace being viewed, resolved from the session.

    Confirmed against a live membership rather than trusted from the session
    alone, so a role cached there cannot outlive the membership it describes.
    """
    key = (request.session.get("current_team") or {}).get("key")
    if not key:
        return None
    user = cast(User, request.user)
    membership = Member.objects.filter(user=user, team__key=key).select_related("team").only("team", "role").first()
    return membership.team if membership else None


def _advisories_context(request: HttpRequest) -> dict[str, Any]:
    current_team = request.session.get("current_team") or {}
    team = _current_team(request)
    search = request.GET.get("search", "")
    advisories = (list_advisories(team, search).value or []) if team else []
    counts = advisory_counts(advisories)
    return {
        "current_team": current_team,
        "has_crud_permissions": current_team.get("role") in ["owner", "admin"],
        "advisories": advisories,
        "advisories_count": counts["total"],
        "open_count": counts["open"],
        "resolved_count": counts["resolved"],
        "published_count": counts["published"],
        "search": search,
    }


class SecurityAdvisoriesDashboardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "core/security_advisories_dashboard.html.j2", _advisories_context(request))

    def post(self, request: HttpRequest) -> HttpResponse:
        # Creation lands with the CRUD pass. In the real flow this writes the
        # advisory plus its first status_change event, so nobody sets a status
        # directly.
        title = request.POST.get("title", "").strip()
        messages.info(
            request,
            f'Not saved yet: "{title or "advisory"}". Creating advisories is the next pass on this UI.',
        )
        return redirect("core:security_advisories_dashboard")


class SecurityAdvisoriesTableView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """HTMX table refresh, mirroring ProductsTableView."""

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "core/security_advisories_table.html.j2", _advisories_context(request))


class SecurityAdvisoryDetailView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """One advisory: its vulnerabilities, affected products and event timeline."""

    def get(self, request: HttpRequest, advisory_id: str) -> HttpResponse:
        team = _current_team(request)
        if team is None:
            raise Http404("Advisory not found")

        result = get_advisory(team, advisory_id)
        if not result.ok or result.value is None:
            raise Http404("Advisory not found")

        advisory = result.value
        current_team = request.session.get("current_team") or {}
        return render(
            request,
            "core/security_advisory_detail.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": current_team.get("role") in ["owner", "admin"],
                "advisory": advisory,
                "timeline": advisory["timeline"],
                "update_kinds": UPDATE_KINDS,
                # Real VEX candidates need the linking pass; an empty list renders
                # the section's own empty state rather than inventing documents.
                "vex_candidates": [],
            },
        )

    def post(self, request: HttpRequest, advisory_id: str) -> HttpResponse:
        team = _current_team(request)
        if team is None or not get_advisory(team, advisory_id).ok:
            raise Http404("Advisory not found")

        intent = request.POST.get("intent")
        if intent == "edit":
            note = "Editing an advisory is the next pass on this UI."
        elif intent == "edit_update":
            note = "Editing a timeline entry is the next pass on this UI."
        elif intent == "link_vex":
            note = "Linking VEX documents is the pass after the CRUD one."
        else:
            kind = request.POST.get("kind", NOTE_ONLY_KIND)
            label = UPDATE_KINDS.get(kind, UPDATE_KINDS[NOTE_ONLY_KIND])["label"]
            note = f'Posting the "{label}" update is the next pass on this UI.'
        messages.info(request, f"Not saved yet. {note}")
        return redirect("core:security_advisory_detail", advisory_id=advisory_id)
