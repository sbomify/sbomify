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

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import HtmxFragmentMixin, htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.security_advisories.forms import AdvisoryAddProductForm, AdvisoryCreateForm
from sbomify.apps.security_advisories.models import AdvisoryProductStatus, SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import (
    PRODUCT_STATUS_FIELDS,
    PUBLISHABLE_VISIBILITIES,
    REMEDIATION_META,
    add_advisory_product,
    advisory_counts,
    create_advisory,
    creation_options,
    delete_advisories,
    delete_advisory,
    edit_message,
    get_advisory,
    list_advisories,
    post_update,
    product_choices,
    publish_advisory,
    update_advisory,
    update_product_status,
)
from sbomify.apps.security_advisories.services.proposals import (
    advisory_proposals,
    approve_proposal,
    pending_counts,
    reject_proposal,
)
from sbomify.apps.teams.models import Member, Workspace
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


# The product status dialog's choices, from the model so the page and the
# stored vocabulary cannot drift apart.
PRODUCT_STATUS_OPTIONS = [{"value": v, "label": label} for v, label in AdvisoryProductStatus.Status.choices]
JUSTIFICATION_OPTIONS = [{"value": v, "label": label} for v, label in AdvisoryProductStatus.Justification.choices]
RESPONSE_OPTIONS = [{"value": v, "label": label} for v, label in AdvisoryProductStatus.Response.choices]


def _current_team(request: HttpRequest) -> Workspace | None:
    """The workspace being viewed, resolved from the session.

    Confirmed against a live membership rather than trusted from the session
    alone, so a role cached there cannot outlive the membership it describes.
    """
    key = (request.session.get("current_workspace") or {}).get("key")
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
# Publishing an advisory is an outward-facing act — it appears on the public
# trust center — so it is ADMINISTER, not the MANAGE tier that covers day-to-day
# artifact work. Bound to the tier rather than repeated as a literal so it cannot
# quietly widen when a role is added.
_ADVISORY_WRITE_ROLES = ADMINISTER


def _can_write_advisories(request: HttpRequest) -> bool:
    """Whether this user may change advisories, from the live Member row.

    Not from ``session["current_workspace"]["role"]``: that is a cache with a 300s
    TTL, so a demoted user kept seeing the compose and edit controls (and a
    promoted one kept missing them) while the handler enforced the real answer.
    """
    key = (request.session.get("current_workspace") or {}).get("key")
    if not key:
        return False
    return Member.objects.filter(user=cast(User, request.user), team__key=key, role__in=_ADVISORY_WRITE_ROLES).exists()


