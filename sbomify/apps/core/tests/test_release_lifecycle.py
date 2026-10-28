"""Where a release stands: supersession edges, support dates, withdrawn and archived.

A supersession is a ReleaseSupersession row, published as the predecessor's
supersededBy CLE event. A release can have many successors and many
predecessors. Support dates still come from the CLE stream, so most of these
tests write events through the service and read the columns back.
"""

from __future__ import annotations

import importlib
import logging
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Release, ReleaseSupersession
from sbomify.apps.core.services.cle import (
    create_cle_event,
    create_release_cle_event,
    create_release_support_definition,
    create_support_definition,
    get_release_cle_document,
)
from sbomify.apps.core.services.release_lifecycle import (
    MAX_SUCCESSORS,
    recompute_release_lifecycle,
    set_release_state,
    tracked_releases,
)
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import Product, ProductCLEEvent, ReleaseCLEEvent

backfill = importlib.import_module("sbomify.apps.core.migrations.0035_backfill_release_lifecycle")

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


def _edge(event: ReleaseCLEEvent) -> ReleaseSupersession:
    return ReleaseSupersession.objects.get(cle_event=event)


def _successors(release: Release) -> set[str]:
    return set(ReleaseSupersession.objects.live().filter(from_release=release).values_list("successor_label", flat=True))


def _tracked(product: Product) -> set[str]:
    return set(tracked_releases(Release.objects.filter(product=product)).values_list("name", flat=True))


def _fresh(release: Release) -> Release:
    return Release.objects.select_related("product").get(pk=release.pk)


def _on(day: datetime) -> dict[str, object]:
    return {"versions": [{"version": "any"}], "effective": day}


EVERY_VERSION = [{"range": "vers:generic/*"}]


