"""Mapping a Vanta programme onto the controls models."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import IntegrityError, transaction

from django.utils import timezone

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus, ControlStatusLog
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.services import vanta_sync
from sbomify.apps.integrations.services.vanta_sync import sync
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


class FakeVantaClient:
    """Stands in for the API, and counts what the sync asked it for."""

    def __init__(self, frameworks: list[dict], controls: dict[str, list[dict]], details: dict[str, dict]) -> None:
        self._frameworks = frameworks
        self._controls = controls
        self._details = details
        self.detail_calls: list[str] = []

    def frameworks(self):
        return iter(self._frameworks)

    def framework_controls(self, framework_id: str):
        return iter(self._controls.get(framework_id, []))

    def control(self, control_id: str) -> dict[str, Any]:
        self.detail_calls.append(control_id)
        return self._details.get(control_id, {})


@pytest.fixture
def install_client(monkeypatch, vanta_credentials):
    """Swap the real client out and hand the test the fake it will use."""

    def _install(frameworks, controls, details) -> FakeVantaClient:
        fake = FakeVantaClient(frameworks, controls, details)
        monkeypatch.setattr(vanta_sync, "VantaClient", lambda token, base_url: fake)
        monkeypatch.setattr(vanta_sync, "access_token", lambda integration, provider: "vat_token")
        return fake

    return _install


SOC2 = {"id": "fw_soc2", "displayName": "SOC 2 Type II", "shorthandName": "SOC 2"}
ISO = {"id": "fw_iso", "displayName": "ISO 27001", "shorthandName": "ISO 27001"}


def _control(vanta_id: str, code: str, name: str, domain: str) -> dict[str, Any]:
    return {"id": vanta_id, "externalId": code, "name": name, "description": f"{name} description", "domains": [domain]}


class TestFirstSync:
    def test_creates_a_catalogue_per_framework(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )

        result = sync(connected_vanta)

        assert result.ok
        catalog = ControlCatalog.objects.get(team=connected_vanta.team, source=ControlCatalog.Source.VANTA)
        assert catalog.name == "SOC 2 Type II"
        assert catalog.external_id == "fw_soc2"
        assert result.value["frameworks"] == 1
        assert result.value["controls"] == 1

    def test_a_new_framework_is_not_published_until_someone_says_so(self, connected_vanta, install_client) -> None:
        """Connecting reads data. Putting it on a public page is a second decision.

        Active because the workspace does track the framework; unpublished
        because nobody has said to show it to their customers.
        """
        install_client([SOC2], {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]}, {})

        sync(connected_vanta)

        catalog = ControlCatalog.objects.get(team=connected_vanta.team, source=ControlCatalog.Source.VANTA)
        assert catalog.is_active is True
        assert catalog.is_published is False

    def test_maps_the_control_fields_a_reader_sees(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )

        sync(connected_vanta)

        control = Control.objects.get(catalog__external_id="fw_soc2")
        assert control.control_id == "CC1.1"
        assert control.external_id == "c1"
        assert control.title == "Control environment"
        assert control.group == "Security"

    def test_a_control_with_no_external_code_falls_back_to_its_vanta_id(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [{"id": "c_custom", "name": "Our own control", "domains": []}]},
            {"c_custom": {"status": "NOT_STARTED"}},
        )

        sync(connected_vanta)

        control = Control.objects.get(catalog__external_id="fw_soc2")
        assert control.control_id == "c_custom"
        assert control.group == "General"

    def test_a_framework_with_no_id_is_skipped(self, connected_vanta, install_client) -> None:
        install_client([{"displayName": "Nameless"}], {}, {})

        result = sync(connected_vanta)

        assert result.value["frameworks"] == 0
        assert not ControlCatalog.objects.filter(team=connected_vanta.team).exists()


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("vanta_status", "expected"),
        [
            ("COMPLETED", ControlStatus.Status.COMPLIANT),
            ("IN_PROGRESS", ControlStatus.Status.PARTIAL),
            ("NOT_STARTED", ControlStatus.Status.NOT_IMPLEMENTED),
            ("NO_EVIDENCE_MAPPED", ControlStatus.Status.NOT_IMPLEMENTED),
            ("SOMETHING_NEW", ControlStatus.Status.NOT_IMPLEMENTED),
            ("", ControlStatus.Status.NOT_IMPLEMENTED),
        ],
    )
    def test_every_vanta_state_lands_somewhere_scoreable(
        self, connected_vanta, install_client, vanta_status, expected
    ) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": vanta_status}},
        )

        sync(connected_vanta)

        status = ControlStatus.objects.get(control__control_id="CC1.1", product__isnull=True)
        assert status.status == expected
        assert status.notes == vanta_sync.SYNC_NOTE

    def test_a_status_change_is_logged_once(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "IN_PROGRESS"}},
        )
        sync(connected_vanta)

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        result = sync(connected_vanta)

        assert result.value["statuses_changed"] == 1
        logs = list(ControlStatusLog.objects.filter(control__control_id="CC1.1").order_by("created_at"))
        assert [(log.old_status, log.new_status) for log in logs] == [
            ("", ControlStatus.Status.PARTIAL),
            (ControlStatus.Status.PARTIAL, ControlStatus.Status.COMPLIANT),
        ]

    def test_an_unchanged_status_is_not_logged_again(self, connected_vanta, install_client) -> None:
        for _ in range(2):
            install_client(
                [SOC2],
                {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
                {"c1": {"status": "COMPLETED"}},
            )
            sync(connected_vanta)

        assert ControlStatusLog.objects.filter(control__control_id="CC1.1").count() == 1

    def test_a_product_override_survives_a_sync(self, connected_vanta, install_client) -> None:
        """Vanta describes the organisation, so a per-product decision stays the workspace's."""
        from sbomify.apps.core.models import Product

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "NOT_STARTED"}},
        )
        sync(connected_vanta)

        control = Control.objects.get(control_id="CC1.1")
        product = Product.objects.create(team=connected_vanta.team, name="Widget")
        ControlStatus.objects.create(control=control, product=product, status=ControlStatus.Status.NOT_APPLICABLE)

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        assert ControlStatus.objects.get(control=control, product=product).status == ControlStatus.Status.NOT_APPLICABLE


