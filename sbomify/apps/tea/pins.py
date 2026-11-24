"""Remote artifacts pinned into product releases: what the latest release follows, and what each pin's findings are."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet

from sbomify.apps.core.domain.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from sbomify.apps.core.models import Product, Release, ReleaseArtifact, _suppress_collection_signals
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease, TeaSubscription

if TYPE_CHECKING:
    from sbomify.apps.sboms.models import Component

# Findings on a pin, worst first. Each is (key, what a user reads).
GONE_UPSTREAM = ("gone_upstream", "Gone upstream")
RELEASE_REMOVED = ("release_removed", "Upstream release removed")
NO_LONGER_DISTRIBUTED = ("no_longer_distributed", "No longer distributed")
CHANGED = ("changed", "Changed since pinned")
END_OF_LIFE = ("end_of_life", "End of life")
OUT_OF_SUPPORT = ("out_of_support", "Out of support")
NEWER_REVISION = ("newer_revision", "Newer revision exists")
NEWER_RELEASE = ("newer_release", "Newer upstream release exists")


def head_artifacts(subscription: TeaSubscription) -> QuerySet[TeaRemoteArtifact]:
    """The artifacts the newest upstream release publishes now: what the latest release pins."""
    if subscription.latest_release_id is None:
        return TeaRemoteArtifact.objects.none()
    return TeaRemoteArtifact.objects.filter(
        release_id=subscription.latest_release_id, state=TeaRemoteArtifact.State.CURRENT
    ).order_by("uuid", "version")


def subscription_of(component: Component) -> TeaSubscription | None:
    try:
        return component.tea_subscription
    except TeaSubscription.DoesNotExist:
        return None


def repoint_latest_pins(subscription: TeaSubscription) -> None:
    """Point each latest release's auto pins for this subscription at the newest upstream release.

    Manual pins are never touched. A product's latest release changes only when
    what it should pin differs from what it pins, and then bumps its collection
    once. Only this subscription's pins move: refreshing the whole release would
    re-run the SBOM receivers, which ignore signal suppression.
    """
    from sbomify.apps.core.signals import _schedule_latest_release_updated

    wanted = set(head_artifacts(subscription).values_list("id", flat=True))
    products = Product.objects.filter(components=subscription.component_id).select_related("team")
    for product in products:
        latest = Release.objects.filter(product=product, is_latest=True).first()
        if latest is None:
            continue
        current = dict(
            ReleaseArtifact.objects.filter(
                release=latest, auto_pinned=True, remote_artifact__release__subscription=subscription
            ).values_list("remote_artifact_id", "id")
        )
        if set(current) == wanted:
            continue
        token = _suppress_collection_signals.set(True)
        try:
            ReleaseArtifact.objects.filter(id__in=[pk for kept, pk in current.items() if kept not in wanted]).delete()
            for remote_artifact_id in sorted(wanted - set(current)):
                ReleaseArtifact.objects.create(release=latest, remote_artifact_id=remote_artifact_id, auto_pinned=True)
        finally:
            _suppress_collection_signals.reset(token)
        latest.bump_collection_version(Release.CollectionUpdateReason.ARTIFACT_UPDATED)
        _schedule_latest_release_updated(latest, product)


def pin(release: Release, remote_artifact: TeaRemoteArtifact, *, allow_replacement: bool = False) -> ReleaseArtifact:
    """Pin a remote artifact revision into a release, as it is now. It is never re-pointed afterwards.

    A release holds one revision of each remote artifact: pinning another one
    replaces it when ``allow_replacement``, and is refused otherwise. Pinning the
    same revision again changes nothing.
    """
    subscription = remote_artifact.release.subscription
    if subscription.component.team_id != release.product.team_id:
        raise PermissionDeniedError("That artifact belongs to another workspace.")
    if release.is_latest:
        raise ValidationError("The latest release follows upstream by itself.")
    with transaction.atomic():
        Release.objects.select_for_update().get(pk=release.pk)
        existing = ReleaseArtifact.objects.filter(release=release, remote_artifact=remote_artifact).first()
        if existing is not None:
            return existing
        slot = ReleaseArtifact.objects.filter(
            release=release,
            remote_artifact__release__subscription=subscription,
            remote_artifact__uuid=remote_artifact.uuid,
        )
        if slot.exists():
            if not allow_replacement:
                raise ConflictError("This release already pins another revision of that artifact.")
            slot.delete()
        return ReleaseArtifact.objects.create(release=release, remote_artifact=remote_artifact)


def unpin(release: Release, pin_id: str) -> None:
    if release.is_latest:
        raise ValidationError("The latest release follows upstream by itself.")
    deleted, _ = ReleaseArtifact.objects.filter(pk=pin_id, release=release, remote_artifact__isnull=False).delete()
    if not deleted:
        raise NotFoundError("That release does not pin this artifact.")


def pins_of(release: Release) -> QuerySet[ReleaseArtifact]:
    """A release's remote pins, with everything their findings read."""
    return (
        release.artifacts.filter(remote_artifact__isnull=False)
        .select_related(
            "remote_artifact__release__subscription__latest_release",
            "remote_artifact__release__subscription__component",
        )
        .order_by("remote_artifact__name", "remote_artifact__uuid")
    )


