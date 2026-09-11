"""Keeps a workspace's CSAF distribution marker moving forward.

``provider-metadata.json`` and the ROLIE feed both carry a "last updated"
marker, and a poller uses it to decide whether to fetch again. Deriving that
marker from the advisories currently in the feed gets the removals wrong: when
a public advisory is deleted, or stops being public, the maximum over what is
left can be *older* than the value the poller already holds, so it never looks
again and keeps serving a document we have withdrawn.

So the marker is stored on the workspace and only ever set to "now", which
makes it monotonic by construction rather than by aggregation.

It is bumped only for advisories that are public or were once public
(``made_public_at``). A purely internal or NDA-only advisory must not move a
marker the whole world can poll: that would leak the timing of embargoed work
from a document served to anyone who asks.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from sbomify.apps.security_advisories.models import SecurityAdvisory


def _affects_public_distribution(advisory: SecurityAdvisory) -> bool:
    return advisory.visibility == SecurityAdvisory.Visibility.PUBLIC or advisory.made_public_at is not None


def _bump(advisory: SecurityAdvisory) -> None:
    if not _affects_public_distribution(advisory):
        return
    from sbomify.apps.teams.models import Team

    # queryset.update() rather than team.save(): no signals, no read, and no
    # chance of clobbering a concurrent write to another column.
    Team.objects.filter(pk=advisory.team_id).update(csaf_feed_updated_at=timezone.now())


@receiver(post_save, sender=SecurityAdvisory, dispatch_uid="csaf_feed_marker_on_save")
def bump_on_save(sender: Any, instance: SecurityAdvisory, **kwargs: Any) -> None:
    _bump(instance)


@receiver(post_delete, sender=SecurityAdvisory, dispatch_uid="csaf_feed_marker_on_delete")
def bump_on_delete(sender: Any, instance: SecurityAdvisory, **kwargs: Any) -> None:
    _bump(instance)