class TestResync:
    def test_updates_in_place_rather_than_duplicating(self, connected_vanta, install_client) -> None:
        for _ in range(2):
            install_client(
                [SOC2],
                {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
                {"c1": {"status": "COMPLETED"}},
            )
            sync(connected_vanta)

        assert ControlCatalog.objects.filter(team=connected_vanta.team).count() == 1
        assert Control.objects.filter(catalog__external_id="fw_soc2").count() == 1

    def test_a_renamed_framework_keeps_its_catalogue(self, connected_vanta, install_client) -> None:
        install_client([SOC2], {"fw_soc2": []}, {})
        sync(connected_vanta)
        original_id = ControlCatalog.objects.get(external_id="fw_soc2").id

        install_client([{**SOC2, "displayName": "SOC 2 (Type II)"}], {"fw_soc2": []}, {})
        sync(connected_vanta)

        catalog = ControlCatalog.objects.get(external_id="fw_soc2")
        assert catalog.id == original_id
        assert catalog.name == "SOC 2 (Type II)"

    def test_a_control_vanta_dropped_is_removed(self, connected_vanta, install_client) -> None:
        """A leftover row has no status, so it would score as "not met" forever."""
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.1", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board oversight", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        result = sync(connected_vanta)

        # The control count, not every cascaded row it took with it.
        assert result.value["controls_removed"] == 1
        assert list(Control.objects.filter(catalog__external_id="fw_soc2").values_list("control_id", flat=True)) == [
            "CC1.1"
        ]

    def test_a_framework_vanta_dropped_is_unpublished_but_kept(self, connected_vanta, install_client) -> None:
        install_client([SOC2, ISO], {"fw_soc2": [], "fw_iso": []}, {})
        sync(connected_vanta)
        ControlCatalog.objects.filter(team=connected_vanta.team).update(is_published=True)

        install_client([SOC2], {"fw_soc2": []}, {})
        sync(connected_vanta)

        assert ControlCatalog.objects.get(external_id="fw_iso").is_published is False
        assert ControlCatalog.objects.get(external_id="fw_soc2").is_published is True
        # Kept, not deleted: the status history is worth more than the row.
        assert ControlCatalog.objects.filter(external_id="fw_iso").exists()

    def test_a_hand_maintained_catalogue_is_never_touched(self, connected_vanta, install_client) -> None:
        builtin = ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="2024",
            source=ControlCatalog.Source.BUILTIN,
            is_active=True,
            is_published=True,
        )
        install_client([SOC2], {"fw_soc2": []}, {})

        sync(connected_vanta)

        builtin.refresh_from_db()
        assert builtin.is_active is True
        assert builtin.is_published is True


