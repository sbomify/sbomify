"""CSAF 2.0 discovery: provider metadata, a ROLIE feed, and the documents it lists.

The CSAF documents themselves have been served from the public API since the
feature shipped. What was missing is the part a machine uses to *find* them:
CSAF 2.0 section 7.1.8 defines ``provider-metadata.json`` as the entry point, and
RFC 9116's ``CSAF`` field is how a reader gets to that from ``security.txt``.

**Everything here is TLP:WHITE and only TLP:WHITE.** A distribution is one
document per URL for every reader, so it is built from
``trust_center.public_advisories`` and ``anonymous_viewer_scope`` rather than
from the requesting reader's scope. Serving a gated advisory here — even to
someone entitled to read it on the trust center — would hand an aggregator
content labelled WHITE that is not, and would confirm the existence of an
embargoed advisory that ``get_public_advisory`` deliberately 404s.

Specs: https://docs.oasis-open.org/csaf/csaf/v2.0/csaf-v2.0.html and RFC 8322.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from sbomify.apps.security_advisories.csaf import CSAF_VERSION, render_csaf
from sbomify.apps.security_advisories.expressions import csaf_filename_expression, csaf_year_expression
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import display_id
from sbomify.apps.security_advisories.services.trust_center import (
    anonymous_projection,
    public_advisories,
    public_advisory_index,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sbomify.apps.teams.models import Team

CSAF_SCHEMA_URL = "https://docs.oasis-open.org/csaf/csaf/v2.0/csaf_json_schema.json"
ROLIE_CATEGORY_SCHEME = "urn:ietf:params:rolie:category:information-type"

PROVIDER_METADATA_PATH = "/.well-known/csaf/provider-metadata.json"
WHITE_FEED_PATH = "/.well-known/csaf/white/feed-tlp-white.json"

# CSAF 2.0 section 5.1: lowercase the tracking id and replace everything outside
# this set with an underscore. Applied to the id the document actually carries,
# which is display_id, so the filename and /document/tracking/id agree.
_FILENAME_ALLOWED = re.compile(r"[^+\-a-z0-9]")

# We serve over TLS, the documents are valid CSAF, TLP:WHITE is free to anyone,
# and this module adds the provider metadata and a ROLIE distribution. We do not
# sign documents or publish hashes, so "csaf_trusted_provider" would be a claim
# we cannot back.
PROVIDER_ROLE = "csaf_provider"


def csaf_filename(advisory: Any) -> str:
    """The filename CSAF 2.0 section 5.1 requires for this advisory."""
    return f"{_FILENAME_ALLOWED.sub('_', str(display_id(advisory)).lower())}.json"


def _year(advisory: Any) -> str:
    moment = advisory.published_at or advisory.created_at
    return str(moment.year) if moment else str(timezone.now().year)


def document_path(advisory: Any) -> str:
    """Where one TLP:WHITE document lives, under the year it was released."""
    return f"/.well-known/csaf/white/{_year(advisory)}/{csaf_filename(advisory)}"


def _stamp(value: Any) -> str:
    return value.isoformat() if value else timezone.now().isoformat()


def distribution_marker(team: Team) -> str:
    """When this workspace's TLP:WHITE distribution last changed.

    Read from the workspace rather than aggregated over the advisories still
    present, because deleting or re-embargoing a public advisory takes the row
    holding the maximum away with it: the aggregate would move backwards and a
    poller holding the older value would never fetch again. ``signals.py`` only
    ever moves this forward.

    Falls back to the workspace's own creation date, so a workspace that has
    published nothing yet still returns something stable rather than a marker
    that changes on every request.
    """
    return _stamp(team.csaf_feed_updated_at or team.created_at)


def provider_metadata(team: Team, *, base_url: str) -> dict[str, Any]:
    """CSAF 2.0 section 7.1.8 provider metadata for one workspace.

    ``last_updated`` is the workspace's distribution marker, so a polling
    aggregator can tell a changed distribution from an unchanged one without
    refetching the feed. An empty feed is legitimate CSAF and is what a
    workspace serves before its first disclosure; it is how aggregators find
    you in advance rather than after.
    """
    return {
        "canonical_url": f"{base_url}{PROVIDER_METADATA_PATH}",
        "last_updated": distribution_marker(team),
        "metadata_version": CSAF_VERSION,
        # Both are required by the provider schema, and both default to true
        # there. Stated explicitly rather than left to a consumer's default: the
        # point of publishing this is to be listed and mirrored.
        "list_on_CSAF_aggregators": True,
        "mirror_on_CSAF_aggregators": True,
        "publisher": {
            "category": "vendor",
            "name": team.display_name,
            "namespace": base_url,
        },
        "role": PROVIDER_ROLE,
        "distributions": [
            {
                "rolie": {
                    "feeds": [
                        {
                            "summary": f"TLP:WHITE security advisories published by {team.display_name}.",
                            "tlp_label": "WHITE",
                            "url": f"{base_url}{WHITE_FEED_PATH}",
                        }
                    ]
                }
            }
        ],
    }


def rolie_feed(team: Team, *, base_url: str) -> dict[str, Any]:
    """The RFC 8322 feed listing every TLP:WHITE advisory this workspace has published."""
    entries = []
    for advisory in public_advisory_index(team):
        url = f"{base_url}{document_path(advisory)}"
        # Related writes can change the document without saving the advisory.
        # Conservatively revalidate every entry when the distribution changes.
        updated = max(
            moment for moment in (advisory.updated_at, advisory.published_at, team.csaf_feed_updated_at) if moment
        )
        entries.append(
            {
                # RFC 4287 requires an Atom id to be an absolute IRI, so the
                # document's own URL rather than the bare tracking id. The
                # tracking id is still in /document/tracking/id and the filename.
                "id": url,
                "title": advisory.title,
                "published": _stamp(advisory.published_at),
                "updated": _stamp(updated),
                "link": [{"rel": "self", "href": url}],
                "format": {"schema": CSAF_SCHEMA_URL, "version": CSAF_VERSION},
                "content": {"type": "application/json", "src": url},
            }
        )
    return {
        "feed": {
            # Absolute IRI here too: the feed's own canonical URL.
            "id": f"{base_url}{WHITE_FEED_PATH}",
            "title": f"{team.display_name} security advisories (TLP:WHITE)",
            "link": [{"rel": "self", "href": f"{base_url}{WHITE_FEED_PATH}"}],
            "category": [{"scheme": ROLIE_CATEGORY_SCHEME, "term": "csaf"}],
            "updated": distribution_marker(team),
            "entry": entries,
        }
    }


def white_document(team: Team, year: str, filename: str, *, base_url: str, generator: str) -> dict[str, Any] | None:
    """Resolve one public document using the indexed CSAF filename expression."""
    if not re.fullmatch(r"[0-9]{4}", year):
        return None
    try:
        advisory = (
            public_advisories(team)
            .alias(_csaf_filename=csaf_filename_expression(), _csaf_year=csaf_year_expression())
            .get(_csaf_filename=filename, _csaf_year=int(year))
        )
    except (SecurityAdvisory.DoesNotExist, SecurityAdvisory.MultipleObjectsReturned):
        # Normalization collisions must not serve the wrong advisory.
        return None
    if _year(advisory) != year:
        return None
    projection = anonymous_projection(team, advisory)
    return render_csaf(
        projection,
        publisher_name=team.display_name,
        publisher_namespace=base_url,
        self_url=f"{base_url}{document_path(advisory)}",
        generator=generator,
    )
