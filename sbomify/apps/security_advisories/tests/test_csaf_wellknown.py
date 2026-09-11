"""CSAF 2.0 discovery: provider metadata, the ROLIE feed, and the TLP:WHITE tree.

The documents were always reachable over the public API; these cover the part
that makes them findable, and the part that decides what a stranger is allowed
to find. The visibility tests are the point of the file: a distribution labelled
TLP:WHITE is one document per URL for everybody, so a gated advisory must not
reach it even when the reader holding the request could read it elsewhere.
"""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlparse

import pytest
from django.test import RequestFactory
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from sbomify.apps.security_advisories import csaf_provider
from sbomify.apps.core.models import Component
from sbomify.apps.security_advisories.models import AdvisoryEvent, SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import cvss_entry, display_id
from sbomify.apps.teams.models import Team
from sbomify.apps.security_advisories.tests.test_csaf import (  # noqa: F401  (fixtures)
    SCHEMAS,
    VECTOR,
    gateway,
    rich_advisory,
    validate_csaf,
    vault,
)
from sbomify.apps.security_advisories.wellknown import (
    ProviderMetadataView,
    WhiteDocumentView,
    WhiteFeedView,
)

pytestmark = pytest.mark.django_db

BASE = "https://trust.example.com"


def _request(path: str, team=None, *, is_custom_domain: bool = True, is_trust_center_subdomain: bool = True):
    request = RequestFactory().get(path, secure=True)
    request.is_custom_domain = is_custom_domain
    request.is_trust_center_subdomain = is_trust_center_subdomain
    if team is not None:
        request.custom_domain_team = team
    return request


def _public(team):
    team.is_public = True
    team.save(update_fields=["is_public"])
    return team


def _json(response):
    return json.loads(response.content)


def _gate(team, advisory, visibility):
    """Move an already-published advisory to another visibility."""
    advisory.visibility = visibility
    advisory.save(update_fields=["visibility"])
    return advisory


class TestGating:
    """The three checks SecurityTxtView makes, made the same way here."""

    def test_404_off_a_custom_domain(self, team) -> None:
        response = ProviderMetadataView.as_view()(_request("/", _public(team), is_custom_domain=False))
        assert response.status_code == 404

    def test_404_when_workspace_is_not_public(self, team) -> None:
        # A plan-less workspace is forced public by Team.save, so going private
        # needs a paid plan first. Exactly the path a private workspace takes.
        team.billing_plan = "business"
        team.is_public = False
        team.save(update_fields=["billing_plan", "is_public"])
        assert team.is_public is False

        assert ProviderMetadataView.as_view()(_request("/", team)).status_code == 404

    def test_404_when_byod_domain_is_unvalidated(self, team) -> None:
        team = _public(team)
        team.custom_domain_validated = False
        response = ProviderMetadataView.as_view()(
            _request("/", team, is_trust_center_subdomain=False),
        )
        assert response.status_code == 404


class TestProviderMetadata:
    def test_validates_against_the_oasis_provider_schema(self, team, rich_advisory) -> None:  # noqa: F811
        """The test that matters to a CSAF aggregator: the published schema, not our reading of it."""
        payload = _json(ProviderMetadataView.as_view()(_request(csaf_provider.PROVIDER_METADATA_PATH, _public(team))))

        schema = json.loads((SCHEMAS / "provider_json_schema.json").read_text())
        registry = Registry().with_resource(
            "https://docs.oasis-open.org/csaf/csaf/v2.0/csaf_json_schema.json",
            Resource.from_contents(
                json.loads((SCHEMAS / "csaf_json_schema.json").read_text()), default_specification=DRAFT7
            ),
        )
        validator_for(schema)(schema, registry=registry).validate(payload)

    def test_shape_is_csaf_7_1_8(self, team, rich_advisory) -> None:  # noqa: F811
        payload = _json(ProviderMetadataView.as_view()(_request(csaf_provider.PROVIDER_METADATA_PATH, _public(team))))

        assert payload["metadata_version"] == "2.0"
        assert payload["role"] == "csaf_provider"
        assert payload["canonical_url"].endswith(csaf_provider.PROVIDER_METADATA_PATH)
        assert payload["publisher"]["category"] == "vendor"
        feed = payload["distributions"][0]["rolie"]["feeds"][0]
        assert feed["tlp_label"] == "WHITE"
        assert feed["url"].endswith(csaf_provider.WHITE_FEED_PATH)

    def test_served_before_the_first_advisory(self, team) -> None:
        """An empty provider is how an aggregator finds you in advance."""
        response = ProviderMetadataView.as_view()(_request(csaf_provider.PROVIDER_METADATA_PATH, _public(team)))
        assert response.status_code == 200
        assert _json(response)["role"] == "csaf_provider"