class TestRequestBudget:
    def test_a_control_in_two_frameworks_is_fetched_once(self, connected_vanta, install_client) -> None:
        shared = _control("c_shared", "CC1.1", "Control environment", "Security")
        fake = install_client(
            [SOC2, ISO],
            {"fw_soc2": [shared], "fw_iso": [shared]},
            {"c_shared": {"status": "COMPLETED"}},
        )

        sync(connected_vanta)

        assert fake.detail_calls == ["c_shared"]


class TestAnEmptyAnswerIsNotAnInstruction:
    """The client is tolerant of a body it cannot parse, so "nothing came back"
    and "there is nothing" arrive here as the same empty list. Neither one may
    be treated as "delete what you have".
    """

    def test_a_framework_that_returns_no_controls_keeps_the_ones_it_has(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        install_client([SOC2], {"fw_soc2": []}, {})
        result = sync(connected_vanta)

        assert result.ok
        assert Control.objects.filter(catalog__external_id="fw_soc2").count() == 1
        assert result.value["controls_removed"] == 0

    def test_the_statuses_survive_too(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        install_client([SOC2], {"fw_soc2": []}, {})
        sync(connected_vanta)

        assert (
            ControlStatus.objects.get(control__control_id="CC1.1", product__isnull=True).status
            == ControlStatus.Status.COMPLIANT
        )

    def test_no_frameworks_at_all_leaves_published_ones_alone(self, connected_vanta, install_client) -> None:
        """Otherwise one unparseable response empties the whole trust center."""
        install_client([SOC2], {"fw_soc2": []}, {})
        sync(connected_vanta)
        ControlCatalog.objects.filter(team=connected_vanta.team).update(is_published=True)

        install_client([], {}, {})
        result = sync(connected_vanta)

        assert result.ok
        assert result.value["frameworks"] == 0
        assert ControlCatalog.objects.get(external_id="fw_soc2").is_published is True


class TestOversizedProviderStrings:
    """Every string here is someone else's and the columns are bounded."""

    def test_a_long_control_code_is_cut_to_fit(self, connected_vanta, install_client) -> None:
        long_code = "CC" + "9" * 200
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", long_code, "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )

        result = sync(connected_vanta)

        assert result.ok
        control = Control.objects.get(catalog__external_id="fw_soc2")
        assert control.control_id == long_code[:50]

    def test_a_long_title_and_domain_are_cut_to_fit(self, connected_vanta, install_client) -> None:
        payload = _control("c1", "CC1.1", "T" * 900, "D" * 400)
        install_client([SOC2], {"fw_soc2": [payload]}, {"c1": {"status": "COMPLETED"}})

        result = sync(connected_vanta)

        assert result.ok
        control = Control.objects.get(catalog__external_id="fw_soc2")
        assert len(control.title) == 500
        assert len(control.group) == 255

    def test_a_long_framework_name_is_cut_to_fit(self, connected_vanta, install_client) -> None:
        install_client([{"id": "fw_long", "displayName": "F" * 400}], {"fw_long": []}, {})

        result = sync(connected_vanta)

        assert result.ok
        assert len(ControlCatalog.objects.get(external_id="fw_long").name) == 255


class TestAFrameworkExistsOnce:
    """One catalog per framework, enforced where a race cannot get past it.

    Two syncs of the same account can both miss the lookup and both insert.
    Left alone that splits one framework's controls and statuses across two
    catalogs, and later syncs pick between them by whichever row comes back
    first.
    """

    def test_the_database_refuses_a_second_catalogue_for_one_framework(self, connected_vanta) -> None:
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="SOC 2",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_soc2",
        )

        # The savepoint is what keeps the refusal from poisoning the test's own
        # transaction, and is why the sync wraps its insert the same way.
        with pytest.raises(IntegrityError), transaction.atomic():
            ControlCatalog.objects.create(
                team=connected_vanta.team,
                name="SOC 2 Type II",
                version="fw_soc2",
                source=ControlCatalog.Source.VANTA,
                external_id="fw_soc2",
            )

    def test_hand_maintained_catalogues_still_coexist(self, connected_vanta) -> None:
        """They carry no external id, so uniqueness must not apply to them."""
        for version in ("2017", "2024"):
            ControlCatalog.objects.create(
                team=connected_vanta.team,
                name="SOC 2 Type II",
                version=version,
                source=ControlCatalog.Source.BUILTIN,
            )

        assert ControlCatalog.objects.filter(team=connected_vanta.team, external_id="").count() == 2

    def test_a_name_collision_with_a_builtin_still_imports_under_its_own_label(
        self, connected_vanta, install_client
    ) -> None:
        """The workspace's own copy of SOC 2 must not block the synced one."""
        ControlCatalog.objects.create(
            team=connected_vanta.team,
            name="SOC 2 Type II",
            version="SOC 2",
            source=ControlCatalog.Source.BUILTIN,
        )
        install_client([SOC2], {"fw_soc2": [_control("c_one", "CC1.1", "Control environment", "Security")]}, {})

        sync(connected_vanta)

        synced = ControlCatalog.objects.get(team=connected_vanta.team, source=ControlCatalog.Source.VANTA)
        assert synced.external_id == "fw_soc2"
        assert synced.version == "fw_soc2"


