"""Keeps a workspace's CSAF distribution marker moving forward.

``provider-metadata.json`` and the ROLIE feed both carry a "last updated"
marker, and a poller uses it to decide whether to fetch again. Deriving that
marker from the advisories currently in the feed gets the removals wrong: when
a public advisory is deleted, or stops being public, the maximum over what is
left can be *older* than the value the poller already holds, so it never looks
again and keeps serving a document we have withdrawn.

So the marker is stored on the workspace, and three things keep it honest:

**It is bumped from every write the document is rendered from.** A CSAF
document is built from ``anonymous_projection``, which reads vulnerabilities,
product statuses, version ranges, references and public events. Watching only
``SecurityAdvisory`` would miss a CVSS edit or a posted update, which change the
document while leaving the advisory row untouched, so every model in that
projection is watched.

**It only ever moves forward, in the database.** ``Greatest`` against the stored
value rather than a plain assignment: two signals racing in Python can commit
out of order, and the later writer must not be able to install an earlier
timestamp.

**It is written after commit.** ``publish_advisory`` locks the workspace row and
then the advisory; the other services lock the advisory first. Taking the
workspace row from inside ``post_save`` would complete that cycle and deadlock,
so the update runs in its own transaction once the advisory lock is gone. A
rolled-back write correctly bumps nothing.

Advisories that are neither public nor ever were are ignored throughout. A
marker the whole world can poll must not move for internal or NDA-only work, or
it leaks the timing of an embargo from a document served to anyone who asks.
"""

from __future__ import annotations

from typing import Any, Callable

from django.db import transaction
from django.db.models import DateTimeField, F
from django.db.models.functions import Coalesce, Greatest, Now
from django.db.models.signals import post_delete, post_save

from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)

# How to get from a row the projection reads back to the advisory it belongs to.
# AdvisoryComponent is deliberately absent: the public projection never reads it.
_TO_ADVISORY: dict[type, Callable[[Any], SecurityAdvisory | None]] = {
    SecurityAdvisory: lambda row: row,
    AdvisoryVulnerability: lambda row: row.advisory,
    AdvisoryReference: lambda row: row.advisory,
    AdvisoryProduct: lambda row: row.advisory,
    AdvisoryEvent: lambda row: row.advisory,
    AdvisoryProductStatus: lambda row: row.vulnerability.advisory,
    AdvisoryVersionRange: lambda row: row.product_status.vulnerability.advisory,
}


def _affects_public_distribution(advisory: SecurityAdvisory) -> bool:
    return advisory.visibility == SecurityAdvisory.Visibility.PUBLIC or advisory.made_public_at is not None


def _bump(team_id: Any) -> None:
    from sbomify.apps.teams.models import Team

    # Greatest against the stored value, so an out-of-order commit cannot install
    # an older timestamp. Coalesce because GREATEST is NULL-propagating on some
    # backends and the column starts NULL.
    Team.objects.filter(pk=team_id).update(
        csaf_feed_updated_at=Greatest(
            Coalesce(F("csaf_feed_updated_at"), Now(), output_field=DateTimeField()),
            Now(),
            output_field=DateTimeField(),
        )
    )


def _schedule(instance: Any) -> None:
    resolve = _TO_ADVISORY.get(type(instance))
    if resolve is None:
        return
    try:
        advisory = resolve(instance)
    except (SecurityAdvisory.DoesNotExist, AttributeError):
        # A cascade delete can tear the parent away before the child's signal
        # runs. The advisory's own signal covers that case.
        return
    if advisory is None or not _affects_public_distribution(advisory):
        return

    team_id = advisory.team_id
    # After commit, so the workspace row is never taken while an advisory row is
    # held: that ordering is what would deadlock against publish_advisory.
    transaction.on_commit(lambda: _bump(team_id))


def bump_on_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    _schedule(instance)


def bump_on_delete(sender: Any, instance: Any, **kwargs: Any) -> None:
    _schedule(instance)


def connect() -> None:
    """Bind one pair of receivers per watched model.

    Per sender rather than a global receiver: an unfiltered post_save fires for
    every write anywhere in the project, and this only ever cares about seven
    models.
    """
    for model in _TO_ADVISORY:
        post_save.connect(bump_on_save, sender=model, dispatch_uid=f"csaf_marker_save_{model.__name__}")
        post_delete.connect(bump_on_delete, sender=model, dispatch_uid=f"csaf_marker_delete_{model.__name__}")
