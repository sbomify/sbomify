"""Per-product statuses after creation.

``create_advisory`` writes every row as ``in_triage`` and, until these write
paths existed, nothing could change one afterwards. The trust center's "Am I
affected?" table and the CSAF export read the rows, not the advisory's
``remediation_status``, so a resolved advisory went on saying "Under
investigation" for every product.

The rows stay the record and the advisory is checked against them: nothing
here pushes the advisory's status down onto them.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core import authz
from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProductStatus,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import (
    add_advisory_product,
    create_advisory,
    get_advisory,
    post_update,
    update_advisory,
    update_product_status,
    update_product_statuses,
)

from .conftest import publish

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(sample_team_with_owner_member):
    return sample_team_with_owner_member.user


def _public_product(team, name: str) -> Product:
    """A product the trust center lists: public, with a public component."""
    product = Product.objects.create(name=name, team=team, is_public=True)
    component = Component.objects.create(name=f"{name} core", team=team, visibility=Component.Visibility.PUBLIC)
    product.components.add(component)
    return product


@pytest.fixture
def action(team):
    return _public_product(team, "sbomify Action")


@pytest.fixture
def app(team):
    return _public_product(team, "sbomify")


@pytest.fixture
def affected(action):
    return Release.objects.create(product=action, name="v26.9.0", version="v26.9.0")


@pytest.fixture
def fixed(action):
    return Release.objects.create(product=action, name="v26.10.1", version="v26.10.1")


@pytest.fixture
def drafted(team, user, action, app, affected) -> SecurityAdvisory:
    """The shape create_advisory leaves: every product under investigation."""
    result = create_advisory(
        team,
        user,
        title="Token leak in the action",
        identifier="CVE-2026-0003",
        remediation_status="fix_in_progress",
        products=[action, app],
        affected_releases=[affected],
    )
    assert result.ok, result.error
    return SecurityAdvisory.objects.get(pk=result.value)


def _latest(product: Product) -> Release:
    """The floating release, which a product with components already carries."""
    return Release.objects.filter(product=product, is_latest=True).first() or Release.objects.create(
        product=product, name="latest", is_latest=True
    )


def _row(advisory: SecurityAdvisory, product: Product) -> AdvisoryProductStatus:
    return AdvisoryProductStatus.objects.get(vulnerability__advisory=advisory, advisory_product__product=product)


class TestUpdatingOneRow:
    def test_a_fixed_release_becomes_its_own_range_and_the_recommendation(self, team, user, drafted, action, fixed):
        row = _row(drafted, action)

        result = update_product_status(
            team,
            user,
            drafted.id,
            row.id,
            changes={"status": "resolved", "fixed_release_id": fixed.id, "action_statement": "Upgrade to v26.10.1"},
        )

        assert result.ok, result.error
        row.refresh_from_db()
        assert row.status == "resolved"
        assert row.recommended_release == fixed
        assert row.recommended_version == "v26.10.1"
        assert row.action_statement == "Upgrade to v26.10.1"
        ranges = list(row.version_ranges.order_by("created_at"))
        # The affected pin is untouched: a range carries fixed or
        # last_affected, never both, so the fix is a second range.
        assert [(r.last_affected, r.fixed) for r in ranges] == [("v26.9.0", ""), ("", "v26.10.1")]
        assert ranges[1].fixed_release == fixed
        assert row.names_fix

    def test_a_second_fix_replaces_the_first_rather_than_stacking(self, team, user, drafted, action, fixed):
        row = _row(drafted, action)
        update_product_status(team, user, drafted.id, row.id, changes={"fixed_version": "v26.10.0"})

        assert update_product_status(team, user, drafted.id, row.id, changes={"fixed_release_id": fixed.id}).ok

        row.refresh_from_db()
        assert list(row.version_ranges.exclude(fixed="").values_list("fixed", flat=True)) == ["v26.10.1"]
        # It followed the fix, because nobody had recommended anything else.
        assert row.recommended_version == "v26.10.1"

    def test_clearing_the_fix_removes_its_range_and_the_recommendation_it_set(self, team, user, drafted, action, fixed):
        row = _row(drafted, action)
        update_product_status(team, user, drafted.id, row.id, changes={"fixed_release_id": fixed.id})

        assert update_product_status(
            team, user, drafted.id, row.id, changes={"fixed_version": "", "fixed_release_id": None}
        ).ok

        row.refresh_from_db()
        assert not row.version_ranges.exclude(fixed="").exists()
        assert row.version_ranges.count() == 1
        assert (row.recommended_version, row.recommended_release) == ("", None)

    def test_an_explicit_recommendation_is_not_overwritten_by_the_fix(self, team, user, drafted, action, fixed):
        row = _row(drafted, action)

        update_product_status(
            team,
            user,
            drafted.id,
            row.id,
            changes={"fixed_version": "v26.10.0", "recommended_release_id": fixed.id},
        )

        row.refresh_from_db()
        assert row.recommended_version == "v26.10.1"
        assert row.version_ranges.exclude(fixed="").get().fixed == "v26.10.0"

    def test_the_database_refuses_a_range_carrying_both_endpoints(self, team, user, drafted, action):
        """What the service steers around, held where nothing can step past it."""
        pin = _row(drafted, action).version_ranges.get()

        with pytest.raises(IntegrityError), transaction.atomic():
            AdvisoryVersionRange.objects.filter(pk=pin.pk).update(fixed="v26.10.1")

    @pytest.mark.parametrize("field", ["fixed_release_id", "recommended_release_id"])
    def test_the_floating_latest_release_is_refused(self, team, user, drafted, action, field):
        latest = _latest(action)
        row = _row(drafted, action)

        result = update_product_status(team, user, drafted.id, row.id, changes={field: latest.id})

        assert not result.ok
        assert "latest" in (result.error or "")
        row.refresh_from_db()
        assert (row.recommended_version, row.version_ranges.count()) == ("", 1)

    def test_a_release_of_another_product_is_refused(self, team, user, drafted, app, fixed):
        row = _row(drafted, app)

        result = update_product_status(team, user, drafted.id, row.id, changes={"fixed_release_id": fixed.id})

        assert not result.ok
        assert "different product" in (result.error or "")
        assert not row.version_ranges.exists()

    def test_a_release_of_another_workspace_is_not_found(self, team, user, drafted, action, other_team):
        theirs = Release.objects.create(product=Product.objects.create(name="Theirs", team=other_team), name="v1")
        row = _row(drafted, action)

        result = update_product_status(team, user, drafted.id, row.id, changes={"fixed_release_id": theirs.id})

        assert result.status_code == 404

    def test_an_unknown_field_is_refused_not_ignored(self, team, user, drafted, action):
        row = _row(drafted, action)

        result = update_product_status(team, user, drafted.id, row.id, changes={"stauts": "resolved"})

        assert not result.ok
        assert "stauts" in (result.error or "")

    def test_moving_off_not_affected_drops_its_justification(self, team, user, drafted, app):
        row = _row(drafted, app)
        update_product_status(
            team, user, drafted.id, row.id, changes={"status": "not_affected", "justification": "code_not_present"}
        )

        assert update_product_status(team, user, drafted.id, row.id, changes={"status": "exploitable"}).ok

        row.refresh_from_db()
        assert (row.status, row.justification) == ("exploitable", "")

    def test_a_justification_on_another_status_is_refused(self, team, user, drafted, app):
        row = _row(drafted, app)

        result = update_product_status(
            team, user, drafted.id, row.id, changes={"status": "exploitable", "justification": "code_not_present"}
        )

        assert not result.ok
        row.refresh_from_db()
        assert row.status == "in_triage"

    def test_each_changed_field_is_an_internal_timeline_entry_in_words(self, team, user, drafted, action, fixed):
        row = _row(drafted, action)

        update_product_status(
            team, user, drafted.id, row.id, changes={"status": "resolved", "fixed_release_id": fixed.id}
        )

        events = AdvisoryEvent.objects.filter(advisory=drafted, event_type=AdvisoryEvent.EventType.FIELD_CHANGE)
        bodies = sorted(e.body for e in events)
        assert "sbomify Action: Status changed from “Under investigation” to “Fixed”." in bodies
        assert "sbomify Action: Fixed in set to “v26.10.1”." in bodies
        assert all(e.payload["status_id"] == row.id for e in events)
        # Internal: field changes never reach the trust center's timeline.
        assert AdvisoryEvent.EventType.FIELD_CHANGE not in AdvisoryEvent.PUBLIC_EVENT_TYPES

    def test_an_edit_that_changes_nothing_records_nothing(self, team, user, drafted, action):
        row = _row(drafted, action)

        assert update_product_status(team, user, drafted.id, row.id, changes={"status": "in_triage"}).ok

        assert not AdvisoryEvent.objects.filter(advisory=drafted, event_type="field_change").exists()

    def test_a_row_from_another_advisory_is_not_found(self, team, user, drafted, action):
        other = create_advisory(team, user, title="Other", products=[action]).value
        foreign = _row(SecurityAdvisory.objects.get(pk=other), action)

        assert (
            update_product_status(team, user, drafted.id, foreign.id, changes={"status": "exploitable"}).status_code
            == 404
        )


class TestTheAdvisoryIsCheckedAgainstItsRows:
    def test_resolving_with_open_rows_is_refused_and_names_them(self, team, user, drafted):
        result = post_update(team, user, drafted.id, kind="resolved")

        assert result.status_code == 400
        assert "sbomify Action is Under investigation" in (result.error or "")
        assert "sbomify is Under investigation" in (result.error or "")
        drafted.refresh_from_db()
        assert drafted.remediation_status == "fix_in_progress"

    def test_an_affected_row_blocks_it_too(self, team, user, drafted, action, app):
        update_product_status(team, user, drafted.id, _row(drafted, app).id, changes={"status": "not_affected"})
        update_product_status(team, user, drafted.id, _row(drafted, action).id, changes={"status": "exploitable"})

        result = post_update(team, user, drafted.id, kind="resolved")

        assert not result.ok
        assert "sbomify Action is Affected" in (result.error or "")

    def test_resolving_succeeds_once_every_row_is_decided(self, team, user, drafted, action, app, fixed):
        update_product_status(
            team,
            user,
            drafted.id,
            _row(drafted, action).id,
            changes={"status": "resolved", "fixed_release_id": fixed.id},
        )
        update_product_status(team, user, drafted.id, _row(drafted, app).id, changes={"status": "not_affected"})

        assert post_update(team, user, drafted.id, kind="resolved").ok
        # Nothing was pushed down: the rows are exactly as they were set.
        assert _row(drafted, app).status == "not_affected"

    def test_a_resolved_advisory_refuses_reopening_a_row(self, team, user, drafted, action, app, fixed):
        update_product_status(
            team,
            user,
            drafted.id,
            _row(drafted, action).id,
            changes={"status": "resolved", "fixed_release_id": fixed.id},
        )
        update_product_status(team, user, drafted.id, _row(drafted, app).id, changes={"status": "not_affected"})
        post_update(team, user, drafted.id, kind="resolved")

        result = update_product_status(team, user, drafted.id, _row(drafted, app).id, changes={"status": "in_triage"})

        assert result.status_code == 409
        assert "Reopen it first" in (result.error or "")

    def test_an_advisory_with_products_cannot_open_as_resolved(self, team, user, action):
        result = create_advisory(team, user, title="Born resolved", remediation_status="resolved", products=[action])

        assert result.status_code == 400
        assert not SecurityAdvisory.objects.filter(title="Born resolved").exists()

    def test_a_published_advisory_keeps_its_publish_rules(self, team, user, drafted, action):
        publish(drafted, visibility=SecurityAdvisory.Visibility.PUBLIC)
        row = _row(drafted, action)

        result = update_product_status(team, user, drafted.id, row.id, changes={"status": "resolved"})

        assert not result.ok
        assert "names no fixed version" in (result.error or "")
        row.refresh_from_db()
        assert row.status == "in_triage"
        assert not AdvisoryEvent.objects.filter(advisory=drafted, event_type="field_change").exists()

    def test_a_withdrawn_advisory_is_final(self, team, user, drafted, action):
        publish(drafted)
        drafted.status = SecurityAdvisory.Status.WITHDRAWN
        drafted.withdrawal_reason = "Duplicate."
        drafted.withdrawn_at = drafted.published_at
        drafted.save()

        result = update_product_status(team, user, drafted.id, _row(drafted, action).id, changes={"status": "resolved"})

        assert result.status_code == 409


class TestOneEditIsOneCsafRevision:
    def test_the_row_and_its_range_bump_the_document_once(
        self, team, user, drafted, action, fixed, django_capture_on_commit_callbacks
    ):
        publish(drafted, visibility=SecurityAdvisory.Visibility.PUBLIC)
        drafted.refresh_from_db()
        before = drafted.csaf_revision

        with django_capture_on_commit_callbacks(execute=True):
            update_product_status(
                team,
                user,
                drafted.id,
                _row(drafted, action).id,
                changes={"status": "resolved", "fixed_release_id": fixed.id, "action_statement": "Upgrade."},
            )

        drafted.refresh_from_db()
        assert drafted.csaf_revision == before + 1


class TestEveryRowOfAProduct:
    def test_it_writes_the_product_row_for_each_vulnerability(self, team, user, drafted, action, fixed):
        second = AdvisoryVulnerability.objects.create(advisory=drafted, cve_id="CVE-2026-0004")
        link = drafted.products.get(product=action)
        AdvisoryProductStatus.objects.create(vulnerability=second, advisory_product=link)

        result = update_product_statuses(
            team, user, drafted.id, action.id, changes={"status": "resolved", "fixed_release_id": fixed.id}
        )

        assert result.ok, result.error
        rows = AdvisoryProductStatus.objects.filter(advisory_product=link)
        assert {r.status for r in rows} == {"resolved"}
        # With two vulnerabilities, the timeline says which row moved.
        bodies = AdvisoryEvent.objects.filter(advisory=drafted, event_type="field_change").values_list(
            "body", flat=True
        )
        assert any("(CVE-2026-0004)" in body for body in bodies)

    def test_it_narrows_to_one_vulnerability(self, team, user, drafted, action):
        second = AdvisoryVulnerability.objects.create(advisory=drafted, cve_id="CVE-2026-0004")
        link = drafted.products.get(product=action)
        AdvisoryProductStatus.objects.create(vulnerability=second, advisory_product=link)

        update_product_statuses(
            team, user, drafted.id, action.id, changes={"status": "exploitable"}, vulnerability_id=second.id
        )

        assert dict(
            AdvisoryProductStatus.objects.filter(advisory_product=link).values_list("vulnerability__cve_id", "status")
        ) == {
            "CVE-2026-0003": "in_triage",
            "CVE-2026-0004": "exploitable",
        }

    def test_a_product_the_advisory_does_not_name_is_not_found(self, team, user, drafted):
        stray = Product.objects.create(name="Elsewhere", team=team)

        assert (
            update_product_statuses(team, user, drafted.id, stray.id, changes={"status": "resolved"}).status_code == 404
        )


class TestAddingProductsLater:
    def test_a_missed_product_joins_under_investigation_with_its_releases(self, team, user, drafted):
        late = Product.objects.create(name="sbomify CLI", team=team)
        release = Release.objects.create(product=late, name="v3.1.0", version="v3.1.0")

        result = add_advisory_product(team, user, drafted.id, product=late, affected_releases=[release])

        assert result.ok, result.error
        row = _row(drafted, late)
        assert row.status == "in_triage"
        assert list(row.version_ranges.values_list("introduced", "last_affected")) == [("v3.1.0", "v3.1.0")]
        event = AdvisoryEvent.objects.get(advisory=drafted, event_type=AdvisoryEvent.EventType.PRODUCT_ADDED)
        assert event.body == "sbomify CLI added, affected in v3.1.0."

    def test_a_product_already_named_gains_only_its_new_releases(self, team, user, drafted, action, affected):
        newer = Release.objects.create(product=action, name="v26.9.1", version="v26.9.1")

        assert add_advisory_product(team, user, drafted.id, product=action, affected_releases=[affected, newer]).ok

        pins = _row(drafted, action).version_ranges.values_list("last_affected", flat=True)
        assert sorted(pins) == ["v26.9.0", "v26.9.1"]
        assert drafted.products.filter(product=action).count() == 1

    def test_a_resolved_advisory_needs_the_new_product_decided(self, team, user, drafted, action, app, fixed):
        update_product_statuses(
            team, user, drafted.id, action.id, changes={"status": "resolved", "fixed_release_id": fixed.id}
        )
        update_product_statuses(team, user, drafted.id, app.id, changes={"status": "not_affected"})
        post_update(team, user, drafted.id, kind="resolved")
        late = Product.objects.create(name="sbomify CLI", team=team)

        refused = add_advisory_product(team, user, drafted.id, product=late)
        accepted = add_advisory_product(team, user, drafted.id, product=late, changes={"status": "not_affected"})

        assert refused.status_code == 409
        assert accepted.ok, accepted.error
        assert _row(drafted, late).status == "not_affected"

    def test_the_floating_latest_release_cannot_be_pinned(self, team, user, drafted, action):
        latest = _latest(action)

        result = add_advisory_product(team, user, drafted.id, product=action, affected_releases=[latest])

        assert not result.ok
        assert _row(drafted, action).version_ranges.count() == 1

    def test_a_workspace_notice_names_no_products(self, team, user, notice, action):
        assert add_advisory_product(team, user, notice.id, product=action).status_code == 400


class TestTheSummary:
    def test_it_is_written_and_recorded(self, team, user, drafted):
        assert update_advisory(team, user, drafted.id, title=drafted.title, summary="  Rotate your token.  ").ok

        drafted.refresh_from_db()
        assert drafted.summary == "Rotate your token."
        assert AdvisoryEvent.objects.filter(advisory=drafted, payload__field="summary").exists()

    def test_leaving_it_out_keeps_it(self, team, user, drafted):
        update_advisory(team, user, drafted.id, title=drafted.title, summary="Kept.")

        update_advisory(team, user, drafted.id, title="Renamed")

        drafted.refresh_from_db()
        assert drafted.summary == "Kept."


class TestTheProjection:
    def test_the_detail_lists_every_row_with_its_fix(self, team, user, drafted, action, fixed):
        update_product_statuses(
            team, user, drafted.id, action.id, changes={"status": "resolved", "fixed_release_id": fixed.id}
        )

        statuses = get_advisory(team, drafted.id).value["statuses"]

        by_product = {row["product"]: row for row in statuses}
        assert set(by_product) == {"sbomify Action", "sbomify"}
        assert by_product["sbomify Action"]["status_label"] == "Fixed"
        assert by_product["sbomify Action"]["fixed_version"] == "v26.10.1"
        assert by_product["sbomify Action"]["fixed_release_id"] == fixed.id
        assert by_product["sbomify Action"]["affected_versions"] == ["v26.9.0"]
        assert get_advisory(team, drafted.id).value["open_status_count"] == 1


# --- the API -----------------------------------------------------------------


def _v2(advisory_id: str, suffix: str = "") -> str:
    return f"/api/v2/advisories/{advisory_id}{suffix}"


@pytest.fixture
def owner_api(authenticated_api_client, sample_team_with_owner_member):
    client, token = authenticated_api_client
    return client, get_api_headers(token)


class TestTheStatusEndpoints:
    def test_one_row_is_patched_and_the_detail_returns_it(self, owner_api, drafted, action, fixed):
        client, headers = owner_api
        row = _row(drafted, action)

        response = client.patch(
            _v2(drafted.id, f"/statuses/{row.id}"),
            data={"status": "resolved", "fixed_release_id": fixed.id},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        listed = {s["id"]: s for s in response.json()["statuses"]}
        assert listed[row.id]["status"] == "resolved"
        assert listed[row.id]["fixed_version"] == "v26.10.1"
        assert listed[row.id]["label"] == "sbomify Action"

    def test_an_unknown_field_is_a_422(self, owner_api, drafted, action):
        client, headers = owner_api

        response = client.patch(
            _v2(drafted.id, f"/statuses/{_row(drafted, action).id}"),
            data={"stauts": "resolved"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 422

    def test_a_member_may_not(self, owner_api, sample_team_with_owner_member, drafted, action):
        client, headers = owner_api
        sample_team_with_owner_member.role = "member"
        sample_team_with_owner_member.save()

        response = client.patch(
            _v2(drafted.id, f"/statuses/{_row(drafted, action).id}"),
            data={"status": "resolved"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        assert _row(drafted, action).status == "in_triage"

    def test_the_agent_token_records_fixed_versions(
        self, sample_user, sample_team_with_owner_member, drafted, action, fixed
    ):
        """The triage runbook's agent records the fix without a person doing it."""
        token = AccessToken.objects.create(
            user=sample_user,
            encoded_token=create_personal_access_token(sample_user),
            description="Triage agent",
            scopes=authz.SCOPE_PRESETS["agent"],
        )

        response = Client().patch(
            _v2(drafted.id, f"/products/{action.id}/status"),
            data={"status": "resolved", "fixed_release_id": fixed.id, "action_statement": "Upgrade to v26.10.1"},
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 200, response.content
        event = AdvisoryEvent.objects.filter(advisory=drafted, payload__field="product_status.status").get()
        assert event.payload["via"]["channel"] == "agent"

    def test_a_product_is_added_through_the_api(self, owner_api, team, drafted):
        client, headers = owner_api
        late = Product.objects.create(name="sbomify CLI", team=team)
        release = Release.objects.create(product=late, name="v3.1.0", version="v3.1.0")

        response = client.post(
            _v2(drafted.id, "/products"),
            data={"product_id": late.id, "affected_release_ids": [release.id]},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        names = [p["name"] for p in response.json()["products"]]
        assert "sbomify CLI" in names

    def test_a_product_of_another_workspace_is_not_found(self, owner_api, other_team, drafted):
        client, headers = owner_api
        theirs = Product.objects.create(name="Theirs", team=other_team)

        response = client.post(
            _v2(drafted.id, "/products"), data={"product_id": theirs.id}, content_type="application/json", **headers
        )

        assert response.status_code == 404

    def test_resolving_with_open_rows_is_a_400_naming_them(self, owner_api, drafted):
        client, headers = owner_api

        response = client.post(
            _v2(drafted.id, "/updates"), data={"kind": "resolved"}, content_type="application/json", **headers
        )

        assert response.status_code == 400
        assert "sbomify Action is Under investigation" in response.json()["detail"]


class TestTheSummaryOverTheApi:
    def test_it_is_stored(self, owner_api, drafted):
        client, headers = owner_api

        response = client.patch(
            _v2(drafted.id), data={"summary": "Rotate your token."}, content_type="application/json", **headers
        )

        assert response.status_code == 200, response.content
        assert response.json()["summary"] == "Rotate your token."

    def test_a_field_the_endpoint_does_not_write_is_a_422_not_a_silent_200(self, owner_api, drafted):
        client, headers = owner_api

        response = client.patch(
            _v2(drafted.id), data={"remediation_status": "resolved"}, content_type="application/json", **headers
        )

        assert response.status_code == 422
        drafted.refresh_from_db()
        assert drafted.remediation_status == "fix_in_progress"


class TestTheRepairEndToEnd:
    """The published advisory that started this, repaired through the API alone."""

    def test_the_trust_center_and_csaf_say_fixed(self, client, owner_api, team, drafted, action, app, fixed):
        api, headers = owner_api
        publish(drafted, visibility=SecurityAdvisory.Visibility.PUBLIC)

        for product, body in (
            (action, {"status": "resolved", "fixed_release_id": fixed.id, "action_statement": "Upgrade to v26.10.1"}),
            (
                app,
                {
                    "status": "resolved",
                    "fixed_version": "33b63393",
                    "action_statement": "Pull the master image built from commit 33b63393 or later.",
                },
            ),
        ):
            patched = api.patch(
                _v2(drafted.id, f"/products/{product.id}/status"), data=body, content_type="application/json", **headers
            )
            assert patched.status_code == 200, patched.content
        resolved = api.post(
            _v2(drafted.id, "/updates"), data={"kind": "resolved"}, content_type="application/json", **headers
        )
        assert resolved.status_code == 200, resolved.content

        public = client.get(f"/api/v2/advisories/public/{team.key}/{drafted.id}").json()
        assert {(s["product"], s["status"]) for s in public["statuses"]} == {
            ("sbomify Action", "resolved"),
            ("sbomify", "resolved"),
        }

        page = client.get(
            reverse("core:advisory_details_public", kwargs={"workspace_key": team.key, "advisory_id": drafted.id})
        ).content.decode()
        assert "Under investigation" not in page
        assert "Fixed" in page
        assert "Upgrade to v26.10.1" in page
        # The instructions already name the fix, so it is not said twice.
        assert "Upgrade to <span" not in page

        csaf = client.get(f"/api/v2/advisories/public/{team.key}/{drafted.id}/csaf").json()
        names = {entry["product_id"]: entry["name"] for entry in csaf["product_tree"]["full_product_names"]}
        status = csaf["vulnerabilities"][0]["product_status"]
        assert "under_investigation" not in status
        assert "sbomify Action >= v26.10.1" in {names[pid] for pid in status["fixed"]}
        remediations = csaf["vulnerabilities"][0]["remediations"]
        assert {r["category"] for r in remediations} == {"vendor_fix"}
        assert any(r["details"] == "Upgrade to v26.10.1" for r in remediations)


# --- the page ----------------------------------------------------------------


class TestTheDetailPage:
    def _open(self, client, member, advisory):
        setup_authenticated_client_session(client, member.team, member.user)
        return client.get(reverse("core:security_advisory_detail", args=[advisory.id]))

    def test_it_lists_the_rows_with_an_edit_dialog(self, client, sample_team_with_owner_member, drafted):
        content = self._open(client, sample_team_with_owner_member, drafted).content.decode()

        assert "Product statuses" in content
        assert 'aria-label="Edit status for sbomify Action"' in content
        assert 'name="intent" value="product_status"' in content
        assert 'name="intent" value="add_product"' in content
        assert 'id="advisory-statuses"' in content

    def test_a_member_sees_the_rows_but_cannot_edit_them(self, client, sample_team_with_owner_member, drafted):
        sample_team_with_owner_member.role = "member"
        sample_team_with_owner_member.save()

        content = self._open(client, sample_team_with_owner_member, drafted).content.decode()

        assert "Product statuses" in content
        assert 'value="product_status"' not in content

    def test_saving_the_dialog_writes_the_row(self, client, sample_team_with_owner_member, drafted, action, fixed):
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        row = _row(drafted, action)

        response = client.post(
            reverse("core:security_advisory_detail", args=[drafted.id]),
            {
                "intent": "product_status",
                "status_id": row.id,
                "status": "resolved",
                "fixed_version": "v26.10.1",
                "fixed_release_id": fixed.id,
                "response": "update",
                "action_statement": "Upgrade to v26.10.1",
                "impact_statement": "",
            },
            follow=True,
        )

        assert "Product status saved." in response.content.decode()
        row.refresh_from_db()
        assert (row.status, row.response, row.recommended_release) == ("resolved", "update", fixed)

    def test_a_refusal_is_shown(self, client, sample_team_with_owner_member, drafted, action, other_team):
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        latest = _latest(action)

        response = client.post(
            reverse("core:security_advisory_detail", args=[drafted.id]),
            {"intent": "product_status", "status_id": _row(drafted, action).id, "fixed_release_id": latest.id},
            follow=True,
        )

        assert "Product status not saved: The floating latest release cannot be the fixed release." in (
            response.content.decode()
        )

    def test_resolving_from_the_composer_names_the_open_rows(self, client, sample_team_with_owner_member, drafted):
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )

        response = client.post(
            reverse("core:security_advisory_detail", args=[drafted.id]), {"kind": "resolved", "note": ""}, follow=True
        )

        assert "sbomify Action is Under investigation" in response.content.decode()
        drafted.refresh_from_db()
        assert drafted.remediation_status == "fix_in_progress"

    def test_adding_a_product_from_the_page(self, client, sample_team_with_owner_member, team, drafted):
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        late = Product.objects.create(name="sbomify CLI", team=team)
        release = Release.objects.create(product=late, name="v3.1.0", version="v3.1.0")

        response = client.post(
            reverse("core:security_advisory_detail", args=[drafted.id]),
            {"intent": "add_product", "product": late.id, "affected_releases": [release.id], "status": "in_triage"},
            follow=True,
        )

        assert "Added &quot;sbomify CLI&quot;." in response.content.decode()
        assert _row(drafted, late).version_ranges.count() == 1

    def test_the_edit_dialog_writes_the_summary(self, client, sample_team_with_owner_member, drafted):
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )

        client.post(
            reverse("core:security_advisory_detail", args=[drafted.id]),
            {"intent": "edit", "title": drafted.title, "summary": "Rotate your token.", "description": ""},
        )

        drafted.refresh_from_db()
        assert drafted.summary == "Rotate your token."