class TestAControlKeepsItsHistoryWhenVantaRenamesTheCode:
    """The code a reader recognises is a label, not identity.

    `control_id` is the framework's own code, and Vanta can change it. Keying
    the row on it made a renamed control a new row, which the prune in the same
    pass then deleted, taking the control's statuses and its whole status log
    with it. `external_id` is Vanta's id and does not move.
    """

    def test_a_renamed_code_updates_the_row_it_already_had(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        original = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c1")

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.2", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        controls = list(Control.objects.filter(catalog__source=ControlCatalog.Source.VANTA))
        assert len(controls) == 1
        assert controls[0].id == original.id
        assert controls[0].control_id == "CC1.2"

    def test_the_status_and_its_history_survive_the_rename(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "IN_PROGRESS"}},
        )
        sync(connected_vanta)

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.2", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        control = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c1")
        logs = list(ControlStatusLog.objects.filter(control=control).order_by("created_at"))
        assert [(log.old_status, log.new_status) for log in logs] == [
            ("", ControlStatus.Status.PARTIAL),
            (ControlStatus.Status.PARTIAL, ControlStatus.Status.COMPLIANT),
        ]

    def test_a_rename_onto_a_code_already_taken_keeps_both_rows(self, connected_vanta, install_client) -> None:
        """(catalog, control_id) is unique, so a collision must not fail the sync."""
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.1", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board oversight", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.2", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board oversight", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        assert Control.objects.filter(catalog__source=ControlCatalog.Source.VANTA).count() == 2