def _writable_team(request: HttpRequest) -> Workspace | None:
    """The workspace, but only for a member who may change its advisories.

    The templates hide the edit and compose controls behind
    ``has_crud_permissions``, which is a rendering decision and nothing a
    handler can rely on — a POST can be crafted without ever loading the page.
    The role is read from the membership row rather than the session, so a
    role cached there cannot outlive a demotion.
    """
    key = (request.session.get("current_workspace") or {}).get("key")
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
    current_team = request.session.get("current_workspace") or {}
    team = _current_team(request)
    search = request.GET.get("search", "")
    advisories = (list_advisories(team, search).value or []) if team else []
    # Changes AI agents proposed and nobody has decided, per advisory, so the
    # list says which advisories need someone before the page is opened.
    waiting = pending_counts(team) if team else {}
    for advisory in advisories:
        advisory["pending_review"] = waiting.get(advisory["pk"], 0)
    counts = advisory_counts(advisories)
    return {
        "current_team": current_team,
        "has_crud_permissions": _can_write_advisories(request),
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

        # The live Member row, not the session's cached role: same reason the
        # rest of this module reads it that way, and it keeps the tier in one
        # place instead of a literal list that widens when a role is added.
        if not _can_write_advisories(request):
            raise Http404("Workspace not found")

        current_team = request.session.get("current_workspace") or {}

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
                #
                # Not "resolved": every product opens under investigation, and
                # a resolved advisory may not say that about any of them. It is
                # resolved from its page once each product has a status.
                "status_options": [
                    {
                        "value": value,
                        "label": meta["label"],
                        "icon": meta["icon"],
                        "variant": meta["variant"],
                    }
                    for value, meta in REMEDIATION_META.items()
                    if value != SecurityAdvisory.RemediationStatus.RESOLVED
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
        cvss_score=form.cleaned_data.get("cvss_score"),
        cvss_vector=form.cleaned_data.get("cvss_vector") or "",
        products=list(form.cleaned_data.get("products") or []),
        affected_releases=list(form.cleaned_data.get("affected_releases") or []),
    )
    if not result.ok or result.value is None:
        messages.error(request, f"Advisory not created: {result.error or 'unknown error'}")
        return redirect(on_error)

    messages.success(request, f'Advisory "{form.cleaned_data["title"]}" created.')
    return redirect("core:security_advisory_detail", advisory_id=result.value)


class SecurityAdvisoriesTableView(HtmxFragmentMixin, GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """HTMX table refresh."""

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "core/security_advisories_table.html.j2", _advisories_context(request))


class SecurityAdvisoriesBulkDeleteView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The table's bulk delete, posted in place by c-tables.bulk-delete once the person confirms.

    Gated to the same roles as deleting one advisory. It answers with a toast
    and the refresh-advisories trigger the table already listens for, so the
    deleted rows leave the list without the page reloading.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        team = _writable_team(request)
        if team is None:
            return htmx_error_response("You cannot delete advisories in this workspace.")
        result = delete_advisories(team, request.POST.getlist("ids"))
        if not result.ok or result.value is None:
            return htmx_error_response(result.error or "Advisories not deleted.")
        count = result.value
        noun = "advisory" if count == 1 else "advisories"
        return htmx_success_response(f"Deleted {count} {noun}.", triggers={"refresh-advisories": True})


class SecurityAdvisoryProductReleasesView(HtmxFragmentMixin, GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The "Add product" dialog's release checkboxes, for the product just picked."""

    def get(self, request: HttpRequest, advisory_id: str) -> HttpResponse:
        team = _writable_team(request)
        if team is None:
            raise Http404("Advisory not found")
        product_id = request.GET.get("product", "")
        options = (creation_options(team, product_ids=[product_id]).value or []) if product_id else []
        releases = options[0]["releases"] if options else []
        return render(request, "core/components/advisory_add_product_releases.html.j2", {"releases": releases})


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
        current_team = request.session.get("current_workspace") or {}
        can_write = _can_write_advisories(request)
        review = advisory_proposals(team, advisory["pk"]).value or {}
        # A pending edit is pointed at from the update it would change, so the
        # reader of that update knows its wording may be about to move.
        pending_edits = review.get("pending_edits", {})
        for entry in advisory["timeline"]:
            entry["pending_edit"] = pending_edits.get(entry["id"])
        return render(
            request,
            "core/security_advisory_detail.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": can_write,
                "advisory": advisory,
                # A withdrawn advisory is final, so its rows are shown, not offered for editing.
                "can_edit_statuses": can_write and advisory["publication_status"] != "withdrawn",
                # The releases of the products the advisory names, for the edit
                # dialog. The add dialog lists every product by name and fetches
                # the chosen one's releases when it is picked, so a page load
                # never reads the whole workspace's releases.
                "product_options": (
                    (creation_options(team, product_ids=[p["id"] for p in advisory["products"] if p["id"]]).value or [])
                    if can_write
                    else []
                ),
                "product_choices": (product_choices(team).value or []) if can_write else [],
                "advisory_product_ids": [p["id"] for p in advisory["products"] if p["id"]],
                "product_status_options": PRODUCT_STATUS_OPTIONS,
                "justification_options": JUSTIFICATION_OPTIONS,
                "response_options": RESPONSE_OPTIONS,
                "timeline": advisory["timeline"],
                "review": review,
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
                # The same rule guards the CVSS pair.
                severity=request.POST.get("severity"),
                description=request.POST.get("description", ""),
                summary=request.POST.get("summary"),
                cvss_score=request.POST.get("cvss_score"),
                cvss_vector=request.POST.get("cvss_vector"),
            )
            if result.ok:
                messages.success(request, "Advisory updated.")
            elif result.status_code == 404:
                raise Http404("Advisory not found")
            else:
                messages.error(request, result.error or "Advisory not updated.")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent == "product_status":
            # Only the fields the dialog posted, so a caller that posts one
            # field changes one field.
            changes = {field: request.POST.get(field, "") for field in PRODUCT_STATUS_FIELDS if field in request.POST}
            result = update_product_status(
                team, cast(User, request.user), advisory_id, request.POST.get("status_id", ""), changes=changes
            )
            if result.ok:
                messages.success(request, "Product status saved.")
            elif result.status_code == 404 and not get_advisory(team, advisory_id).ok:
                raise Http404("Advisory not found")
            else:
                messages.error(request, f"Product status not saved: {result.error or 'unknown error'}")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent == "add_product":
            form = AdvisoryAddProductForm(team, request.POST)
            if not form.is_valid():
                first_error = next(iter(form.errors.values()))[0]
                messages.error(request, f"Product not added: {first_error}")
                return redirect("core:security_advisory_detail", advisory_id=advisory_id)
            status = form.cleaned_data.get("status")
            result = add_advisory_product(
                team,
                cast(User, request.user),
                advisory_id,
                product=form.cleaned_data["product"],
                affected_releases=list(form.cleaned_data.get("affected_releases") or []),
                changes={"status": status} if status else {},
            )
            if result.ok:
                messages.success(request, f'Added "{form.cleaned_data["product"].name}".')
            elif result.status_code == 404:
                raise Http404("Advisory not found")
            else:
                messages.error(request, f"Product not added: {result.error or 'unknown error'}")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent == "delete":
            result = delete_advisory(team, advisory_id)
            if not result.ok:
                if result.status_code == 404:
                    raise Http404("Advisory not found")
                messages.error(request, result.error or "Advisory not deleted.")
                return redirect("core:security_advisory_detail", advisory_id=advisory_id)
            messages.success(request, "Advisory deleted.")
            return redirect("core:security_advisories_dashboard")

        if intent == "edit_update":
            result = edit_message(
                team,
                cast(User, request.user),
                advisory_id,
                request.POST.get("update_id", ""),
                note=request.POST.get("note", ""),
            )
            if result.ok:
                messages.success(request, "Update edited.")
            elif result.status_code == 404 and not get_advisory(team, advisory_id).ok:
                raise Http404("Advisory not found")
            else:
                messages.error(request, f"Update not edited: {result.error or 'unknown error'}")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent in ("approve_proposal", "reject_proposal"):
            proposal_id = request.POST.get("proposal_id", "")
            if intent == "approve_proposal":
                decided = approve_proposal(
                    team,
                    cast(User, request.user),
                    advisory_id,
                    proposal_id,
                    # Present only when the reviewer reworded the update first.
                    note=request.POST.get("note"),
                    decision_note=request.POST.get("decision_note", ""),
                )
                done, failed = "Change approved.", "Change not approved"
            else:
                decided = reject_proposal(
                    team,
                    cast(User, request.user),
                    advisory_id,
                    proposal_id,
                    decision_note=request.POST.get("decision_note", ""),
                )
                done, failed = "Change rejected.", "Change not rejected"
            if decided.ok:
                messages.success(request, done)
            elif decided.status_code == 404 and not get_advisory(team, advisory_id).ok:
                raise Http404("Advisory not found")
            else:
                messages.error(request, f"{failed}: {decided.error or 'unknown error'}")
            return redirect("core:security_advisory_detail", advisory_id=advisory_id)

        if intent == "link_vex":
            if not get_advisory(team, advisory_id).ok:
                raise Http404("Advisory not found")
            messages.info(request, "Not saved yet. Linking VEX documents is the pass after the CRUD one.")
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
