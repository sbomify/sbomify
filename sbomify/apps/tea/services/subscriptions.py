"""Creating a TEA subscription component, and reading one back."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import IntegrityError, transaction

from sbomify.apps.core.authz import can
from sbomify.apps.core.domain.exceptions import (
    ConflictError,
    ExternalServiceError,
    PermissionDeniedError,
    ValidationError,
)
from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.tea import pins, sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease, TeaSubscription, TeaSubscriptionEvent
from sbomify.apps.tea.services.remote import RemoteServer, read
from sbomify.apps.teams.broadcasts import broadcast_on_commit
from sbomify.apps.teams.models import Workspace


@dataclass(frozen=True)
class Subscribe:
    """One component picked on a remote server, and where it goes in this workspace."""

    server: RemoteServer
    component_uuid: str
    release_uuids: list[str] = field(default_factory=list)
    tei: str = ""
    name: str = ""
    product_ids: list[str] = field(default_factory=list)
    pin_release_ids: list[str] = field(default_factory=list)


def authorize_targets(actor: Any, team: Workspace, product_ids: list[str], release_ids: list[str]) -> None:
    """Refuse products or releases the caller may not change. Ids from another workspace read as unknown."""
    products = list(Product.objects.filter(team=team, pk__in=product_ids))
    releases = list(
        Release.objects.filter(product__team=team, pk__in=release_ids, is_latest=False).select_related("product")
    )
    if len(products) != len(set(product_ids)) or len(releases) != len(set(release_ids)):
        raise ValidationError("Pick products and releases from this workspace.")
    if not all(can(actor, "product:manage", product) for product in products):
        raise PermissionDeniedError("You can't add components to one of those products.")
    if not all(can(actor, "release:tag", release.product) for release in releases):
        raise PermissionDeniedError("You can't pin into one of those releases.")


def subscribe(team: Workspace, request: Subscribe) -> TeaSubscription:
    """Create a subscription component and run its first check, so a bad pick fails now.

    The caller has checked that the user may create components here, and may
    pin into the releases named. A component whose first check fails is not kept.
    """
    if TeaSubscription.objects.filter(
        component__team=team,
        api_base_url=request.server.base_url,
        remote_component_uuid=request.component_uuid,
    ).exists():
        raise ConflictError("This workspace already subscribes to that component.")

    with request.server.client() as client:
        remote = read(lambda: client.get_component(request.component_uuid))
    name = (request.name or remote.name).strip()[:255]
    products = list(Product.objects.filter(team=team, pk__in=request.product_ids))
    releases = list(
        Release.objects.filter(product__team=team, pk__in=request.pin_release_ids, is_latest=False).select_related(
            "product"
        )
    )
    if len(products) != len(set(request.product_ids)) or len(releases) != len(set(request.pin_release_ids)):
        raise ValidationError("Pick products and releases from this workspace.")

    try:
        with transaction.atomic():
            component = Component.objects.create(
                team=team,
                name=name,
                component_type=Component.ComponentType.TEA_SUBSCRIPTION,
                visibility=Component.Visibility.PRIVATE if team.can_be_private() else Component.Visibility.PUBLIC,
            )
            subscription = TeaSubscription.objects.create(
                component=component,
                api_base_url=request.server.base_url,
                spec_version=request.server.spec_version,
                source_tei=request.tei,
                remote_component_uuid=request.component_uuid,
                remote_name=remote.name,
            )
            TeaRemoteRelease.objects.bulk_create(
                TeaRemoteRelease(subscription=subscription, uuid=uuid, version="", tracked=True)
                for uuid in dict.fromkeys(request.release_uuids)
            )
    except IntegrityError as exc:
        raise ConflictError(f"A component named {name} already exists.") from exc

    checked = sync.check(subscription.pk, force=True)
    if checked is None or checked.status != TeaSubscription.Status.OK:
        message = checked.last_error if checked else "The first check did not run."
        component.delete()
        raise ExternalServiceError(message, service="tea")

    for product in products:
        product.components.add(component)
    starting = _starting_artifacts(checked, request.release_uuids)
    for release in releases:
        for artifact in starting:
            pins.pin(release, artifact, allow_replacement=True)
    broadcast_on_commit(team.key, "component_created", {"component_id": str(component.id), "name": component.name})
    return checked


def _starting_artifacts(subscription: TeaSubscription, release_uuids: list[str]) -> list[TeaRemoteArtifact]:
    """What a pick pins into existing releases: the release picked to start from, else the newest one."""
    start = subscription.releases.filter(uuid__in=release_uuids[:1]).first() or subscription.latest_release
    if start is None:
        return []
    return list(start.artifacts.filter(state=TeaRemoteArtifact.State.CURRENT).order_by("uuid", "version"))


# The badge each state wears, for c-badges.dynamic. Anything unlisted is neutral.
STATUS_TONES: dict[str, str] = {
    TeaSubscription.Status.OK: "success",
    TeaSubscription.Status.NOT_FOUND: "warning",
    TeaSubscription.Status.UNREACHABLE: "danger",
    TeaSubscription.Status.ERROR: "danger",
}
STATE_TONES: dict[str, str] = {
    TeaRemoteArtifact.State.CURRENT: "success",
    TeaRemoteArtifact.State.REPLACED: "info",
    TeaRemoteArtifact.State.CHANGED: "warning",
    TeaRemoteArtifact.State.GONE: "danger",
}
LIFECYCLE_TONES: dict[str, str] = {
    TeaRemoteRelease.Lifecycle.END_OF_SUPPORT: "warning",
    TeaRemoteRelease.Lifecycle.END_OF_LIFE: "danger",
    TeaRemoteRelease.Lifecycle.NO_LONGER_DISTRIBUTED: "danger",
}


def page_context(component_id: str) -> dict[str, Any]:
    """What the component page shows for a subscription: its state and the latest events."""
    subscription = TeaSubscription.objects.select_related("component", "latest_release").get(component_id=component_id)
    events = subscription.events.select_related("release")[:50]
    return {
        "subscription": describe(subscription),
        "subscription_events": [
            {"title": event.get_kind_display(), "summary": event_summary(event), "created_at": event.created_at}
            for event in events
        ],
    }


def event_summary(event: TeaSubscriptionEvent) -> str:
    """One line on what an event names, in the words a user reads."""
    detail = event.detail
    kind = TeaSubscriptionEvent.Kind
    if event.kind in (kind.RELEASE_ADDED, kind.RELEASE_REMOVED):
        return f"Release {detail.get('version', '')}"
    if event.kind == kind.COLLECTION_UPDATED:
        return f"Collection version {detail.get('old')} to {detail.get('new')}"
    if event.kind == kind.LIFECYCLE_CHANGED:
        labels = dict(TeaRemoteRelease.Lifecycle.choices)
        old, new = labels.get(detail.get("old", ""), ""), labels.get(detail.get("new", ""), "")
        return f"Release {detail.get('version', '')}: {old} to {new}"
    if event.kind == kind.CHECK_FAILED:
        return str(detail.get("error", ""))
    if "name" in detail:
        return f"{detail['name']} version {detail.get('version', '')}"
    return ""


def describe(subscription: TeaSubscription) -> dict[str, Any]:
    """A subscription's state, releases and artifacts, newest release first, for the API and the component page."""
    releases = subscription.releases.prefetch_related("artifacts").order_by("-release_date", "-created_date")
    head = subscription.latest_release
    return {
        "component_id": subscription.component_id,
        "name": subscription.component.name,
        "server": subscription.api_base_url,
        "spec_version": subscription.spec_version,
        "source_tei": subscription.source_tei,
        "remote_component_uuid": subscription.remote_component_uuid,
        "remote_name": subscription.remote_name,
        "remote_identifiers": subscription.remote_identifiers,
        "status": subscription.status,
        "status_display": subscription.get_status_display(),
        "status_tone": STATUS_TONES.get(subscription.status, ""),
        "last_error": subscription.last_error,
        "last_checked_at": subscription.last_checked_at,
        "last_success_at": subscription.last_success_at,
        "next_check_at": subscription.next_check_at,
        "latest_release": {"uuid": head.uuid, "version": head.version} if head else None,
        "releases": [
            {
                "uuid": release.uuid,
                "version": release.version,
                "release_date": release.release_date or release.created_date,
                "pre_release": release.pre_release,
                "tracked": release.tracked,
                "lifecycle": release.lifecycle,
                "lifecycle_display": release.get_lifecycle_display(),
                "lifecycle_tone": LIFECYCLE_TONES.get(release.lifecycle, ""),
                "gone": release.gone_at is not None,
                "artifacts": [
                    _artifact(a) for a in sorted(release.artifacts.all(), key=lambda a: (a.name, -a.version))
                ],
            }
            for release in releases
            if release.version
        ],
    }


def _artifact(artifact: TeaRemoteArtifact) -> dict[str, Any]:
    formats = artifact.snapshot.get("formats") or []
    return {
        "id": artifact.pk,
        "uuid": artifact.uuid,
        "version": artifact.version,
        "name": artifact.name or artifact.uuid,
        "type": artifact.artifact_type,
        "state": artifact.state,
        "state_display": artifact.get_state_display(),
        "state_tone": STATE_TONES.get(artifact.state, ""),
        "formats": [{"media_type": f.get("mediaType") or "", "url": f.get("url") or ""} for f in formats],
    }
