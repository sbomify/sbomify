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

Creation and the timeline composer persist: the New Advisory form writes the
whole initial graph through ``create_advisory``, and posting an update writes a
note or a status move through ``post_update``. Editing and linking VEX still
land in the following passes, and those handlers say so rather than pretending
otherwise.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.models import User
from sbomify.apps.security_advisories.forms import AdvisoryCreateForm
from sbomify.apps.security_advisories.services.advisories import (
    PUBLISHABLE_VISIBILITIES,
    REMEDIATION_META,
    advisory_counts,
    create_advisory,
    creation_options,
    get_advisory,
    list_advisories,
    post_update,
    publish_advisory,
    update_advisory,
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


# Severity as the New Advisory form offers it. The icons read as a scale rather
# than as five different warnings, and each variant points at the same token the
# severity badge uses, so the choice looks like the badge it produces.
SEVERITY_OPTIONS: list[dict[str, str]] = [
    {
        "value": "critical",
        "label": "Critical",
        "icon": "fas fa-triangle-exclamation",
        "variant": "severity-critical",
    },
    {"value": "high", "label": "High", "icon": "fas fa-angles-up", "variant": "severity-high"},
    {"value": "medium", "label": "Medium", "icon": "fas fa-angle-up", "variant": "severity-medium"},
    {"value": "low", "label": "Low", "icon": "fas fa-angle-down", "variant": "severity-low"},
]


# Roles that may change an advisory, mirroring the has_crud_permissions the
# templates use to decide whether to render the controls at all.
_ADVISORY_WRITE_ROLES = ("owner", "admin")


def _writable_team(request: HttpRequest) -> Team | None:
    """The workspace, but only for a member who may change its advisories.

    The templates hide the edit and compose controls behind
    ``has_crud_permissions``, which is a rendering decision and nothing a
    handler can rely on — a POST can be crafted without ever loading the page.
    The role is read from the membership row rather than the session, so a
    role cached there cannot outlive a demotion.
    """
    key = (request.session.get("current_team") or {}).get("key")
    if not key:
        return None
    user = cast(User, request.user)
    membership = (
        Member.objects.filter(user=user, team__key=key, role__in=_ADVISORY_WRITE_ROLES)
        .select_related("team")
        .only("team", "role")
        .first()
    )
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
        context = _advisories_context(request)
        team = _current_team(request)
        context["creation_products"] = (creation_options(team).value or []) if team else []
        return render(request, "core/security_advisories_dashboard.html.j2", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        # Kept so anything still posting the create form at the list URL keeps
        # working; the form itself now lives at security_advisory_new.
        return _create_advisory(request, on_error="core:security_advisories_dashboard")


class SecurityAdvisoryCreateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The New Advisory form, as a page.

    It was a modal, but the affected-products picker is a filterable tree with
    range selection that needs room to be usable — in a modal the scope line and
    the version list fell under the fold on a short window.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        team = _current_team(request)
        if team is None:
            raise Http404("Workspace not found")

        current_team = request.session.get("current_team") or {}
        if current_team.get("role") not in ["owner", "admin"]:
            raise Http404("Workspace not found")

        products = creation_options(team).value or []
        # ``?product=`` lets a product's row menu open this form with that
        # product already ticked. Intersected with the workspace's own products,
        # so a hand-edited id cannot preselect another workspace's product — and
        # an id for something deleted since simply drops out.
        requested = set(request.GET.getlist("product"))
        preselected = [product["id"] for product in products if product["id"] in requested]

        return render(
            request,
            "core/security_advisory_new.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": True,
                "creation_products": products,
                "preselected_product_ids": preselected,
                "severity_options": SEVERITY_OPTIONS,
                # From REMEDIATION_META so the form, the badges and the timeline
                # read the same vocabulary, in the same order, with the same icon
                # and colour on each value.
                "status_options": [
                    {
                        "value": value,
                        "label": meta["label"],
                        "icon": meta["icon"],
                        "variant": meta["variant"],
                    }
                    for value, meta in REMEDIATION_META.items()
                ],
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        return _create_advisory(request, on_error="core:security_advisory_new")


def _create_advisory(request: HttpRequest, *, on_error: str) -> HttpResponse:
    """Create an advisory from a posted form, returning to `on_error` if it fails."""
    team = _writable_team(request)
    if team is None:
        raise Http404("Workspace not found")

    form = AdvisoryCreateForm(team, request.POST)
    if not form.is_valid():
        # The redirect drops the form, so errors surface as a toast rather than
        # inline. First error only: one actionable message beats a wall of them.
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Advisory not created: {first_error}")
        return redirect(on_error)

    result = create_advisory(
        team,
        cast(User, request.user),
        title=form.cleaned_data["title"],
        severity=form.cleaned_data.get("severity") or "",
        description=form.cleaned_data.get("description") or "",
        identifier=form.cleaned_data.get("vulnerability_id") or "",
        remediation_status=form.cleaned_data.get("remediation_status") or "",
        products=list(form.cleaned_data.get("products") or []),
        affected_releases=list(form.cleaned_data.get("affected_releases") or []),
    )
    if not result.ok or result.value is None:
        messages.error(request, f"Advisory not created: {result.error or 'unknown error'}")
        return redirect(on_error)

    messages.success(request, f'Advisory "{form.cleaned_data["title"]}" created.')
    return redirect("core:security_advisory_detail", advisory_id=result.value)


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
                "publish_visibilities": PUBLISHABLE_VISIBILITIES,
                # Real VEX candidates need the linking pass; an empty list renders
                # the section's own empty state rather than inventing documents.
                "vex_candidates": [],
            },
        )

    def post(self, request: HttpRequest, advisory_id: str) -> HttpResponse:
        team = _writable_team(request)
        if team is None:
            raise Http404("Advisory not found")

        intent = request.POST.get("intent")
        if intent == "publish":
            result = publish_advisory(
                team,
                cast(User, request.user),
                advisory_id,
                visibility=request.POST.get("visibility", ""),
            )
            if result.ok:
                messages.success(request, "Advisory published.")
            elif result.status_code == 404:
                raise Http404("Advisory not found")
            else:
                messages.error(request, result.error or "Advisory not published.")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent == "edit":
            result = update_advisory(
                team,
                cast(User, request.user),
                advisory_id,
                title=request.POST.get("title", ""),
                # None when the form did not carry the field at all, so a
                # partial edit cannot silently set a severity nobody chose.
                severity=request.POST.get("severity"),
                description=request.POST.get("description", ""),
            )
            if result.ok:
                messages.success(request, "Advisory updated.")
            elif result.status_code == 404:
                raise Http404("Advisory not found")
            else:
                messages.error(request, result.error or "Advisory not updated.")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent in ("edit_update", "link_vex"):
            # Only the stubs pay for the full projection lookup; the real
            # composer path below lets post_update do the one scoped lookup.
            if not get_advisory(team, advisory_id).ok:
                raise Http404("Advisory not found")
            note = {
                "edit_update": "Editing a timeline entry is the next pass on this UI.",
                "link_vex": "Linking VEX documents is the pass after the CRUD one.",
            }[intent]
            messages.info(request, f"Not saved yet. {note}")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        kind = (request.POST.get("kind") or NOTE_ONLY_KIND).strip()
        result = post_update(team, cast(User, request.user), advisory_id, kind=kind, note=request.POST.get("note", ""))
        if not result.ok and result.status_code == 404:
            raise Http404("Advisory not found")
        if result.ok:
            if kind == NOTE_ONLY_KIND:
                messages.success(request, "Update posted.")
            else:
                label = UPDATE_KINDS.get(kind, UPDATE_KINDS[NOTE_ONLY_KIND])["label"]
                messages.success(request, f"Status moved to {label}.")
        else:
            messages.error(request, result.error or "Update not posted.")
        return redirect("core:security_advisory_detail", advisory_id=advisory_id)
