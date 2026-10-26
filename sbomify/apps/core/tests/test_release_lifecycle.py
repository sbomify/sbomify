"""Where a release stands: supersession edges, support dates, withdrawn and archived.

The edge is the predecessor's supersededBy CLE event and the Release columns are
derived from the event stream, so most of these tests write events through the
service and read the columns back.
"""

from __future__ import annotations

import importlib
import logging
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.apps import apps as django_apps
from django.test import Client
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Release
from sbomify.apps.core.services.cle import create_release_cle_event, create_release_support_definition
from sbomify.apps.core.services.release_lifecycle import (
    MAX_SUCCESSORS,
    recompute_release_lifecycle,
    set_release_state,
    tracked_releases,
)
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import Product, ReleaseCLEEvent

backfill = importlib.import_module("sbomify.apps.core.migrations.0034_backfill_release_lifecycle")

PAST = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)


def _release(product: Product, name: str, **fields: object) -> Release:
    return Release.objects.create(product=product, name=name, version=name, **fields)


def _event(release: Release, event_type: str, effective: datetime = PAST, **fields: object) -> ReleaseCLEEvent:
    result = create_release_cle_event(release, event_type, effective, **fields)
    assert result.ok, result.error
    assert result.value is not None
    return result.value


def _supersede(predecessor: Release, successor: str, *, drop_in: bool = True, effective: datetime = PAST):
    return create_release_cle_event(
        predecessor, "supersededBy", effective, superseded_by_version=successor, drop_in=drop_in
    )


def _withdraw_event(event: ReleaseCLEEvent) -> None:
    _event(event.release, "withdrawn", withdrawn_event_id=event.event_id)


def _fresh(release: Release) -> Release:
    return Release.objects.select_related("product").get(pk=release.pk)


def _on(day: datetime) -> dict[str, object]:
    return {"versions": [{"version": "any"}], "effective": day}