def findings(artifact: TeaRemoteArtifact) -> list[tuple[str, str]]:
    """What has happened upstream to a pinned artifact revision, worst first."""
    remote_release = artifact.release
    head = remote_release.subscription.latest_release
    found = []
    if artifact.state == TeaRemoteArtifact.State.GONE:
        found.append(GONE_UPSTREAM)
    if remote_release.gone_at is not None:
        found.append(RELEASE_REMOVED)
    if remote_release.lifecycle == TeaRemoteRelease.Lifecycle.NO_LONGER_DISTRIBUTED:
        found.append(NO_LONGER_DISTRIBUTED)
    if artifact.state == TeaRemoteArtifact.State.CHANGED:
        found.append(CHANGED)
    if remote_release.lifecycle == TeaRemoteRelease.Lifecycle.END_OF_LIFE:
        found.append(END_OF_LIFE)
    if remote_release.lifecycle == TeaRemoteRelease.Lifecycle.END_OF_SUPPORT:
        found.append(OUT_OF_SUPPORT)
    if artifact.state == TeaRemoteArtifact.State.REPLACED:
        found.append(NEWER_REVISION)
    if head is not None and head.pk != remote_release.pk and _released(head) > _released(remote_release):
        found.append(NEWER_RELEASE)
    return found


def _released(remote_release: TeaRemoteRelease) -> datetime:
    return remote_release.release_date or remote_release.created_date or remote_release.first_seen_at


def upstream_changed() -> Exists:
    """Whether a release pins anything whose upstream changed: an annotation for release lists.

    A newer upstream release alone does not count, or every older release would carry the mark for good.
    """
    unsettled = (
        ~Q(remote_artifact__state=TeaRemoteArtifact.State.CURRENT)
        | Q(remote_artifact__release__gone_at__isnull=False)
        | ~Q(remote_artifact__release__lifecycle=TeaRemoteRelease.Lifecycle.ACTIVE)
    )
    return Exists(ReleaseArtifact.objects.filter(unsettled, release=OuterRef("pk"), remote_artifact__isnull=False))


FINDING_TONES = {
    GONE_UPSTREAM[0]: "danger",
    RELEASE_REMOVED[0]: "danger",
    NO_LONGER_DISTRIBUTED[0]: "danger",
    END_OF_LIFE[0]: "danger",
    CHANGED[0]: "warning",
    OUT_OF_SUPPORT[0]: "warning",
    NEWER_REVISION[0]: "info",
    NEWER_RELEASE[0]: "info",
}


def finding_details(artifact: TeaRemoteArtifact) -> list[dict[str, str]]:
    """A pin's findings with what a user reads and the badge each wears, worst first."""
    return [{"key": key, "label": label, "tone": FINDING_TONES[key]} for key, label in findings(artifact)]


def pinnable(release: Release) -> QuerySet[TeaRemoteArtifact]:
    """Remote artifacts a release may pin: the current ones of subscriptions on its product, not pinned yet."""
    return (
        TeaRemoteArtifact.objects.filter(
            release__subscription__component__products=release.product,
            release__gone_at__isnull=True,
            state=TeaRemoteArtifact.State.CURRENT,
        )
        .exclude(pins__release=release)
        .select_related("release__subscription__component")
        .order_by("release__subscription__component__name", "-release__release_date", "name")
    )