class TestWhiteFeed:
    def test_lists_a_public_advisory(self, team, rich_advisory) -> None:  # noqa: F811
        feed = _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, _public(team))))["feed"]

        assert feed["category"] == [{"scheme": csaf_provider.ROLIE_CATEGORY_SCHEME, "term": "csaf"}]
        assert len(feed["entry"]) == 1
        entry = feed["entry"][0]
        assert entry["format"] == {"schema": csaf_provider.CSAF_SCHEMA_URL, "version": "2.0"}
        assert entry["content"]["src"] == entry["link"][0]["href"]
        assert entry["content"]["src"].endswith(csaf_provider.csaf_filename(rich_advisory))

    def test_atom_ids_are_absolute_iris(self, team, rich_advisory) -> None:  # noqa: F811
        """RFC 4287: an Atom id is an IRI, not a bare tracking id."""
        feed = _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, _public(team))))["feed"]

        assert urlparse(feed["id"]).scheme and urlparse(feed["id"]).netloc
        assert feed["id"].endswith(csaf_provider.WHITE_FEED_PATH)
        entry = feed["entry"][0]
        assert urlparse(entry["id"]).scheme and urlparse(entry["id"]).netloc
        assert entry["id"] == entry["link"][0]["href"]
        # The tracking id still identifies the advisory where CSAF asks for it.
        assert display_id(rich_advisory) not in (feed["id"], entry["id"].rsplit("/", 1)[0])

    def test_a_gated_advisory_never_appears(self, team, rich_advisory) -> None:  # noqa: F811
        _gate(team, rich_advisory, SecurityAdvisory.Visibility.GATED)

        feed = _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, _public(team))))["feed"]
        assert feed["entry"] == []

    def test_a_private_advisory_never_appears(self, team, rich_advisory) -> None:  # noqa: F811
        _gate(team, rich_advisory, SecurityAdvisory.Visibility.PRIVATE)

        feed = _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, _public(team))))["feed"]
        assert feed["entry"] == []

    def test_a_draft_never_appears(self, team, sample_user, gateway) -> None:  # noqa: F811
        SecurityAdvisory.objects.create(team=team, title="Not published yet")

        feed = _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, _public(team))))["feed"]
        assert feed["entry"] == []


