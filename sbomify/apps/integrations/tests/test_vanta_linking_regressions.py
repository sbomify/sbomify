"""Requirement identifiers and connection ownership during framework linking."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import OperationalError, connections, transaction
from django.utils import timezone

from sbomify.apps.controls.models import ControlMapping
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.services import vanta_sync
from sbomify.apps.integrations.tests.test_vanta_sync import SOC2, FakeVantaClient, _builtin, _control, _requirement

pytestmark = pytest.mark.django_db


@pytest.fixture
def linking_account(connected_vanta, vanta_credentials, monkeypatch):
    fake = FakeVantaClient(
        [SOC2],
        {"fw_soc2": [_control("v1", "ONE", "One", "General"), _control("v2", "TWO", "Two", "General")]},
        {},
    )
    fake.requirements["fw_soc2"] = [_requirement(code, "v1") for code in ("CC1.1", "CC6.1", "CC6.2")]
    _builtin(connected_vanta.team, "SOC 2 Type II", ["CC1.1", "CC6.1", "CC6.2"])
    monkeypatch.setattr(vanta_sync, "VantaClient", lambda token, base_url: fake)
    monkeypatch.setattr(vanta_sync, "access_token", lambda integration, provider: "vat_test")
    return fake


@pytest.mark.parametrize("shorthand", [None, "", "  "])
def test_soc2_requirement_ids_are_codes_when_shorthand_is_empty(connected_vanta, linking_account, shorthand):
    # Vanta's documented SOC 2 response has id "CC 1.1" and shorthand null.
    linking_account.requirements["fw_soc2"] = [
        {"id": code, "name": "", "shorthand": shorthand, "controlIds": ["v1"]}
        for code in ("CC 1.1", "CC 6.1", "CC 6.2")
    ]

    result = vanta_sync.sync(connected_vanta)

    assert result.ok
    assert result.value["controls_linked"] == 3
    assert set(ControlMapping.objects.values_list("target_control__control_id", flat=True)) == {
        "CC1.1",
        "CC6.1",
        "CC6.2",
    }


def test_shorthand_takes_precedence_over_an_opaque_requirement_id(connected_vanta, linking_account):
    result = vanta_sync.sync(connected_vanta)

    assert result.ok
    assert result.value["controls_linked"] == 3


@pytest.mark.parametrize("change", ["reconnect", "disconnect"])
def test_connection_replaced_during_requirement_fetch_keeps_previous_links(
    connected_vanta, linking_account, monkeypatch, change
):
    assert vanta_sync.sync(connected_vanta).ok
    before = set(ControlMapping.objects.values_list("source_control_id", "target_control_id"))

    def replace_connection(framework_id):
        current = Integration.objects.filter(pk=connected_vanta.pk)
        if change == "reconnect":
            current.update(connected_at=timezone.now())
        else:
            current.delete()
        return [_requirement(code, "v2") for code in ("CC1.1", "CC6.1", "CC6.2")]

    monkeypatch.setattr(linking_account, "framework_requirements", replace_connection)

    result = vanta_sync.sync(connected_vanta)

    assert not result.ok
    assert result.status_code == 409
    assert set(ControlMapping.objects.values_list("source_control_id", "target_control_id")) == before


@pytest.mark.django_db(transaction=True)
def test_connection_is_locked_only_while_writing_links(connected_vanta, linking_account, monkeypatch):
    def try_lock_from_another_connection():
        try:
            with transaction.atomic():
                Integration.objects.select_for_update(nowait=True).get(pk=connected_vanta.pk)
            return True
        except OperationalError as exc:
            assert getattr(exc.__cause__, "pgcode", None) == "55P03"  # PostgreSQL lock_not_available
            return False
        finally:
            connections.close_all()

    fetch = linking_account.framework_requirements
    write_links = vanta_sync.link_framework
    with ThreadPoolExecutor(max_workers=1) as executor:

        def fetch_requirements(framework_id):
            assert executor.submit(try_lock_from_another_connection).result(timeout=5)
            return fetch(framework_id)

        def link_while_locked(catalog, requirements):
            assert not executor.submit(try_lock_from_another_connection).result(timeout=5)
            return write_links(catalog, requirements)

        monkeypatch.setattr(linking_account, "framework_requirements", fetch_requirements)
        monkeypatch.setattr(vanta_sync, "link_framework", link_while_locked)
        result = vanta_sync.sync(connected_vanta)

    assert result.ok
    assert result.value["controls_linked"] == 3