class TestAReconnectStopsTheRunItReplaced:
    """A sync is minutes long, so the account can change under it."""

    def test_a_superseded_run_does_not_retire_frameworks(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        ControlCatalog.objects.filter(team=connected_vanta.team).update(is_published=True)

        # Vanta now answers with a different programme, which would normally
        # retire SOC 2. The reconnect lands first.
        install_client([ISO], {"fw_iso": [_control("c9", "A.5.1", "Policies", "Org")]}, {"c9": {"status": "COMPLETED"}})
        Integration.objects.filter(pk=connected_vanta.pk).update(connected_at=timezone.now())

        result = sync(connected_vanta)

        assert not result.ok
        assert ControlCatalog.objects.get(external_id="fw_soc2").is_published is True

    def test_a_current_run_still_retires(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        ControlCatalog.objects.filter(team=connected_vanta.team).update(is_published=True)

        install_client([ISO], {"fw_iso": [_control("c9", "A.5.1", "Policies", "Org")]}, {"c9": {"status": "COMPLETED"}})
        result = sync(connected_vanta)

        assert result.ok
        assert ControlCatalog.objects.get(external_id="fw_soc2").is_published is False


class TestWhatVantaDropsDoesNotTakeSomebodyElsesDecisionWithIt:
    """The sync never writes product scope, and must not delete it either.

    Deleting a Control cascades its statuses, so pruning a control Vanta
    stopped listing took any product override on it, and that override's
    history, with no trace.
    """

    def _product(self, team):
        from sbomify.apps.core.models import Product

        return Product.objects.create(team=team, name="Widget")

    def test_a_control_with_a_product_override_is_kept(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.1", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        kept = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c2")
        ControlStatus.objects.create(
            control=kept, product=self._product(connected_vanta.team), status=ControlStatus.Status.COMPLIANT
        )

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        assert Control.objects.filter(pk=kept.pk).exists()
        assert ControlStatus.objects.filter(control=kept, product__isnull=False).exists()

    def test_its_stale_workspace_status_goes(self, connected_vanta, install_client) -> None:
        """Vanta was answering for that one, and it is no longer answering."""
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.1", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        kept = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c2")
        ControlStatus.objects.create(
            control=kept, product=self._product(connected_vanta.team), status=ControlStatus.Status.COMPLIANT
        )

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        assert Control.objects.filter(pk=kept.pk).exists()
        assert not ControlStatus.objects.filter(control=kept, product__isnull=True).exists()

    def test_a_control_nobody_overrode_is_still_deleted(self, connected_vanta, install_client) -> None:
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    _control("c1", "CC1.1", "Control environment", "Security"),
                    _control("c2", "CC1.2", "Board", "Security"),
                ]
            },
            {"c1": {"status": "COMPLETED"}, "c2": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        install_client(
            [SOC2],
            {"fw_soc2": [_control("c1", "CC1.1", "Control environment", "Security")]},
            {"c1": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        assert not Control.objects.filter(catalog__source=ControlCatalog.Source.VANTA, external_id="c2").exists()


class TestARecreatedControlDoesNotInheritTheOldOne:
    def test_a_new_control_under_a_used_code_takes_a_label_of_its_own(self, connected_vanta, install_client) -> None:
        """Vanta deleting and recreating under one code must not reassign identity."""
        install_client(
            [SOC2],
            {"fw_soc2": [_control("c_old", "CC1.1", "Control environment", "Security")]},
            {"c_old": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)
        old = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c_old")

        # Same code, different upstream id, and the old one still listed so the
        # collision is live rather than resolved by the prune.
        install_client(
            [SOC2],
            {
                "fw_soc2": [
                    # New one first: processed before the old is renamed off
                    # CC1.1, so the collision is live rather than already gone.
                    _control("c_new", "CC1.1", "Board oversight", "Security"),
                    _control("c_old", "CC9.9", "Control environment", "Security"),
                ]
            },
            {"c_old": {"status": "COMPLETED"}, "c_new": {"status": "COMPLETED"}},
        )
        sync(connected_vanta)

        old.refresh_from_db()
        assert old.external_id == "c_old"
        new = Control.objects.get(catalog__source=ControlCatalog.Source.VANTA, external_id="c_new")
        assert new.pk != old.pk
