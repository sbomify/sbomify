"""Links between releases of different products.

A release holds artifacts of its own product's components. A product that ships
with another product, such as an application and the toolchain it downloads at
run time, links its release to that product's release instead of adopting its
components.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from django.db import IntegrityError, transaction

from sbomify.apps.core.models import Release, ReleaseArtifact, ReleaseLink
from sbomify.apps.core.services.results import ServiceResult


def find_release(
    team_id: int, *, release_id: str | None, product_id: str | None, version: str | None
) -> Release | None:
    """The release a link points at, by id or by product and version, within one workspace."""
    releases = Release.objects.select_related("product").filter(product__team_id=team_id)
    if release_id:
        return releases.filter(pk=release_id).first()
    if product_id and version:
        return releases.filter(product_id=product_id, version=version).first()
    return None


def _reaches(start: Release, target: Release) -> bool:
    """Whether following links from ``start`` arrives at ``target``."""
    seen: set[str] = set()
    frontier = {start.id}
    while frontier:
        if target.id in frontier:
            return True
        seen |= frontier
        frontier = (
            set(ReleaseLink.objects.filter(release_id__in=frontier).values_list("linked_release_id", flat=True)) - seen
        )
    return False


def link_release(release: Release, linked_release: Release) -> ServiceResult[ReleaseLink]:
    if linked_release.product.team_id != release.product.team_id:
        return ServiceResult.failure("The linked release must be in the same workspace", status_code=403)
    if linked_release.product_id == release.product_id:
        return ServiceResult.failure("Link a release of another product", status_code=400)
    if release.is_latest:
        return ServiceResult.failure("Cannot link releases to the 'latest' release", status_code=400)
    if _reaches(linked_release, release):
        return ServiceResult.failure("That release already links back to this one", status_code=400)
    try:
        with transaction.atomic():
            link = ReleaseLink.objects.create(release=release, linked_release=linked_release)
    except IntegrityError:
        return ServiceResult.failure("This release is already linked", status_code=409)
    return ServiceResult.success(link)


def unlink_release(release: Release, linked_release_id: str) -> ServiceResult[None]:
    if release.is_latest:
        return ServiceResult.failure("Cannot unlink releases from the 'latest' release", status_code=400)
    deleted, _ = ReleaseLink.objects.filter(release=release, linked_release_id=linked_release_id).delete()
    if not deleted:
        return ServiceResult.failure("Linked release not found", status_code=404)
    return ServiceResult.success(None)


def release_links(release: Release, *, include_private: bool) -> list[ReleaseLink]:
    """The release's direct links. Without ``include_private``, only links to public products."""
    links = release.links.select_related("linked_release__product")
    if not include_private:
        links = links.filter(linked_release__product__is_public=True)
    return list(links)


def release_link_rows(
    release: Release, *, include_private: bool, url_for: Callable[[Release], str]
) -> list[dict[str, str]]:
    """What a release page lists for each linked release, with the URL the reader can open."""
    return [
        {
            "product_name": link.linked_release.product.name,
            "name": link.linked_release.name,
            "version": link.linked_release.version,
            "url": url_for(link.linked_release),
        }
        for link in release_links(release, include_private=include_private)
    ]


def linked_release_ids(release: Release) -> list[str]:
    """Every release reachable through links, in a stable order. Links cannot form a cycle."""
    found: list[str] = []
    frontier = [release.id]
    while frontier:
        nxt = list(
            ReleaseLink.objects.filter(release_id__in=frontier)
            .exclude(linked_release_id__in=[release.id, *found])
            .order_by("linked_release_id")
            .values_list("linked_release_id", flat=True)
            .distinct()
        )
        found.extend(nxt)
        frontier = nxt
    return found


def aggregate_sbom_artifacts(
    release: Release, *, include_non_public: bool, readable_product_ids: Collection[str] | None = None
) -> list[ReleaseArtifact]:
    """The SBOM artifacts a release's aggregate is built from: its own, then those of every linked release.

    The release's own members follow the rule they always have: a public release
    hides members whose component is not public, unless ``include_non_public``.
    A linked member is what its own release would show this reader: all of it
    with ``include_non_public`` for a product in ``readable_product_ids`` (every
    product when that is None), otherwise only a public component of a public
    product. Without that, a link would hand a reader confined to one product,
    an OIDC bot, the private SBOMs of another.

    One SBOM pinned into two of these releases is a single member. Ordered by SBOM
    id, so the aggregate serializes the same way on every rebuild.
    """
    from sbomify.apps.core.models import Component
    from sbomify.apps.sboms.models import SBOM

    sboms_only = {"sbom__isnull": False, "sbom__bom_type": SBOM.BomType.SBOM}
    # select_related joins the whole sbom -> component -> team FK chain in one query.
    own = release.artifacts.filter(**sboms_only).select_related("sbom__component", "sbom__component__team")
    linked = ReleaseArtifact.objects.filter(release_id__in=linked_release_ids(release), **sboms_only).select_related(
        "release__product", "sbom__component", "sbom__component__team"
    )

    members: dict[str, ReleaseArtifact] = {}
    for artifact in own:
        sbom = artifact.sbom
        if sbom is None or sbom.id in members:
            continue
        if (
            include_non_public
            or not release.product.is_public
            or sbom.component.visibility == Component.Visibility.PUBLIC
        ):
            members[sbom.id] = artifact
    for artifact in linked.order_by("created_at"):
        sbom = artifact.sbom
        if sbom is None or sbom.id in members:
            continue
        readable = readable_product_ids is None or artifact.release.product_id in readable_product_ids
        public = sbom.component.visibility == Component.Visibility.PUBLIC and artifact.release.product.is_public
        if (include_non_public and readable) or public:
            members[sbom.id] = artifact
    return [members[sbom_id] for sbom_id in sorted(members)]