@pytest.mark.django_db
class TestDerivedDates:
    def test_end_of_support_is_the_latest_across_policies_after_corrections(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        for support_id in ("standard", "extended"):
            assert create_release_support_definition(release, support_id, support_id).ok

        _event(release, "endOfSupport", **_on(datetime(2026, 6, 30, tzinfo=dt_timezone.utc)), support_id="standard")
        _event(release, "endOfSupport", **_on(datetime(2029, 6, 30, tzinfo=dt_timezone.utc)), support_id="extended")
        # A correction within one policy replaces that policy's date, even when it moves earlier.
        correction = _event(
            release, "endOfSupport", **_on(datetime(2028, 1, 31, tzinfo=dt_timezone.utc)), support_id="extended"
        )
        assert _fresh(release).end_of_support == date(2028, 1, 31)

        # A later event under another policy does not cut the longest one short.
        _event(release, "endOfSupport", **_on(datetime(2026, 12, 31, tzinfo=dt_timezone.utc)), support_id="standard")
        assert _fresh(release).end_of_support == date(2028, 1, 31)

        _withdraw_event(correction)
        assert _fresh(release).end_of_support == date(2029, 6, 30)

    def test_end_of_life_is_the_latest_surviving_event(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        _event(release, "endOfLife", **_on(datetime(2027, 1, 1, tzinfo=dt_timezone.utc)))
        later = _event(release, "endOfLife", **_on(datetime(2026, 3, 1, tzinfo=dt_timezone.utc)))
        assert _fresh(release).end_of_life == date(2026, 3, 1)

        _withdraw_event(later)
        assert _fresh(release).end_of_life == date(2027, 1, 1)


@pytest.mark.django_db
class TestSupersededAt:
    def test_only_a_drop_in_edge_retires_its_source(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.1.0")

        upgrade_path = _supersede(old, "1.1.0", drop_in=False)
        assert upgrade_path.ok and upgrade_path.value is not None
        assert upgrade_path.value.superseded_by_release_id == new.pk
        assert _fresh(old).superseded_at is None
        assert _fresh(old).is_tracked

        assert _supersede(old, "1.1.0", drop_in=True).ok
        assert _fresh(old).superseded_at == PAST
        assert _fresh(old).lifecycle_state == Release.LifecycleState.SUPERSEDED

    def test_a_successor_outside_sbomify_still_counts(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        result = _supersede(old, "2.0.0-from-elsewhere")
        assert result.ok and result.value is not None
        assert result.value.superseded_by_release_id is None
        assert not _fresh(old).is_tracked

    def test_a_withdrawn_successor_hands_its_predecessor_back(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1").ok

        assert set_release_state(new, "withdraw", reason="defective").ok
        assert _fresh(old).superseded_at is None
        assert _fresh(old).is_tracked

        assert set_release_state(new, "reactivate").ok
        assert _fresh(old).superseded_at == PAST

    def test_withdrawing_the_edge_restores_the_predecessor(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        edge = _supersede(old, "1.0.1")
        assert edge.ok and edge.value is not None

        _withdraw_event(edge.value)
        assert _fresh(old).superseded_at is None

    def test_the_earliest_drop_in_edge_wins(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        _release(sample_product, "1.1.0")
        assert _supersede(old, "1.1.0", effective=datetime(2025, 3, 1, tzinfo=dt_timezone.utc)).ok
        assert _supersede(old, "1.0.1", effective=datetime(2025, 2, 1, tzinfo=dt_timezone.utc)).ok
        assert _fresh(old).superseded_at == datetime(2025, 2, 1, tzinfo=dt_timezone.utc)


@pytest.mark.django_db
class TestTrackedPredicate:
    """``tracked_releases()`` and ``Release.lifecycle_state`` must agree on every state."""

    def test_queryset_and_properties_agree(self, sample_product: Product) -> None:
        now = timezone.now()
        today = now.date()
        Product.objects.filter(pk=sample_product.pk).update(end_of_support=today - timedelta(days=10))
        expected = {
            "latest": Release.LifecycleState.ACTIVE,
            "withdrawn": Release.LifecycleState.WITHDRAWN,
            "eol": Release.LifecycleState.END_OF_LIFE,
            "product-eos": Release.LifecycleState.END_OF_SUPPORT,
            "extended": Release.LifecycleState.ACTIVE,
            "last-day": Release.LifecycleState.ACTIVE,
            "superseded": Release.LifecycleState.SUPERSEDED,
            "superseded-later": Release.LifecycleState.ACTIVE,
            "archived": Release.LifecycleState.ARCHIVED,
            "withdrawn-and-superseded": Release.LifecycleState.WITHDRAWN,
        }
        Release.objects.create(product=sample_product, name="latest", is_latest=True)
        _release(sample_product, "withdrawn", withdrawn_at=now, withdrawn_reason="defective")
        _release(sample_product, "eol", end_of_life=today - timedelta(days=1), end_of_support=today + timedelta(days=9))
        _release(sample_product, "product-eos")
        # A release's own later date outlives the product default.
        _release(sample_product, "extended", end_of_support=today + timedelta(days=30))
        _release(sample_product, "last-day", end_of_support=today)
        _release(sample_product, "superseded", superseded_at=now - timedelta(days=1), end_of_support=today)
        _release(sample_product, "superseded-later", superseded_at=now + timedelta(days=1), end_of_support=today)
        _release(sample_product, "archived", archived_at=now, end_of_support=today)
        _release(
            sample_product,
            "withdrawn-and-superseded",
            withdrawn_at=now,
            withdrawn_reason="compromised",
            superseded_at=now - timedelta(days=1),
        )

        releases = Release.objects.filter(product=sample_product).select_related("product")
        assert {release.name: release.lifecycle_state for release in releases} == expected
        tracked = set(tracked_releases(Release.objects.filter(product=sample_product)).values_list("name", flat=True))
        assert tracked == {name for name, state in expected.items() if state == Release.LifecycleState.ACTIVE}
        assert tracked == {release.name for release in releases if release.is_tracked}

    def test_a_product_end_of_life_retires_named_releases_but_never_latest(self, sample_product: Product) -> None:
        Product.objects.filter(pk=sample_product.pk).update(end_of_life=timezone.now().date() - timedelta(days=1))
        Release.objects.create(product=sample_product, name="latest", is_latest=True)
        _release(sample_product, "1.0.0")

        assert list(tracked_releases(Release.objects.filter(product=sample_product)).values_list("name", flat=True)) == [
            "latest"
        ]


@pytest.mark.django_db
class TestEdgeValidation:
    def test_a_release_cannot_supersede_itself(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        result = _supersede(old, "1.0.0")
        assert not result.ok and "itself" in (result.error or "")

    def test_latest_is_never_superseded_and_never_a_successor(self, sample_product: Product) -> None:
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        named = _release(sample_product, "1.0.0")

        assert not _supersede(latest, "1.0.0").ok
        assert not _supersede(named, "latest").ok
        assert not ReleaseCLEEvent.objects.exists()

    def test_a_cycle_is_refused(self, sample_product: Product) -> None:
        a, b, c = (_release(sample_product, name) for name in ("1.0.0", "1.1.0", "1.2.0"))
        assert _supersede(a, "1.1.0").ok
        assert _supersede(b, "1.2.0").ok

        result = _supersede(c, "1.0.0")
        assert not result.ok and "cycle" in (result.error or "")
        assert not ReleaseCLEEvent.objects.filter(release=c).exists()

    def test_a_rollback_edge_is_refused_but_withdrawing_rolls_back(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1").ok

        result = _supersede(new, "1.0.0")
        assert not result.ok and "withdraw it instead" in (result.error or "")

        assert set_release_state(new, "withdraw", reason="defective").ok
        assert _fresh(old).is_tracked

    def test_a_withdrawn_edge_no_longer_blocks_the_reverse(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        edge = _supersede(old, "1.0.1")
        assert edge.ok and edge.value is not None
        _withdraw_event(edge.value)

        assert _supersede(new, "1.0.0").ok

    def test_successors_are_capped(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        for n in range(MAX_SUCCESSORS):
            assert _supersede(old, f"external-{n}").ok

        result = _supersede(old, "one-too-many")
        assert not result.ok and str(MAX_SUCCESSORS) in (result.error or "")
        # A retry of an edge already there is not a new one, so it still succeeds at the cap.
        assert _supersede(old, "external-0").ok

    def test_a_repeated_declaration_returns_the_existing_edge(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        first, again = _supersede(old, "1.0.1"), _supersede(old, "1.0.1")

        assert first.ok and again.ok and first.value is not None and again.value is not None
        assert first.value.pk == again.value.pk
        assert ReleaseCLEEvent.objects.filter(release=old).count() == 1

    def test_drop_in_belongs_to_supersession_only(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        result = create_release_cle_event(release, "released", PAST, drop_in=True)
        assert not result.ok and "drop_in" in (result.error or "")


@pytest.mark.django_db
class TestReleaseState:
    def test_withdraw_needs_a_reason(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        assert not set_release_state(release, "withdraw").ok
        assert _fresh(release).withdrawn_at is None

    def test_latest_cannot_be_withdrawn_or_archived(self, sample_product: Product) -> None:
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        assert not set_release_state(latest, "withdraw", reason="defective").ok
        assert not set_release_state(latest, "archive").ok

    def test_archive_then_reactivate(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        archived = set_release_state(release, "archive")
        assert archived.ok and archived.value is not None
        assert archived.value.lifecycle_state == Release.LifecycleState.ARCHIVED

        assert set_release_state(release, "reactivate").ok
        assert _fresh(release).is_tracked

    def test_each_decision_leaves_an_audit_line(
        self, sample_product: Product, caplog: pytest.LogCaptureFixture
    ) -> None:
        release = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        # The audit tree does not propagate to the root logger caplog listens on.
        audit_logger = logging.getLogger("sbomify.audit.release")
        audit_logger.addHandler(caplog.handler)
        try:
            set_release_state(release, "withdraw", reason="compromised", actor_id=7)
            create_release_cle_event(
                release, "supersededBy", PAST, superseded_by_version="1.0.1", drop_in=True, actor_id=7
            )
        finally:
            audit_logger.removeHandler(caplog.handler)

        lines = [record for record in caplog.records if record.name == "sbomify.audit.release"]
        assert [(record.action, record.actor_id) for record in lines] == [("withdraw", 7), ("supersede", 7)]
        assert lines[0].reason == "compromised"


@pytest.mark.django_db
class TestReleaseCLEEndpoint:
    def _post(self, client: Client, token: AccessToken, release: Release, payload: dict[str, object]):
        return client.post(
            f"/api/v1/releases/{release.pk}/cle/events",
            data=payload,
            content_type="application/json",
            **get_api_headers(token),
        )

    def test_drop_in_is_recorded_and_returned(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")

        response = self._post(
            client,
            token,
            old,
            {
                "event_type": "supersededBy",
                "effective": "2025-01-01T00:00:00Z",
                "superseded_by_version": "1.0.1",
                "drop_in": True,
            },
        )

        assert response.status_code == 201, response.content
        assert response.json()["drop_in"] is True
        assert response.json()["superseded_by_release_id"] == new.pk
        assert not _fresh(old).is_tracked

    def test_raw_supersession_defaults_to_upgrade_path(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")

        response = self._post(
            client,
            token,
            old,
            {"event_type": "supersededBy", "effective": "2025-01-01T00:00:00Z", "superseded_by_version": "1.0.1"},
        )

        assert response.status_code == 201, response.content
        assert response.json()["drop_in"] is False
        assert _fresh(old).is_tracked

    def test_supersession_of_latest_is_refused(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        _release(sample_product, "1.0.0")

        response = self._post(
            client,
            token,
            latest,
            {"event_type": "supersededBy", "effective": "2025-01-01T00:00:00Z", "superseded_by_version": "1.0.0"},
        )

        assert response.status_code == 400
        assert "latest" in response.json()["detail"]

    def test_a_cycle_is_refused_through_the_endpoint(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1").ok

        response = self._post(
            client,
            token,
            new,
            {"event_type": "supersededBy", "effective": "2025-01-01T00:00:00Z", "superseded_by_version": "1.0.0"},
        )

        assert response.status_code == 400
        assert "cycle" in response.json()["detail"]

    def test_drop_in_is_not_a_field_on_product_or_component_events(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        component = Component.objects.create(name="lifecycle component", team_id=sample_product.team_id)
        payload = {
            "event_type": "supersededBy",
            "effective": "2025-01-01T00:00:00Z",
            "superseded_by_version": "2.0.0",
            "drop_in": True,
        }

        for url in (
            f"/api/v1/products/{sample_product.pk}/cle/events",
            f"/api/v1/components/{component.pk}/cle/events",
        ):
            response = client.post(url, data=payload, content_type="application/json", **get_api_headers(token))
            assert response.status_code == 422, (url, response.content)


@pytest.mark.django_db
class TestDeleteGuard:
    def test_a_successor_with_surviving_edges_is_not_deleted(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        edge = _supersede(old, "1.0.1", drop_in=False)
        assert edge.ok and edge.value is not None

        response = client.delete(f"/api/v1/releases/{new.pk}", **get_api_headers(token))
        assert response.status_code == 400
        assert response.json()["detail"] == "Release 1.0.1 supersedes 1 release. Withdraw those supersessions first."
        assert Release.objects.filter(pk=new.pk).exists()

        _withdraw_event(edge.value)
        response = client.delete(f"/api/v1/releases/{new.pk}", **get_api_headers(token))
        assert response.status_code == 204, response.content


@pytest.mark.django_db
class TestBackfillMigration:
    def test_existing_edges_resolve_and_stay_upgrade_paths(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        named = Release.objects.create(product=sample_product, name="legacy")
        # Rows as they exist before the migration: written straight to the table, unresolved.
        rows = [
            (old, "supersededBy", {"superseded_by_version": "1.0.1"}),
            (new, "supersededBy", {"superseded_by_version": "legacy"}),
            (named, "supersededBy", {"superseded_by_version": "latest"}),
            (named, "supersededBy", {"superseded_by_version": "outside"}),
            (old, "endOfSupport", {"effective": datetime(2026, 6, 30, tzinfo=dt_timezone.utc), "support_id": "a"}),
            (old, "endOfSupport", {"effective": datetime(2027, 6, 30, tzinfo=dt_timezone.utc), "support_id": "b"}),
            (new, "endOfLife", {"effective": datetime(2028, 1, 1, tzinfo=dt_timezone.utc)}),
        ]
        for n, (release, event_type, fields) in enumerate(rows, start=1):
            ReleaseCLEEvent.objects.create(
                release=release, event_id=n, event_type=event_type, **{"effective": PAST, **fields}
            )

        backfill.backfill_release_lifecycle(django_apps, None)

        edges = {
            event.superseded_by_version: event for event in ReleaseCLEEvent.objects.filter(event_type="supersededBy")
        }
        assert edges["1.0.1"].superseded_by_release_id == new.pk
        assert edges["legacy"].superseded_by_release_id == named.pk
        assert edges["latest"].superseded_by_release_id is None
        assert edges["outside"].superseded_by_release_id is None
        assert not any(event.drop_in for event in edges.values())

        migrated = {r.pk: (r.superseded_at, r.end_of_support, r.end_of_life) for r in Release.objects.all()}
        assert migrated[old.pk] == (None, date(2027, 6, 30), None)
        assert migrated[new.pk] == (None, None, date(2028, 1, 1))
        assert migrated[latest.pk] == (None, None, None)

        # The frozen copy and the app's recompute must not drift.
        Release.objects.update(end_of_support=None, end_of_life=None)
        recompute_release_lifecycle(sample_product)
        assert {r.pk: (r.superseded_at, r.end_of_support, r.end_of_life) for r in Release.objects.all()} == migrated