class TestWhiteDocument:
    def _fetch(self, team, advisory):
        path = csaf_provider.document_path(advisory)
        year, filename = path.rsplit("/", 2)[-2:]
        return WhiteDocumentView.as_view()(_request(path, team), year=year, filename=filename)

    def test_serves_a_schema_valid_document(self, team, rich_advisory) -> None:  # noqa: F811
        response = self._fetch(_public(team), rich_advisory)

        assert response.status_code == 200
        document = _json(response)
        validate_csaf(document)
        assert document["document"]["distribution"]["tlp"]["label"] == "WHITE"
        assert document["document"]["tracking"]["id"] == display_id(rich_advisory)

    def test_filename_follows_csaf_5_1(self, team, rich_advisory) -> None:  # noqa: F811
        """Lowercase the tracking id, and the filename matches /document/tracking/id."""
        tracking_id = display_id(rich_advisory)
        assert tracking_id == "TESTTEAM-SA-2026-0001"

        assert csaf_provider.csaf_filename(rich_advisory) == "testteam-sa-2026-0001.json"

    def test_a_gated_advisory_is_not_served(self, team, rich_advisory) -> None:  # noqa: F811
        """Even to a reader who could read it on the trust center: this URL is WHITE."""
        team = _public(team)
        path = csaf_provider.document_path(rich_advisory)
        _gate(team, rich_advisory, SecurityAdvisory.Visibility.GATED)

        year, filename = path.rsplit("/", 2)[-2:]
        assert WhiteDocumentView.as_view()(_request(path, team), year=year, filename=filename).status_code == 404

    def test_unknown_filename_is_404(self, team, rich_advisory) -> None:  # noqa: F811
        response = WhiteDocumentView.as_view()(
            _request("/", _public(team)), year="2026", filename="nothing-here.json"
        )
        assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestDistributionMarker:
    """The marker a poller uses to decide whether to fetch again.

    ``transaction=True`` because the marker is written from ``on_commit``: the
    default rolled-back test transaction never commits, so the callbacks that
    carry the whole mechanism would never run.
    """

    def _marker(self, team):
        team.refresh_from_db()
        return _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, team)))["feed"]["updated"]

    def test_publishing_moves_it_forward(self, team, rich_advisory) -> None:  # noqa: F811
        team = _public(team)
        team.refresh_from_db()
        assert team.csaf_feed_updated_at is not None

    def test_deleting_the_newest_advisory_does_not_move_it_backwards(self, team, rich_advisory) -> None:  # noqa: F811
        """The bug an aggregate over the surviving rows would have: a poller misses the removal."""
        team = _public(team)
        before = self._marker(team)

        rich_advisory.delete()

        after = self._marker(team)
        assert _json(WhiteFeedView.as_view()(_request(csaf_provider.WHITE_FEED_PATH, team)))["feed"]["entry"] == []
        assert after > before

    def test_re_embargoing_does_not_move_it_backwards(self, team, rich_advisory) -> None:  # noqa: F811
        team = _public(team)
        before = self._marker(team)

        _gate(team, rich_advisory, SecurityAdvisory.Visibility.GATED)

        assert self._marker(team) > before

    def test_a_never_public_advisory_does_not_move_it(self, team) -> None:
        """A marker the world can poll must not leak the timing of embargoed work."""
        team = _public(team)
        team.csaf_feed_updated_at = None
        team.save(update_fields=["csaf_feed_updated_at"])

        SecurityAdvisory.objects.create(
            team=team,
            title="Embargoed",
            visibility=SecurityAdvisory.Visibility.GATED,
        )

        team.refresh_from_db()
        assert team.csaf_feed_updated_at is None

    def test_provider_metadata_and_feed_agree(self, team, rich_advisory) -> None:  # noqa: F811
        # The signal writes with queryset.update(), so the in-memory row is stale
        # until reloaded. A request reloads it in middleware; a test must say so.
        team = _public(team)
        team.refresh_from_db()

        metadata = _json(ProviderMetadataView.as_view()(_request(csaf_provider.PROVIDER_METADATA_PATH, team)))

        assert metadata["last_updated"] == self._marker(team)

    def test_a_nested_write_moves_it(self, team, rich_advisory) -> None:  # noqa: F811
        """A CVSS edit changes the document without touching the advisory row."""
        team = _public(team)
        before = self._marker(team)

        vulnerability = rich_advisory.vulnerabilities.first()
        vulnerability.cvss_scores = [cvss_entry(7.5, VECTOR)]
        vulnerability.save(update_fields=["cvss_scores"])

        assert self._marker(team) > before

    def test_a_posted_update_moves_it(self, team, rich_advisory) -> None:  # noqa: F811
        """An event is part of the rendered document's revision history."""
        team = _public(team)
        before = self._marker(team)

        AdvisoryEvent.objects.create(
            advisory=rich_advisory,
            event_type=AdvisoryEvent.EventType.UPDATE,
            body="Fix released.",
        )

        assert self._marker(team) > before

    def test_the_marker_never_moves_backwards(self, team, rich_advisory) -> None:  # noqa: F811
        """Greatest against the stored value, so a late writer cannot install an older time."""
        team = _public(team)
        team.refresh_from_db()
        ahead = team.csaf_feed_updated_at + timedelta(days=1)
        Team.objects.filter(pk=team.pk).update(csaf_feed_updated_at=ahead)

        rich_advisory.title = "Retitled"
        rich_advisory.save(update_fields=["title"])

        team.refresh_from_db()
        assert team.csaf_feed_updated_at >= ahead

    def test_a_draft_with_public_visibility_does_not_move_it(self, team) -> None:
        """is_externally_visible excludes a draft whatever its visibility says."""
        team = _public(team)
        Team.objects.filter(pk=team.pk).update(csaf_feed_updated_at=None)

        SecurityAdvisory.objects.create(
            team=team,
            title="Drafted, not disclosed",
            visibility=SecurityAdvisory.Visibility.PUBLIC,
        )

        team.refresh_from_db()
        assert team.csaf_feed_updated_at is None

    def test_an_internal_comment_does_not_move_it(self, team, rich_advisory) -> None:  # noqa: F811
        """The timeline renders PUBLIC_EVENT_TYPES only, so a comment changes no document."""
        team = _public(team)
        before = self._marker(team)

        AdvisoryEvent.objects.create(
            advisory=rich_advisory,
            event_type=AdvisoryEvent.EventType.COMMENT,
            body="Internal note.",
        )

        assert self._marker(team) == before

    def test_renaming_a_named_product_moves_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        """A product name is printed in the document, so a rename changes it."""
        team = _public(team)
        before = self._marker(team)

        gateway.name = "Acme Gateway Pro"
        gateway.save(update_fields=["name"])

        assert self._marker(team) > before

    def test_hiding_a_component_moves_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        """Component visibility decides whether the product is listed at all."""
        team = _public(team)
        before = self._marker(team)

        component = gateway.components.first()
        component.visibility = Component.Visibility.PRIVATE
        component.save(update_fields=["visibility"])

        assert self._marker(team) > before
