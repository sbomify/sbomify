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
from django.db import transaction
from django.test import RequestFactory
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from sbomify.apps.core.models import Component
from sbomify.apps.security_advisories import csaf_provider
from sbomify.apps.security_advisories.models import AdvisoryEvent, SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import cvss_entry, display_id
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
from sbomify.apps.teams.models import Team

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
        response = WhiteDocumentView.as_view()(_request("/", _public(team)), year="2026", filename="nothing-here.json")
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

    @pytest.mark.parametrize("visibility", ["gated", "private"])
    def test_later_embargoed_writes_do_not_move_it(self, team, rich_advisory, gateway, visibility) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        # Deliberately retain the child instance's cached, formerly public parent.
        vulnerability = rich_advisory.vulnerabilities.first()
        _ = vulnerability.advisory
        _gate(team, rich_advisory, visibility)
        before = self._marker(team)
        rich_advisory.summary = "Private investigation"
        rich_advisory.save(update_fields=["summary"])
        vulnerability.cvss_scores = [cvss_entry(7.5, VECTOR)]
        vulnerability.save(update_fields=["cvss_scores"])
        gateway.name = "Private rename"
        gateway.save(update_fields=["name"])
        assert self._marker(team) == before
        rich_advisory.delete()
        assert self._marker(team) == before

    @pytest.mark.parametrize("reverse", [False, True])
    @pytest.mark.parametrize("operation", ["add", "remove", "clear"])
    def test_m2m_changes_move_it(self, team, rich_advisory, gateway, reverse, operation) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        component = gateway.components.first()
        if operation == "add":
            gateway.components.remove(component)
        before = self._marker(team)
        manager = gateway.components if reverse else component.products
        target = component if reverse else gateway
        if operation == "clear":
            manager.clear()
        else:
            getattr(manager, operation)(target)
        assert self._marker(team) > before

    @pytest.mark.parametrize("entity", ["product", "component"])
    def test_deletion_captures_links_before_they_disappear(self, team, rich_advisory, gateway, entity) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        before = self._marker(team)
        row = gateway if entity == "product" else gateway.components.first()
        row.delete()
        assert self._marker(team) > before

    @pytest.mark.parametrize("entity", ["advisory", "product", "component"])
    def test_rolled_back_deletion_does_not_move_it(self, team, rich_advisory, gateway, entity) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        before = self._marker(team)
        row = {"advisory": rich_advisory, "product": gateway, "component": gateway.components.first()}[entity]
        with transaction.atomic():
            row.delete()
            transaction.set_rollback(True)
        assert self._marker(team) == before

    @pytest.mark.parametrize("change", ["cvss", "product", "publisher"])
    def test_entry_updated_tracks_related_writes(self, team, rich_advisory, gateway, change) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        team.refresh_from_db()
        before = csaf_provider.rolie_feed(team, base_url=BASE)["feed"]["entry"][0]["updated"]
        if change == "cvss":
            vulnerability = rich_advisory.vulnerabilities.first()
            vulnerability.cvss_scores = [cvss_entry(7.5, VECTOR)]
            vulnerability.save(update_fields=["cvss_scores"])
        elif change == "product":
            gateway.name = "New name"
            gateway.save(update_fields=["name"])
        else:
            team.name = "New publisher"
            team.save(update_fields=["name"])
        team.refresh_from_db()
        feed = csaf_provider.rolie_feed(team, base_url=BASE)["feed"]
        assert feed["entry"][0]["updated"] > before
        assert feed["updated"] == feed["entry"][0]["updated"]

    def test_renaming_an_empty_provider_moves_metadata(self, team) -> None:
        team = _public(team)
        before = self._marker(team)
        team.name = "Renamed publisher"
        team.save(update_fields=["name"])
        assert self._marker(team) > before
        payload = csaf_provider.provider_metadata(team, base_url=BASE)
        assert payload["publisher"]["name"] == "Renamed publisher"
        assert payload["last_updated"] > before

    def test_unrelated_team_save_does_not_move_it(self, team, rich_advisory) -> None:  # noqa: F811 (shared pytest fixtures)
        team = _public(team)
        before = self._marker(team)
        team.save(update_fields=["security_txt_config"])
        assert self._marker(team) == before

    def test_bulk_downgrade_visibility_updates_feed_and_entry(self, team, rich_advisory, gateway) -> None:  # noqa: F811 (shared pytest fixtures)
        from sbomify.apps.billing.billing_helpers import handle_community_downgrade_visibility

        team = _public(team)
        component = gateway.components.first()
        component.visibility = Component.Visibility.PRIVATE
        component.save(update_fields=["visibility"])
        before = self._marker(team)
        handle_community_downgrade_visibility(team)
        assert self._marker(team) > before
        feed = csaf_provider.rolie_feed(team, base_url=BASE)["feed"]
        assert feed["entry"][0]["updated"] == feed["updated"]

    def test_bulk_downgrade_does_not_expose_embargoed_activity(self, team, rich_advisory, gateway) -> None:  # noqa: F811 (shared pytest fixtures)
        from sbomify.apps.billing.billing_helpers import handle_community_downgrade_visibility

        team = _public(team)
        _gate(team, rich_advisory, SecurityAdvisory.Visibility.GATED)
        component = gateway.components.first()
        component.visibility = Component.Visibility.PRIVATE
        component.save(update_fields=["visibility"])
        before = self._marker(team)
        handle_community_downgrade_visibility(team)
        assert self._marker(team) == before

    def test_direct_through_model_writes_move_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        from sbomify.apps.sboms.models import ProductComponent

        team = _public(team)
        component = gateway.components.first()
        link = ProductComponent.objects.get(product=gateway, component=component)
        before = self._marker(team)
        link.delete()
        assert self._marker(team) > before
        before = self._marker(team)
        ProductComponent.objects.create(product=gateway, component=component)
        assert self._marker(team) > before

    @pytest.mark.parametrize("hidden", ["product", "component"])
    def test_hidden_product_edits_do_not_move_it(self, team, rich_advisory, gateway, hidden) -> None:  # noqa: F811
        team = _public(team)
        if hidden == "product":
            gateway.is_public = False
            gateway.save(update_fields=["is_public"])
        else:
            component = gateway.components.first()
            component.visibility = Component.Visibility.PRIVATE
            component.save(update_fields=["visibility"])
        before = self._marker(team)
        gateway.name = "Secret project name"
        gateway.save(update_fields=["name"])
        assert self._marker(team) == before

    def test_unrendered_component_edits_do_not_move_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        team = _public(team)
        before = self._marker(team)
        component = gateway.components.first()
        component.name = "Internal component name"
        component.save(update_fields=["name"])
        assert self._marker(team) == before

    def test_adding_private_component_does_not_move_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        team = _public(team)
        before = self._marker(team)
        component = Component.objects.create(
            name="Hidden component", team=team, visibility=Component.Visibility.PRIVATE
        )
        gateway.components.add(component)
        assert self._marker(team) == before
        gateway.components.remove(component)
        assert self._marker(team) == before

    @pytest.mark.parametrize("kind", ["product", "status", "version"])
    @pytest.mark.parametrize("operation", ["edit", "delete"])
    def test_hidden_product_children_do_not_move_it(self, team, rich_advisory, gateway, kind, operation) -> None:  # noqa: F811
        team = _public(team)
        gateway.is_public = False
        gateway.save(update_fields=["is_public"])
        link = rich_advisory.products.get(product=gateway)
        status = link.statuses.first()
        row, field, value = {
            "product": (link, "product_name", "Internal alias"),
            "status": (status, "action_statement", "Internal fix plan"),
            "version": (status.version_ranges.first(), "fixed", "2.17.2"),
        }[kind]
        before = self._marker(team)
        if operation == "delete":
            row.delete()
        else:
            setattr(row, field, value)
            row.save(update_fields=[field])
        assert self._marker(team) == before

    def test_portfolio_status_changes_still_move_it(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        team = _public(team)
        status = rich_advisory.products.get(product=gateway).statuses.first()
        status.advisory_product = None
        status.save(update_fields=["advisory_product"])
        before = self._marker(team)
        status.action_statement = "Update all installations"
        status.save(update_fields=["action_statement"])
        assert self._marker(team) > before

    def test_workspace_visibility_transitions_move_it(self, team, rich_advisory) -> None:  # noqa: F811
        team = _public(team)
        before = self._marker(team)
        team.billing_plan = "business"
        team.is_public = False
        team.save(update_fields=["billing_plan", "is_public"])
        team.refresh_from_db()
        assert team.csaf_feed_updated_at.isoformat() > before
        assert ProviderMetadataView.as_view()(_request("/", team)).status_code == 404
        before = team.csaf_feed_updated_at
        team.is_public = True
        team.save(update_fields=["is_public"])
        team.refresh_from_db()
        assert team.csaf_feed_updated_at > before
        assert ProviderMetadataView.as_view()(_request("/", team)).status_code == 200

    def test_large_bulk_downgrade_keeps_sql_bounded(self, team, rich_advisory, gateway) -> None:  # noqa: F811
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from sbomify.apps.billing.billing_helpers import handle_community_downgrade_visibility

        Component.objects.bulk_create(
            [
                Component(team=team, name=f"Private component {i}", visibility=Component.Visibility.PRIVATE)
                for i in range(1400)
            ]
        )
        component = gateway.components.first()
        component.visibility = Component.Visibility.PRIVATE
        component.save(update_fields=["visibility"])
        before = self._marker(team)
        with CaptureQueriesContext(connection) as queries:
            handle_community_downgrade_visibility(team)
        assert self._marker(team) > before
        assert Component.objects.filter(team=team, visibility=Component.Visibility.PRIVATE).count() == 0
        assert max(len(query["sql"]) for query in queries) < 5000

    def test_migration_initializes_populated_feeds_without_overwriting_markers(self, team, rich_advisory) -> None:  # noqa: F811
        from importlib import import_module
        from types import SimpleNamespace

        from django.apps import apps
        from django.db import connection

        initialize = import_module(
            "sbomify.apps.security_advisories.migrations.0007_initialize_csaf_markers"
        ).initialize_markers
        Team.objects.filter(pk=team.pk).update(csaf_feed_updated_at=None)
        initialize(apps, SimpleNamespace(connection=connection))
        team.refresh_from_db()
        assert team.csaf_feed_updated_at >= rich_advisory.updated_at
        marker = team.csaf_feed_updated_at
        initialize(apps, SimpleNamespace(connection=connection))
        team.refresh_from_db()
        assert team.csaf_feed_updated_at == marker


class TestDocumentLookup:
    def test_fetch_does_not_load_other_advisories(self, team, rich_advisory) -> None:  # noqa: F811
        from django.db.models.signals import post_init
        from django.utils import timezone

        now = timezone.now()
        SecurityAdvisory.objects.bulk_create(
            [
                SecurityAdvisory(
                    team=team,
                    title=f"Other advisory {i}",
                    tracking_id=f"OTHER-SA-2026-{i:04d}",
                    status=SecurityAdvisory.Status.PUBLISHED,
                    visibility=SecurityAdvisory.Visibility.PUBLIC,
                    published_at=now,
                    made_public_at=now,
                )
                for i in range(20)
            ]
        )
        loaded = []

        def record(sender, instance, **kwargs):
            loaded.append(instance.pk)

        post_init.connect(record, sender=SecurityAdvisory)
        try:
            path = csaf_provider.document_path(rich_advisory)
            year, filename = path.rsplit("/", 2)[-2:]
            document = csaf_provider.white_document(team, year, filename, base_url=BASE, generator="test")
        finally:
            post_init.disconnect(record, sender=SecurityAdvisory)
        assert document is not None
        assert loaded == [rich_advisory.pk]

    @pytest.mark.parametrize("tracking_id", ["Mixed.Case/ID", "A+B-2026:1", "ACME-SA-2026-0001"])
    def test_indexed_lookup_uses_csaf_normalization(self, team, tracking_id) -> None:
        from django.utils import timezone

        now = timezone.now()
        advisory = SecurityAdvisory.objects.create(
            team=team,
            title="Imported public advisory",
            tracking_id=tracking_id,
            status=SecurityAdvisory.Status.PUBLISHED,
            visibility=SecurityAdvisory.Visibility.PUBLIC,
            published_at=now,
            made_public_at=now,
        )
        filename = csaf_provider.csaf_filename(advisory)
        document = csaf_provider.white_document(team, str(now.year), filename, base_url=BASE, generator="test")
        assert document is not None
        assert document["document"]["tracking"]["id"] == tracking_id
        assert csaf_provider.white_document(team, "1999", filename, base_url=BASE, generator="test") is None

    @pytest.mark.parametrize("collision", ["same_year", "different_year", "private"])
    def test_normalized_collisions_are_consistent_in_feed_and_lookup(self, team, collision) -> None:
        from django.utils import timezone

        now = timezone.now()
        advisories = []
        for i, tracking in enumerate(["Mixed.Case/ID", "Mixed?Case/ID"]):
            published = now.replace(year=now.year - i) if collision == "different_year" else now
            advisories.append(
                SecurityAdvisory.objects.create(
                    team=team,
                    title=tracking,
                    tracking_id=tracking,
                    status=SecurityAdvisory.Status.PUBLISHED,
                    visibility=SecurityAdvisory.Visibility.PRIVATE
                    if collision == "private" and i
                    else SecurityAdvisory.Visibility.PUBLIC,
                    published_at=published,
                    made_public_at=published if collision != "private" or not i else None,
                )
            )
        feed = csaf_provider.rolie_feed(team, base_url=BASE)["feed"]["entry"]
        assert len(feed) == {"same_year": 0, "different_year": 2, "private": 1}[collision]
        for entry in feed:
            year, filename = entry["content"]["src"].rsplit("/", 2)[-2:]
            assert csaf_provider.white_document(team, year, filename, base_url=BASE, generator="test") is not None
        if collision == "same_year":
            assert (
                csaf_provider.white_document(
                    team, str(now.year), csaf_provider.csaf_filename(advisories[0]), base_url=BASE, generator="test"
                )
                is None
            )
