"""Tests for the backfill_cbom_retag management command (#1069)."""

import json
import pathlib

import pytest
from django.core.management import call_command

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.utils import SBOMDataError

from ..models import SBOM
from .fixtures import sample_component  # noqa: F401

CMD = "sbomify.apps.sboms.management.commands.backfill_cbom_retag"
_TEST_DATA = pathlib.Path(__file__).parent / "test_data"
CBOM_DATA = json.loads((_TEST_DATA / "cbom_sample_1.6.cdx.json").read_text())
PLAIN_DATA = json.loads((_TEST_DATA / "sbomify_trivy.cdx.json").read_text())


def _make_sbom(component, name, bom_type="sbom"):
    return SBOM.objects.create(
        name=name,
        component=component,
        format="cyclonedx",
        version=name,  # distinct per row to satisfy unique (component, version, format, qualifiers, bom_type)
        sbom_filename=f"{name}.json",
        bom_type=bom_type,
    )


@pytest.fixture
def enqueue(mocker):
    return mocker.patch(f"{CMD}.enqueue_assessment")


@pytest.mark.django_db
def test_retags_crypto_and_enqueues_pqc(sample_component, mocker, enqueue):  # noqa: F811
    crypto = _make_sbom(sample_component, "crypto")
    plain = _make_sbom(sample_component, "plain")
    data = {str(crypto.id): CBOM_DATA, str(plain.id): PLAIN_DATA}
    mocker.patch(f"{CMD}.get_sbom_data", side_effect=lambda sid: (SBOM.objects.get(id=sid), data[str(sid)]))

    call_command("backfill_cbom_retag")

    crypto.refresh_from_db()
    plain.refresh_from_db()
    assert crypto.bom_type == "cbom"
    assert plain.bom_type == "sbom"
    enqueue.assert_called_once()
    kwargs = enqueue.call_args.kwargs
    assert kwargs["sbom_id"] == crypto.id
    assert kwargs["plugin_name"] == "pqc-readiness"
    assert kwargs["run_reason"] == RunReason.MANUAL


@pytest.mark.django_db
def test_idempotent_rerun_is_noop(sample_component, mocker, enqueue):  # noqa: F811
    crypto = _make_sbom(sample_component, "crypto")
    mocker.patch(f"{CMD}.get_sbom_data", return_value=(crypto, CBOM_DATA))

    call_command("backfill_cbom_retag")
    call_command("backfill_cbom_retag")  # already cbom -> excluded by the query

    assert enqueue.call_count == 1


@pytest.mark.django_db
def test_skips_enqueue_when_pqc_run_exists(sample_component, mocker, enqueue):  # noqa: F811
    crypto = _make_sbom(sample_component, "crypto")
    AssessmentRun.objects.create(
        sbom=crypto,
        plugin_name="pqc-readiness",
        plugin_version="1.0",
        plugin_config_hash="abc",
        category="assessment",
        run_reason=RunReason.MANUAL.value,
    )
    mocker.patch(f"{CMD}.get_sbom_data", return_value=(crypto, CBOM_DATA))

    call_command("backfill_cbom_retag")

    crypto.refresh_from_db()
    assert crypto.bom_type == "cbom"  # still re-tagged
    enqueue.assert_not_called()  # but no duplicate PQC enqueue


@pytest.mark.django_db
def test_dry_run_writes_nothing(sample_component, mocker, enqueue):  # noqa: F811
    crypto = _make_sbom(sample_component, "crypto")
    mocker.patch(f"{CMD}.get_sbom_data", return_value=(crypto, CBOM_DATA))

    call_command("backfill_cbom_retag", "--dry-run")

    crypto.refresh_from_db()
    assert crypto.bom_type == "sbom"
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_continues_past_fetch_error(sample_component, mocker, enqueue):  # noqa: F811
    bad = _make_sbom(sample_component, "bad")
    crypto = _make_sbom(sample_component, "crypto")

    def fetch(sid):
        if sid == bad.id:
            raise SBOMDataError("orphaned S3 object")
        return (SBOM.objects.get(id=sid), CBOM_DATA)

    mocker.patch(f"{CMD}.get_sbom_data", side_effect=fetch)

    call_command("backfill_cbom_retag")

    crypto.refresh_from_db()
    assert crypto.bom_type == "cbom"  # processed despite the bad row
    enqueue.assert_called_once()