def _product_event(product: Product, event_type: str, day: datetime, **fields: object) -> ProductCLEEvent:
    fields.setdefault("versions", EVERY_VERSION)
    result = create_cle_event(product, event_type, day, **fields)  # type: ignore[arg-type]
    assert result.ok, result.error
    assert result.value is not None
    return result.value


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
        old, major = _release(sample_product, "1.0.0"), _release(sample_product, "2.0.0")
        patch = _release(sample_product, "1.0.1")

        new_line = _supersede(old, "2.0.0", drop_in=False)
        assert new_line.ok and new_line.value is not None
        assert _edge(new_line.value).to_release == major
        assert _fresh(old).superseded_at is None
        assert _fresh(old).is_tracked

        same_line = _supersede(old, "1.0.1", drop_in=True)
        assert same_line.ok and same_line.value is not None
        assert _edge(same_line.value).to_release == patch
        assert _fresh(old).superseded_at == PAST
        assert _fresh(old).lifecycle_state == Release.LifecycleState.SUPERSEDED

    def test_a_successor_outside_sbomify_still_counts(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        result = _supersede(old, "2.0.0-from-elsewhere")
        assert result.ok and result.value is not None
        edge = _edge(result.value)
        assert edge.to_release is None and edge.successor_label == "2.0.0-from-elsewhere"
        assert not _fresh(old).is_tracked

    def test_a_withdrawn_successor_hands_its_predecessor_back(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1").ok

        assert set_release_state(new, "withdraw", reason="defective").ok
        assert _fresh(old).superseded_at is None
        assert _fresh(old).is_tracked

        assert set_release_state(new, "reactivate").ok
        assert _fresh(old).superseded_at == PAST

    def test_withdrawing_a_middle_release_keeps_the_line_moved_on(self, sample_product: Product) -> None:
        # 1.0 -> 1.1 -> 1.2 on one line. Pulling 1.1 is not a rollback to 1.0: 1.2 still carries the line.
        releases = {name: _release(sample_product, name) for name in ("1.0", "1.1", "1.2")}
        assert _supersede(releases["1.0"], "1.1").ok
        assert _supersede(releases["1.1"], "1.2").ok

        assert set_release_state(releases["1.1"], "withdraw", reason="defective").ok

        assert _fresh(releases["1.0"]).lifecycle_state == Release.LifecycleState.SUPERSEDED
        assert _tracked(sample_product) == {"1.2"}

    def test_withdrawing_the_head_brings_back_only_the_release_before_it(self, sample_product: Product) -> None:
        releases = {name: _release(sample_product, name) for name in ("1.0", "1.1", "1.2")}
        assert _supersede(releases["1.0"], "1.1").ok
        assert _supersede(releases["1.1"], "1.2").ok

        assert set_release_state(releases["1.2"], "withdraw", reason="defective").ok
        assert _tracked(sample_product) == {"1.1"}

        # With 1.1 pulled as well, nothing carries the line on, so it rolls back to 1.0.
        assert set_release_state(releases["1.1"], "withdraw", reason="defective").ok
        assert _tracked(sample_product) == {"1.0"}

    def test_withdrawing_the_edge_restores_the_predecessor(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        edge = _supersede(old, "1.0.1")
        assert edge.ok and edge.value is not None

        _withdraw_event(edge.value)
        assert _edge(edge.value).withdrawn_at is not None
        assert _fresh(old).superseded_at is None

    def test_the_earliest_drop_in_edge_wins(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        _release(sample_product, "1.1.0")
        assert _supersede(old, "1.1.0", effective=datetime(2025, 3, 1, tzinfo=dt_timezone.utc)).ok
        assert _supersede(old, "1.0.1", effective=datetime(2025, 2, 1, tzinfo=dt_timezone.utc)).ok
        assert _fresh(old).superseded_at == datetime(2025, 2, 1, tzinfo=dt_timezone.utc)


@pytest.mark.django_db
class TestOneToMany:
    """A release can have several successors and several predecessors."""

    def test_two_maintained_lines(self, sample_product: Product) -> None:
        # 1.0 to 1.2.1 each replaced by the next; 2.0 starts a new line from 1.2.1, and the
        # 1.2 series carries on later with 1.2.2. Both lines stay monitored until 1.2.2 replaces 1.2.1.
        releases = {name: _release(sample_product, name) for name in ("1.0", "1.1", "1.2", "1.2.1", "2.0")}
        for old, new in (("1.0", "1.1"), ("1.1", "1.2"), ("1.2", "1.2.1")):
            assert _supersede(releases[old], new).ok
        assert _supersede(releases["1.2.1"], "2.0", drop_in=False).ok

        assert _tracked(sample_product) == {"1.2.1", "2.0"}

        releases["1.2.2"] = _release(sample_product, "1.2.2")
        assert _supersede(releases["1.2.1"], "1.2.2").ok

        assert _tracked(sample_product) == {"1.2.2", "2.0"}
        assert _successors(releases["1.2.1"]) == {"2.0", "1.2.2"}
        assert {edge.from_release.name for edge in releases["2.0"].predecessor_edges.all()} == {"1.2.1"}

    def test_one_release_replaced_by_two(self, sample_product: Product) -> None:
        old = _release(sample_product, "12.0")
        _release(sample_product, "12.0.1")
        _release(sample_product, "12.1")
        first, second = _supersede(old, "12.0.1"), _supersede(old, "12.1")
        assert first.ok and second.ok and first.value is not None and second.value is not None

        assert _tracked(sample_product) == {"12.0.1", "12.1"}

        # Withdrawing one of two drop-in edges leaves the other retiring it.
        _withdraw_event(first.value)
        assert _successors(old) == {"12.1"}
        assert not _fresh(old).is_tracked

        _withdraw_event(second.value)
        assert _fresh(old).is_tracked

    def test_two_releases_replaced_by_one(self, sample_product: Product) -> None:
        a, b = _release(sample_product, "1.4"), _release(sample_product, "1.5")
        merged = _release(sample_product, "2.0")
        assert _supersede(a, "2.0").ok
        assert _supersede(b, "2.0").ok

        assert {edge.from_release.name for edge in merged.predecessor_edges.all()} == {"1.4", "1.5"}
        assert _tracked(sample_product) == {"2.0"}

    def test_each_edge_is_published_as_its_own_cle_event(self, sample_product: Product) -> None:
        old = _release(sample_product, "12.0")
        _release(sample_product, "12.0.1")
        assert _supersede(old, "12.0.1").ok
        assert _supersede(old, "13.0-elsewhere", drop_in=False).ok

        document = get_release_cle_document(old)

        assert document.ok and document.value is not None
        published = {event.superseded_by_version for event in document.value.events if event.superseded_by_version}
        assert published == {"12.0.1", "13.0-elsewhere"}

    def test_the_database_refuses_a_self_edge_and_a_second_live_edge_to_one_successor(
        self, sample_product: Product
    ) -> None:
        old, new = _release(sample_product, "1.0"), _release(sample_product, "1.1")
        with pytest.raises(IntegrityError), transaction.atomic():
            ReleaseSupersession.objects.create(from_release=old, to_release=old, successor_label="1.0", effective=PAST)

        ReleaseSupersession.objects.create(from_release=old, to_release=new, successor_label="1.1", effective=PAST)
        with pytest.raises(IntegrityError), transaction.atomic():
            ReleaseSupersession.objects.create(from_release=old, to_release=new, successor_label="1.1", effective=PAST)

        ReleaseSupersession.objects.filter(from_release=old).update(withdrawn_at=PAST)
        ReleaseSupersession.objects.create(from_release=old, to_release=new, successor_label="1.1", effective=PAST)


@pytest.mark.django_db
class TestTrackedPredicate:
    """``tracked_releases()`` and ``Release.lifecycle_state`` must agree on every state."""

    def test_queryset_and_properties_agree(self, sample_product: Product) -> None:
        now = timezone.now()
        today = now.date()
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
        _release(
            sample_product,
            "eol",
            effective_end_of_life=today - timedelta(days=1),
            effective_end_of_support=today + timedelta(days=9),
        )
        _release(sample_product, "product-eos", effective_end_of_support=today - timedelta(days=10))
        _release(sample_product, "extended", effective_end_of_support=today + timedelta(days=30))
        _release(sample_product, "last-day", effective_end_of_support=today)
        _release(sample_product, "superseded", superseded_at=now - timedelta(days=1), effective_end_of_support=today)
        _release(
            sample_product, "superseded-later", superseded_at=now + timedelta(days=1), effective_end_of_support=today
        )
        _release(sample_product, "archived", archived_at=now, effective_end_of_support=today)
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
        Release.objects.create(product=sample_product, name="latest", is_latest=True)
        _release(sample_product, "1.0.0")
        _product_event(sample_product, "endOfLife", timezone.now() - timedelta(days=2))

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
        assert not ReleaseSupersession.objects.exists()

    def test_a_cycle_is_refused(self, sample_product: Product) -> None:
        a, b, c = (_release(sample_product, name) for name in ("1.0.0", "1.1.0", "1.2.0"))
        assert _supersede(a, "1.1.0").ok
        assert _supersede(b, "1.2.0").ok

        result = _supersede(c, "1.0.0")
        assert not result.ok and "cycle" in (result.error or "")
        assert not ReleaseCLEEvent.objects.filter(release=c).exists()
        assert not ReleaseSupersession.objects.filter(from_release=c).exists()

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

        # The reverse edge records an upgrade path: 1.0.0 came out first, so it cannot replace 1.0.1 on its line.
        assert _supersede(new, "1.0.0", drop_in=False).ok

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
        assert again.status_code == 200
        assert ReleaseCLEEvent.objects.filter(release=old).count() == 1
        assert ReleaseSupersession.objects.filter(from_release=old).count() == 1

    def test_restating_a_live_edge_with_the_other_line_is_refused(self, sample_product: Product) -> None:
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1", drop_in=True).ok

        result = _supersede(old, "1.0.1", drop_in=False)

        assert not result.ok and result.status_code == 409
        assert "remove" in (result.error or "").lower()
        assert ReleaseSupersession.objects.filter(from_release=old).count() == 1

    def test_a_retry_with_another_date_is_the_same_edge(self, sample_product: Product) -> None:
        # A pipeline re-run, or a release date corrected in the UI, must not fail a build that changed nothing.
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        first = _supersede(old, "1.0.1")
        again = _supersede(old, "1.0.1", effective=datetime(2025, 2, 1, tzinfo=dt_timezone.utc))

        assert first.ok and again.ok and first.value is not None and again.value is not None
        assert again.status_code == 200 and again.value.pk == first.value.pk
        assert ReleaseSupersession.objects.filter(from_release=old).count() == 1

    def test_drop_in_belongs_to_supersession_only(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        result = create_release_cle_event(release, "released", PAST, drop_in=True)
        assert not result.ok and "drop_in" in (result.error or "")



@pytest.mark.django_db
class TestPendingEdges:
    """An edge declared before its successor existed links once a release carries the name it gave."""

    def _create(self, client: Client, token: AccessToken, product: Product, version: str):
        return client.post(
            "/api/v1/releases",
            data={"product_id": product.pk, "name": version, "version": version},
            content_type="application/json",
            **get_api_headers(token),
        )

    def _patch(self, client: Client, token: AccessToken, release: Release, payload: dict[str, object]):
        return client.patch(
            f"/api/v1/releases/{release.pk}", data=payload, content_type="application/json", **get_api_headers(token)
        )

    def test_creating_the_successor_links_the_edge_so_the_cycle_check_sees_it(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old = _release(sample_product, "1.0")
        edge = _supersede(old, "2.0")
        assert edge.ok and edge.value is not None and _edge(edge.value).to_release is None

        response = self._create(client, token, sample_product, "2.0")

        assert response.status_code == 201, response.content
        new = Release.objects.get(pk=response.json()["id"])
        assert _edge(edge.value).to_release == new
        back = _supersede(new, "1.0")
        assert not back.ok and "cycle" in (back.error or "")

    def test_a_new_version_links_the_edges_that_name_it(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old, other = _release(sample_product, "1.0"), _release(sample_product, "1.9")
        edge = _supersede(old, "2.0")
        assert edge.ok and edge.value is not None

        response = self._patch(client, token, other, {"version": "2.0"})

        assert response.status_code == 200, response.content
        assert _edge(edge.value).to_release == other

    def test_a_rename_that_would_close_a_cycle_is_refused(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old, other = _release(sample_product, "1.0"), _release(sample_product, "2.1")
        assert _supersede(old, "2.0").ok
        # A new-line edge still counts for the cycle check; same line would need 1.0 released after 2.1.
        assert _supersede(other, "1.0", drop_in=False).ok

        response = self._patch(client, token, other, {"version": "2.0"})

        assert response.status_code == 400, response.content
        assert "cycle" in response.json()["detail"]
        assert _fresh(other).version == "2.1"


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
        self, sample_product: Product, caplog: pytest.LogCaptureFixture, django_capture_on_commit_callbacks
    ) -> None:
        release = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        # The audit tree does not propagate to the root logger caplog listens on.
        audit_logger = logging.getLogger("sbomify.audit.release")
        audit_logger.addHandler(caplog.handler)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                set_release_state(release, "withdraw", reason="compromised", actor_id=7)
                create_release_cle_event(
                    release, "supersededBy", PAST, superseded_by_version="1.0.1", drop_in=True, actor_id=7
                )
        finally:
            audit_logger.removeHandler(caplog.handler)

        lines = [record for record in caplog.records if record.name == "sbomify.audit.release"]
        assert [(record.action, record.actor_id) for record in lines] == [("withdraw", 7), ("supersede", 7)]
        assert lines[0].reason == "compromised"

    def test_a_rolled_back_decision_leaves_no_audit_line(
        self, sample_product: Product, caplog: pytest.LogCaptureFixture, django_capture_on_commit_callbacks
    ) -> None:
        release = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        audit_logger = logging.getLogger("sbomify.audit.release")
        audit_logger.addHandler(caplog.handler)
        try:
            with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
                create_release_cle_event(release, "supersededBy", PAST, superseded_by_version="1.0.1", drop_in=True)
                transaction.set_rollback(True)
        finally:
            audit_logger.removeHandler(caplog.handler)

        assert not [record for record in caplog.records if record.name == "sbomify.audit.release"]


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
        assert response.json()["superseded_by_version"] == "1.0.1"
        edge = ReleaseSupersession.objects.get(from_release=old)
        assert edge.drop_in is True and edge.to_release == new
        assert edge.cle_event is not None and edge.cle_event.event_id == response.json()["event_id"]
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
        assert ReleaseSupersession.objects.get(from_release=old).drop_in is False
        assert _fresh(old).is_tracked

    def test_a_retry_returns_the_existing_edge_with_200_and_the_other_line_is_a_conflict(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        payload = {"event_type": "supersededBy", "effective": "2025-01-01T00:00:00Z", "superseded_by_version": "1.0.1"}

        first = self._post(client, token, old, payload)
        retry = self._post(client, token, old, payload)
        later = self._post(client, token, old, {**payload, "effective": "2025-02-01T00:00:00Z"})
        other_line = self._post(client, token, old, {**payload, "drop_in": True})

        assert first.status_code == 201, first.content
        assert retry.status_code == 200, retry.content
        assert retry.json()["event_id"] == first.json()["event_id"]
        assert later.status_code == 200, later.content
        assert later.json()["event_id"] == first.json()["event_id"]
        assert other_line.status_code == 409, other_line.content
        assert ReleaseCLEEvent.objects.filter(release=old).count() == 1
        assert ReleaseSupersession.objects.filter(from_release=old).count() == 1

    def test_a_withdrawn_event_withdraws_its_edge(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old = _release(sample_product, "1.0.0")
        _release(sample_product, "1.0.1")
        edge = _supersede(old, "1.0.1")
        assert edge.ok and edge.value is not None

        response = self._post(
            client,
            token,
            old,
            {"event_type": "withdrawn", "effective": "2025-03-01T00:00:00Z", "withdrawn_event_id": edge.value.event_id},
        )

        assert response.status_code == 201, response.content
        assert _edge(edge.value).withdrawn_at is not None
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
        edge = _supersede(old, "1.0.1", drop_in=True)
        assert edge.ok and edge.value is not None

        response = client.delete(f"/api/v1/releases/{new.pk}", **get_api_headers(token))
        assert response.status_code == 400
        assert response.json()["detail"] == "Release 1.0.1 replaces 1.0.0. Remove that link on its Lifecycle card first."
        assert Release.objects.filter(pk=new.pk).exists()

        _withdraw_event(edge.value)
        response = client.delete(f"/api/v1/releases/{new.pk}", **get_api_headers(token))
        assert response.status_code == 204, response.content


    def test_an_upgrade_path_edge_does_not_block_deleting_its_successor(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        # It retires nothing, so deleting the successor changes nothing the edge decides.
        client, token = authenticated_api_client
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        assert _supersede(old, "1.0.1", drop_in=False).ok

        response = client.delete(f"/api/v1/releases/{new.pk}", **get_api_headers(token))

        assert response.status_code == 204, response.content
        assert _fresh(old).is_tracked
        # The edge outlives its successor and still says what the successor was.
        edge = ReleaseSupersession.objects.get(from_release=old)
        assert edge.to_release is None and edge.successor_label == "1.0.1"


@pytest.mark.django_db
class TestBackfillMigration:
    def test_existing_supersededby_events_become_upgrade_path_edges(self, sample_product: Product) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        named = Release.objects.create(product=sample_product, name="legacy")
        # Rows as they exist before the migration: written straight to the table, with no edges.
        rows = [
            (old, "supersededBy", {"superseded_by_version": "1.0.1"}),
            (old, "supersededBy", {"superseded_by_version": "2.0-elsewhere"}),
            (old, "supersededBy", {"superseded_by_version": "1.0.1"}),
            (new, "supersededBy", {"superseded_by_version": "legacy"}),
            (named, "supersededBy", {"superseded_by_version": "latest"}),
            (named, "supersededBy", {"superseded_by_version": "voided"}),
            (named, "withdrawn", {"withdrawn_event_id": 6}),
            (latest, "supersededBy", {"superseded_by_version": "1.0.0"}),
            (old, "endOfSupport", {"effective": datetime(2026, 6, 30, tzinfo=dt_timezone.utc), "support_id": "a"}),
            (old, "endOfSupport", {"effective": datetime(2027, 6, 30, tzinfo=dt_timezone.utc), "support_id": "b"}),
            (new, "endOfLife", {"effective": datetime(2028, 1, 1, tzinfo=dt_timezone.utc)}),
        ]
        for n, (release, event_type, fields) in enumerate(rows, start=1):
            ReleaseCLEEvent.objects.create(
                release=release, event_id=n, event_type=event_type, **{"effective": PAST, **fields}
            )
        product_rows = [
            ("endOfLife", datetime(2030, 1, 1, tzinfo=dt_timezone.utc), EVERY_VERSION),
            ("endOfSupport", datetime(2020, 1, 1, tzinfo=dt_timezone.utc), [{"range": "vers:semver/<1.0.0"}]),
        ]
        for n, (event_type, effective, versions) in enumerate(product_rows, start=1):
            ProductCLEEvent.objects.create(
                product=sample_product, event_id=n, event_type=event_type, effective=effective, versions=versions
            )

        backfill.backfill_release_lifecycle(django_apps, None)

        edges = {
            (edge.from_release.name, edge.successor_label): edge
            for edge in ReleaseSupersession.objects.select_related("from_release", "cle_event")
        }
        # One live edge per successor: the repeated 1.0.1 event adds none.
        assert set(edges) == {
            ("1.0.0", "1.0.1"),
            ("1.0.0", "2.0-elsewhere"),
            ("1.0.1", "legacy"),
            ("legacy", "latest"),
        }
        assert edges[("1.0.0", "1.0.1")].to_release == new
        assert edges[("1.0.0", "1.0.1")].cle_event.event_id == 1
        assert edges[("1.0.1", "legacy")].to_release == named
        # A successor outside sbomify, or one the live service refuses, keeps its label only.
        assert edges[("1.0.0", "2.0-elsewhere")].to_release is None
        assert edges[("legacy", "latest")].to_release is None
        assert not any(edge.drop_in or edge.withdrawn_at for edge in edges.values())

        def derived() -> dict[str, tuple[object, ...]]:
            return {
                r.pk: (r.superseded_at, r.end_of_support, r.end_of_life, r.effective_end_of_support, r.effective_end_of_life)
                for r in Release.objects.all()
            }

        migrated = derived()
        assert migrated[old.pk] == (None, date(2027, 6, 30), None, date(2027, 6, 30), date(2030, 1, 1))
        assert migrated[new.pk] == (None, None, date(2028, 1, 1), None, date(2028, 1, 1))
        # A product date for some versions only is never inherited.
        assert migrated[named.pk] == (None, None, None, None, date(2030, 1, 1))
        assert migrated[latest.pk] == (None, None, None, None, date(2030, 1, 1))

        # The frozen copy and the app's recompute must not drift.
        Release.objects.update(end_of_support=None, end_of_life=None, effective_end_of_support=None, effective_end_of_life=None)
        recompute_release_lifecycle(sample_product)
        assert derived() == migrated


@pytest.mark.django_db
class TestProductDateInheritance:
    """A release with no date of its own takes the product's, but only a date that covers every version."""

    def test_a_product_date_for_every_version_is_inherited(self, sample_product: Product) -> None:
        plain = _release(sample_product, "1.0.0")
        extended = _release(sample_product, "1.1.0")
        assert create_release_support_definition(extended, "extended", "Extended").ok
        _event(extended, "endOfSupport", **_on(timezone.now() + timedelta(days=60)), support_id="extended")

        _product_event(sample_product, "endOfSupport", timezone.now() - timedelta(days=5))

        assert _fresh(plain).effective_end_of_support == (timezone.now() - timedelta(days=5)).date()
        assert _fresh(plain).lifecycle_state == Release.LifecycleState.END_OF_SUPPORT
        # A release's own date wins, so extended support outlives the product default.
        assert _fresh(extended).is_tracked
        assert _tracked(sample_product) == {"1.1.0"}

    def test_a_product_date_for_some_versions_is_never_inherited(self, sample_product: Product) -> None:
        # sbomify has no version parser, by design, so it cannot tell which releases a range covers.
        release = _release(sample_product, "2.0.0")

        _product_event(
            sample_product, "endOfSupport", timezone.now() - timedelta(days=5), versions=[{"range": "vers:semver/<2.0.0"}]
        )

        assert _fresh(release).effective_end_of_support is None
        assert _fresh(release).is_tracked

    @pytest.mark.parametrize("order", [("extended", "standard"), ("standard", "extended")])
    def test_product_support_policies_fold_the_same_whatever_the_order(
        self, sample_product: Product, order: tuple[str, str]
    ) -> None:
        release = _release(sample_product, "1.0.0")
        days = {"standard": datetime(2026, 6, 30, tzinfo=dt_timezone.utc), "extended": datetime(2027, 6, 30, tzinfo=dt_timezone.utc)}
        for support_id in order:
            assert create_support_definition(sample_product, support_id, support_id).ok
        for support_id in order:
            _product_event(sample_product, "endOfSupport", days[support_id], support_id=support_id)

        assert _fresh(release).effective_end_of_support == date(2027, 6, 30)

    def test_product_columns_alone_retire_nothing(self, sample_product: Product) -> None:
        # Monitoring follows the published lifecycle events, not a column another writer can set.
        release = _release(sample_product, "1.0.0")
        Product.objects.filter(pk=sample_product.pk).update(end_of_support=date(2020, 1, 1))
        recompute_release_lifecycle(sample_product)

        assert _fresh(release).is_tracked

    def test_withdrawing_the_product_event_brings_the_release_back(self, sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        event = _product_event(sample_product, "endOfLife", timezone.now() - timedelta(days=5))
        assert not _fresh(release).is_tracked

        _product_event(sample_product, "withdrawn", PAST, versions=[], withdrawn_event_id=event.event_id)

        assert _fresh(release).effective_end_of_life is None
        assert _fresh(release).is_tracked


@pytest.mark.django_db
class TestReleaseEdits:
    """Editing a release writes only what changed, under the lock order every lifecycle writer uses."""

    def _send(self, client: Client, token: AccessToken, method: str, release: Release, payload: dict[str, object]):
        return getattr(client, method)(
            f"/api/v1/releases/{release.pk}", data=payload, content_type="application/json", **get_api_headers(token)
        )

    @pytest.mark.parametrize("method", ["patch", "put"])
    def test_an_edit_does_not_put_back_a_withdrawal_made_after_it_read_the_release(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
        mocker,
        method: str,
    ) -> None:
        client, token = authenticated_api_client
        release = _release(sample_product, "1.0.0")
        real_can = __import__("sbomify.apps.core.apis", fromlist=["can"]).can

        withdrawn: list[bool] = []

        def withdraw_meanwhile(*args, **kwargs):
            # Another member withdraws the release between this request's read and its write.
            if not withdrawn:
                Release.objects.filter(pk=release.pk).update(withdrawn_at=timezone.now(), withdrawn_reason="compromised")
                withdrawn.append(True)
            return real_can(*args, **kwargs)

        mocker.patch("sbomify.apps.core.apis.can", side_effect=withdraw_meanwhile)
        payload: dict[str, object] = {"description": "Notes"}
        if method == "put":
            payload.update({"name": "1.0.0", "version": "1.0.0", "is_prerelease": False})

        response = self._send(client, token, method, release, payload)

        assert response.status_code == 200, response.content
        edited = _fresh(release)
        assert edited.description == "Notes"
        assert edited.withdrawn_at is not None and edited.withdrawn_reason == "compromised"

    def test_an_edit_locks_the_product_before_the_release(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        client, token = authenticated_api_client
        release = _release(sample_product, "1.0.0")

        with CaptureQueriesContext(connection) as queries:
            response = self._send(client, token, "patch", release, {"description": "Notes"})

        assert response.status_code == 200, response.content
        locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
        product_table, release_table = Product._meta.db_table, Release._meta.db_table
        firsts = [next(i for i, sql in enumerate(locks) if f'FROM "{table}"' in sql) for table in (product_table, release_table)]
        assert firsts[0] < firsts[1], locks

    def test_moving_the_release_date_moves_the_edges_that_took_their_date_from_it(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        first_date = datetime(2025, 3, 1, 12, 0, tzinfo=dt_timezone.utc)
        old = _release(sample_product, "1.9", created_at=PAST, released_at=PAST)
        other = _release(sample_product, "1.8", created_at=PAST, released_at=PAST)
        new = _release(sample_product, "2.0", created_at=PAST, released_at=first_date)
        took_its_date = _supersede(old, "2.0", effective=first_date)
        own_date = _supersede(other, "2.0", effective=PAST)
        assert took_its_date.ok and own_date.ok and took_its_date.value and own_date.value

        corrected = datetime(2025, 4, 1, 9, 30, tzinfo=dt_timezone.utc)
        response = self._send(client, token, "patch", new, {"released_at": corrected.isoformat()})

        assert response.status_code == 200, response.content
        assert _edge(took_its_date.value).effective == corrected
        assert _fresh(old).superseded_at == corrected
        assert _edge(own_date.value).effective == PAST


@pytest.mark.django_db
class TestBackfillReruns:
    def test_the_backfill_can_be_reversed_and_applied_again(self, sample_product: Product) -> None:
        old, _new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        ReleaseCLEEvent.objects.create(
            release=old, event_id=1, event_type="supersededBy", effective=PAST, superseded_by_version="1.0.1"
        )
        ProductCLEEvent.objects.create(
            product=sample_product,
            event_id=1,
            event_type="endOfLife",
            effective=datetime(2027, 1, 1, tzinfo=dt_timezone.utc),
            versions=EVERY_VERSION,
        )

        backfill.backfill_release_lifecycle(django_apps, None)
        backfill.backfill_release_lifecycle(django_apps, None)
        assert ReleaseSupersession.objects.count() == 1
        assert _fresh(old).effective_end_of_life == date(2027, 1, 1)

        backfill.reverse_backfill_release_lifecycle(django_apps, None)
        assert not ReleaseSupersession.objects.exists()
        assert _fresh(old).effective_end_of_life is None

        backfill.backfill_release_lifecycle(django_apps, None)
        assert ReleaseSupersession.objects.count() == 1
        assert _fresh(old).effective_end_of_life == date(2027, 1, 1)
