"""Which advisories bear on a release.

The model stores affected versions as strings, deliberately: an advisory has to
describe versions that predate sbomify or were never cut as Releases at all. The
``Release`` pins beside them are optional sugar. That is the right storage
choice, and it is why a materialised link table would be the wrong one. Such a
table could only hold releases sbomify already knows about, so an advisory
saying "affects everything below 2.0" would silently miss the 2.0-rc1 someone
cuts tomorrow, and every new release would owe a backfill.

So the edge is resolved on read. Two sources feed it: the pins, which are
walkable now that they have reverse names, and the version strings compared
against the release's own version.

Comparison uses :mod:`packaging`, which the plugins already rely on. Anything it
cannot parse is reported as undetermined rather than guessed at. Saying "not
affected" about a release nobody could actually compare is the one answer worth
avoiding.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from sbomify.apps.security_advisories.models import AdvisoryVersionRange, SecurityAdvisory

if TYPE_CHECKING:  # pragma: no cover
    from sbomify.apps.core.models import Release

PINNED = "pinned"
VERSION = "version"
UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class ReleaseImpact:
    """One advisory's bearing on one release."""

    advisory: SecurityAdvisory
    #: PINNED when a range names this Release outright, VERSION when the
    #: release's version falls inside a range, UNDETERMINED when neither could
    #: be established because a version string would not parse.
    matched_by: str
    #: The ranges that could not be compared, so a caller can say which.
    undetermined: tuple[str, ...] = ()

    @property
    def is_certain(self) -> bool:
        return self.matched_by != UNDETERMINED


def _parse(raw: str) -> Version | None:
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def version_in_range(version: str, advisory_range: AdvisoryVersionRange) -> bool | None:
    """Is ``version`` inside this range? ``None`` when something will not parse.

    OSV semantics, matching the model's own constraint that a range carries
    ``fixed`` or ``last_affected`` but never both: ``introduced`` is inclusive,
    ``fixed`` exclusive, ``last_affected`` inclusive, and an absent endpoint is
    unbounded on that side.
    """
    target = _parse(version)
    if target is None:
        return None

    bounds = (
        (advisory_range.introduced, operator.ge),  # target >= introduced
        (advisory_range.fixed, operator.lt),  # target <  fixed
        (advisory_range.last_affected, operator.le),  # target <= last_affected
    )
    for raw, satisfies in bounds:
        if not raw:
            continue
        bound = _parse(raw)
        if bound is None:
            return None
        if not satisfies(target, bound):
            return False
    return True


def advisories_affecting_release(release: Release, *, published_only: bool = True) -> list[ReleaseImpact]:
    """Every advisory that bears on ``release``, pinned or resolved by version.

    Args:
        release: the product release to assess.
        published_only: drafts are internal, so anything outward-facing wants
            them excluded. Pass ``False`` for the workspace's own view.
    """
    ranges = (
        AdvisoryVersionRange.objects.filter(
            product_status__advisory_product__product_id=release.product_id,
        )
        .select_related("product_status__vulnerability__advisory")
        .order_by("created_at")
    )
    if published_only:
        ranges = ranges.filter(product_status__vulnerability__advisory__status=SecurityAdvisory.Status.PUBLISHED)

    matched: dict[str, ReleaseImpact] = {}
    unparsed: dict[str, tuple[SecurityAdvisory, list[str]]] = {}

    for advisory_range in ranges:
        advisory = advisory_range.product_status.vulnerability.advisory

        # A range whose fix IS this release does not make the release affected.
        if advisory_range.fixed_release_id == release.pk:
            continue

        pinned = release.pk in (advisory_range.introduced_release_id, advisory_range.last_affected_release_id)
        if pinned:
            matched[advisory.pk] = ReleaseImpact(advisory=advisory, matched_by=PINNED)
            continue

        verdict = version_in_range(release.version, advisory_range)
        if verdict is None:
            _, seen = unparsed.setdefault(advisory.pk, (advisory, []))
            seen.append(str(advisory_range))
        elif verdict:
            matched.setdefault(advisory.pk, ReleaseImpact(advisory=advisory, matched_by=VERSION))

    # An advisory already matched outright is not made uncertain by a second
    # range nobody could parse.
    for advisory_id, (advisory, seen) in unparsed.items():
        matched.setdefault(
            advisory_id,
            ReleaseImpact(advisory=advisory, matched_by=UNDETERMINED, undetermined=tuple(seen)),
        )

    return list(matched.values())
