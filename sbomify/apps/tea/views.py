"""The TEA subscription import wizard and the component page's "Check now".

The wizard is one page whose steps are partials: each step posts back here,
reads the remote server, and answers with the next step. The server travels in
a hidden field and is checked again on every request, because the browser
sends it back.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.billing.billing_helpers import check_rate_limit
from sbomify.apps.core.authz import MANAGE, can
from sbomify.apps.core.domain.exceptions import DomainError
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import Product, Release
from sbomify.apps.tea import pins
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.services import remote
from sbomify.apps.tea.services.subscriptions import Subscribe, authorize_targets, subscribe
from sbomify.apps.tea.tasks import check_tea_subscription
from sbomify.apps.teams.broadcasts import broadcast_on_commit
from sbomify.apps.teams.models import Workspace
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key

STEPS = {1: "Source", 2: "Find", 3: "Select", 4: "Confirm"}
# Each step reads a remote server on the user's behalf, so the wizard is rate limited like the API.
STEP_LIMIT, STEP_PERIOD = 30, 60
# The longest value each field takes, as the API allows. A name_<n> field takes 255.
FIELD_LIMITS = (("server", 500), ("custom_server", 500), ("tei", 2048), ("id_value", 2048), ("page_token", 2048))
MAX_PICKS = remote.PREVIEW_LIMIT
CUSTOM_SOURCE = "custom"
ID_TYPES = [{"value": "PURL", "label": "PURL"}, {"value": "CPE", "label": "CPE"}, {"value": "TEI", "label": "TEI"}]


def source_options() -> list[dict[str, str]]:
    named = [
        {"value": domain, "label": label, "icon": "fas fa-cubes"} for domain, label in settings.TEA_SUBSCRIPTION_SOURCES
    ]
    return [*named, {"value": CUSTOM_SOURCE, "label": "Another server", "icon": "fas fa-server"}]


class TeaSubscribeView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Subscribe to a component another TEA 1.0 server publishes."""

    def _team(self, request: HttpRequest) -> Workspace:
        current = request.session.get("current_workspace") or {}
        if get_member_role_by_key(request.user, current.get("key")) not in MANAGE:
            raise Http404("Workspace not found")
        return Workspace.objects.get(key=current["key"])

    def get(self, request: HttpRequest) -> HttpResponse:
        self._team(request)
        return render(request, "tea/subscribe.html.j2", {"steps": STEPS, "step": 1, "sources": source_options()})

    def post(self, request: HttpRequest) -> HttpResponse:
        team = self._team(request)
        if check_rate_limit(f"tea_wizard:{request.user.pk}", limit=STEP_LIMIT, period=STEP_PERIOD):
            return htmx_error_response("Too many requests. Wait a minute and try again.")
        too_long = any(len(request.POST.get(name, "")) > limit for name, limit in FIELD_LIMITS) or any(
            len(value) > 255 for name, value in request.POST.items() if name.startswith("name_")
        )
        if too_long or len(request.POST.getlist("pick")) > MAX_PICKS:
            return HttpResponseBadRequest("Request too large")
        handlers: dict[str, Callable[[HttpRequest, Workspace], HttpResponse]] = {
            "find": self._find,
            "tei": self._tei,
            "products": self._products,
            "releases": self._releases,
            "components": self._components,
            "confirm": self._confirm,
            "subscribe": self._subscribe,
        }
        handler = handlers.get(request.POST.get("step", ""))
        if handler is None:
            return HttpResponseBadRequest("Unknown step")
        try:
            return handler(request, team)
        except DomainError as error:
            return htmx_error_response(error.detail)

    def _step(self, request: HttpRequest, template: str, step: int, **context: Any) -> HttpResponse:
        return render(request, f"tea/wizard/{template}.html.j2", {"steps": STEPS, "step": step, **context})

    def _server(self, request: HttpRequest) -> remote.RemoteServer:
        return remote.connect(request.POST.get("server", ""))

    def _find(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        source = request.POST.get("source", "")
        typed = request.POST.get("custom_server", "") if source == CUSTOM_SOURCE else source
        server = remote.connect(typed)
        return self._step(request, "find", 2, server=server, id_types=ID_TYPES)

    def _tei(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        match = remote.resolve_tei(request.POST.get("tei", ""))
        if not match.product_release_uuids:
            return htmx_error_response("That TEI names no product release on its server.")
        if len(match.product_release_uuids) == 1:
            return self._components_of(request, match.server, match.product_release_uuids[0], tei=request.POST["tei"])
        releases = remote.describe_product_releases(match.server, match.product_release_uuids)
        return self._step(
            request, "releases", 3, server=match.server, page=remote.Page(releases), tei=request.POST["tei"]
        )

    def _products(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        server = self._server(request)
        id_type, id_value = request.POST.get("id_type") or None, request.POST.get("id_value", "").strip() or None
        page = remote.list_products(
            server, id_type=id_type, id_value=id_value, page_token=request.POST.get("page_token") or None
        )
        return self._step(
            request, "products", 2, server=server, page=page, id_type=id_type or "", id_value=id_value or ""
        )

    def _releases(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        server = self._server(request)
        product_uuid = request.POST.get("product_uuid", "")
        page = remote.product_releases(server, product_uuid, page_token=request.POST.get("page_token") or None)
        return self._step(request, "releases", 3, server=server, page=page, product_uuid=product_uuid)

    def _components(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        server = self._server(request)
        return self._components_of(
            request, server, request.POST.get("product_release_uuid", ""), tei=request.POST.get("tei", "")
        )

    def _components_of(self, request: HttpRequest, server: remote.RemoteServer, uuid: str, *, tei: str) -> HttpResponse:
        product_release = remote.product_release_components(server, uuid)
        return self._step(request, "components", 3, server=server, product_release=product_release, tei=tei)

    def _picked(self, request: HttpRequest) -> list[dict[str, str]]:
        """The components picked on the select step, each as uuid, release uuid and remote name."""
        picked = []
        for value in request.POST.getlist("pick"):
            component_uuid, _, rest = value.partition("|")
            release_uuid, _, name = rest.partition("|")
            if component_uuid:
                picked.append({"uuid": component_uuid, "release_uuid": release_uuid, "name": name})
        return picked

    def _confirm(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        server = self._server(request)
        picked = self._picked(request)
        if not picked:
            return htmx_error_response("Pick at least one component.")
        return self._step(
            request,
            "confirm",
            4,
            server=server,
            picked=picked,
            tei=request.POST.get("tei", ""),
            products=Product.objects.filter(team=team).order_by("name"),
            releases=Release.objects.filter(product__team=team, is_latest=False)
            .select_related("product")
            .order_by("product__name", "-created_at"),
        )

    def _subscribe(self, request: HttpRequest, team: Workspace) -> HttpResponse:
        server = self._server(request)
        picked = self._picked(request)
        product_ids, pin_release_ids = request.POST.getlist("product_ids"), request.POST.getlist("pin_release_ids")
        authorize_targets(request, team, product_ids, pin_release_ids)
        created: list[TeaSubscription] = []
        for index, pick in enumerate(picked):
            created.append(
                subscribe(
                    team,
                    Subscribe(
                        server=server,
                        component_uuid=pick["uuid"],
                        release_uuids=[pick["release_uuid"]] if pick["release_uuid"] else [],
                        tei=request.POST.get("tei", ""),
                        name=request.POST.get(f"name_{index}", ""),
                        product_ids=product_ids,
                        pin_release_ids=pin_release_ids,
                    ),
                )
            )
        target = (
            reverse("core:component_details", kwargs={"component_id": created[0].component_id})
            if len(created) == 1
            else reverse("core:components_dashboard")
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
        return response


class TeaReleasePinsView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Pin a remote artifact into a release, or unpin one, from the release page."""

    def post(self, request: HttpRequest, release_id: str) -> HttpResponse:
        release = Release.objects.select_related("product__team").filter(pk=release_id).first()
        if release is None or not can(request, "release:read", release.product):
            raise Http404("Release not found")
        try:
            if request.POST.get("action") == "unpin":
                if not can(request, "release:manage", release.product):
                    return htmx_error_response("You can't change this release.")
                pins.unpin(release, request.POST.get("pin_id", ""))
                message = "Unpinned."
            else:
                if not can(request, "release:tag", release.product):
                    return htmx_error_response("You can't pin into this release.")
                artifact = (
                    TeaRemoteArtifact.objects.select_related("release__subscription__component")
                    .filter(
                        pk=request.POST.get("remote_artifact_id", ""),
                        release__subscription__component__team=release.product.team,
                    )
                    .first()
                )
                if artifact is None:
                    return htmx_error_response("Pick a remote artifact.")
                pins.pin(release, artifact, allow_replacement=True)
                message = "Pinned as it is now."
        except DomainError as error:
            return htmx_error_response(error.detail)
        broadcast_on_commit(
            release.product.team.key,
            "release_updated",
            {"release_id": str(release.id), "product_id": str(release.product_id), "name": release.name},
        )
        return htmx_success_response(message, triggers={"refresh-remote-pins": True})


class TeaSubscriptionCheckView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Queue a check of one subscription now."""

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        subscription = TeaSubscription.objects.select_related("component").filter(component_id=component_id).first()
        if subscription is None or not can(request, "component:read_internal", subscription.component):
            raise Http404("Component not found")
        if not can(request, "component:manage", subscription.component):
            return htmx_error_response("You can't check this subscription.")
        check_tea_subscription.send(subscription.pk, force=True)
        return htmx_success_response("Check queued. The page updates when it finishes.")
