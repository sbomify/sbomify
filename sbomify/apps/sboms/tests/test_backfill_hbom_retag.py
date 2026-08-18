"""The backfill_hbom_retag management command: forward re-tag of hardware BOMs
stored before HBOM auto-detection, the has_hardware_components stamp, and the
release-slot blast radius the dry run has to surface."""

from __future__ import annotations

import io
import json
import pathlib
from typing import Any

import pytest
from botocore.exceptions import ClientError
from django.core.management import call_command

from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.utils import SBOMDataError

CMD = "sbomify.apps.sboms.management.commands.backfill_hbom_retag"
_DATA = pathlib.Path(__file__).parent / "test_data"
HBOM_DATA = json.loads((_DATA / "hbom_pcie_sata_adapter.cdx.json").read_text())  # pure: every component a device
PLAIN_DATA = json.loads((_DATA / "sbomify_trivy.cdx.json").read_text())
MIXED_DATA: dict[str, Any] = {"components": [{"type": "device", "name": "board"}, {"type": "library", "name": "libc"}]}


def _make_sbom(component: Component, name: str, bom_type: str = "sbom") -> SBOM:
    return SBOM.objects.create(
        name=name,
        component=component,
        format="cyclonedx",
        version=name,  # distinct per row to satisfy unique (component, version, format, qualifiers, bom_type)
        sbom_filename=f"{name}.json",
        bom_type=bom_type,
    )


def _run(*args: str) -> str:
    out, err = io.StringIO(), io.StringIO()
    call_command("backfill_hbom_retag", *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


@pytest.fixture
def enqueue(mocker):
    return mocker.patch(f"{CMD}.enqueue_assessments_for_sbom", return_value=["ntia", "osv"])


@pytest.fixture
def fetch(mocker):
    """Serve each row's document from a per-id map, like S3 would."""
    docs: dict[str, Any] = {}

    def _fetch(sbom_id):
        return SBOM.objects.get(id=sbom_id), docs[str(sbom_id)]

    mocker.patch(f"{CMD}.get_sbom_data", side_effect=_fetch)
    return docs


@pytest.mark.django_db
def test_retags_hardware_and_reassesses(sample_component, fetch, enqueue):
    hardware = _make_sbom(sample_component, "hardware")
    software = _make_sbom(sample_component, "software")
    fetch[hardware.id] = HBOM_DATA
    fetch[software.id] = PLAIN_DATA

    _run()

    hardware.refresh_from_db()
    software.refresh_from_db()
    assert hardware.bom_type == "hbom"
    assert hardware.has_hardware_components is True
    assert software.bom_type == "sbom"
    assert software.has_hardware_components is False

    enqueue.assert_called_once()
    kwargs = enqueue.call_args.kwargs
    assert kwargs["sbom_id"] == hardware.id
    assert kwargs["team_id"] == str(sample_component.team_id)
    assert kwargs["run_reason"] == RunReason.MANUAL


@pytest.mark.django_db
def test_mixed_document_is_stamped_but_not_retagged(sample_component, fetch, enqueue):
    """Hardware plus software stays an sbom; the stamp is what hardware-gated
    plugins read, and it is independent of the tag."""
    mixed = _make_sbom(sample_component, "mixed")
    fetch[mixed.id] = MIXED_DATA

    _run()

    mixed.refresh_from_db()
    assert mixed.bom_type == "sbom"
    assert mixed.has_hardware_components is True
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_rows_already_tagged_hbom_are_never_read(sample_component, mocker, enqueue):
    already = _make_sbom(sample_component, "already", bom_type="hbom")
    read = mocker.patch(f"{CMD}.get_sbom_data")

    _run()

    already.refresh_from_db()
    assert already.bom_type == "hbom"
    assert already.has_hardware_components is None  # untouched, and None never skips dispatch
    read.assert_not_called()


@pytest.mark.django_db
def test_dry_run_writes_nothing(sample_component, fetch, enqueue):
    hardware = _make_sbom(sample_component, "hardware")
    fetch[hardware.id] = HBOM_DATA

    output = _run("--dry-run")

    hardware.refresh_from_db()
    assert hardware.bom_type == "sbom"
    assert hardware.has_hardware_components is None
    enqueue.assert_not_called()
    assert "would re-tag" in output
    assert "re-tagged-hbom=1" in output and "(dry-run)" in output


@pytest.mark.django_db
def test_dry_run_reports_every_release_whose_slot_changes(sample_product, sample_component, fetch, enqueue):
    """The blast radius: the row leaves the component's sbom slot in each
    release holding it, and an already-occupied hbom slot is a collision the
    operator has to resolve."""
    hardware = _make_sbom(sample_component, "hardware")
    sibling = _make_sbom(sample_component, "sibling")  # stays behind in the sbom slot
    incumbent = _make_sbom(sample_component, "incumbent", bom_type="hbom")  # already holds the destination
    fetch[hardware.id] = HBOM_DATA
    fetch[sibling.id] = PLAIN_DATA

    # Creating an SBOM auto-pins it into the product's "latest" release, whose
    # slot bookkeeping is not what this test is about; drop those and pin by hand.
    ReleaseArtifact.objects.all().delete()
    pinned = Release.objects.create(product=sample_product, name="v1.0.0")
    unrelated = Release.objects.create(product=sample_product, name="v2.0.0")
    for sbom in (hardware, sibling, incumbent):
        ReleaseArtifact.objects.create(release=pinned, sbom=sbom)

    output = _run("--dry-run")

    assert f"on component {sample_component.name}" in output
    assert f"{sample_product.name}/v1.0.0" in output
    assert "cyclonedx/sbom -> cyclonedx/hbom" in output
    assert "sbom slot left holding: sibling" in output
    assert "hbom slot already holds: incumbent (COLLISION)" in output
    assert unrelated.name not in output  # only releases actually holding the row
    assert "release-slots-affected=1" in output


@pytest.mark.django_db
def test_row_pinned_to_no_release_reports_no_slots(sample_component, fetch, enqueue):
    hardware = _make_sbom(sample_component, "hardware")
    fetch[hardware.id] = HBOM_DATA
    ReleaseArtifact.objects.all().delete()  # drop the auto-maintained "latest" pin

    assert "release-slots-affected=0" in _run("--dry-run")


@pytest.mark.django_db
def test_second_run_reports_zero_changes(sample_component, fetch, enqueue):
    hardware = _make_sbom(sample_component, "hardware")
    software = _make_sbom(sample_component, "software")
    fetch[hardware.id] = HBOM_DATA
    fetch[software.id] = PLAIN_DATA

    _run()
    output = _run()

    assert "scanned=1" in output  # the re-tagged row no longer matches bom_type=sbom
    assert "re-tagged-hbom=0" in output
    assert "hardware-stamped=0" in output
    assert enqueue.call_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error",
    [
        SBOMDataError("orphaned S3 object"),
        ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"),
    ],
)
def test_unreadable_row_is_skipped_not_fatal(sample_component, mocker, enqueue, error):
    bad = _make_sbom(sample_component, "bad")
    hardware = _make_sbom(sample_component, "hardware")

    def _fetch(sbom_id):
        if sbom_id == bad.id:
            raise error
        return SBOM.objects.get(id=sbom_id), HBOM_DATA

    mocker.patch(f"{CMD}.get_sbom_data", side_effect=_fetch)

    output = _run()

    hardware.refresh_from_db()
    assert hardware.bom_type == "hbom"  # the sweep carried on past the bad row
    assert f"skip {bad.id}" in output
    assert "errors=1" in output


@pytest.mark.django_db
def test_unreachable_broker_does_not_abort_the_sweep(sample_component, fetch, enqueue):
    """The re-tag is committed and the row is no longer a candidate, so a failed
    enqueue has to be reported rather than lose the rest of the sweep."""
    hardware = _make_sbom(sample_component, "hardware")
    fetch[hardware.id] = HBOM_DATA
    enqueue.side_effect = ConnectionError("broker unavailable")

    output = _run()

    hardware.refresh_from_db()
    assert hardware.bom_type == "hbom"
    assert f"re-tagged {hardware.id} but could not enqueue" in output
    assert "errors=1" in output


@pytest.mark.django_db
def test_uniqueness_collision_keeps_the_stamp(sample_component, fetch, enqueue):
    """The re-tag rolls back on a duplicate hbom row, but the stamp was written
    separately and survives."""
    hardware = _make_sbom(sample_component, "hardware")
    _make_sbom(sample_component, "hardware", bom_type="hbom")  # same unique tuple bar bom_type
    fetch[hardware.id] = HBOM_DATA

    output = _run()

    hardware.refresh_from_db()
    assert hardware.bom_type == "sbom"
    assert hardware.has_hardware_components is True
    assert "errors=1" in output
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_team_id_scopes_to_one_workspace(sample_component, fetch, enqueue):
    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    other_team = Team.objects.create(name="Other")
    other_team.key = number_to_random_token(other_team.pk)
    other_team.save()
    other_component = Component.objects.create(
        name="other", team=other_team, component_type=Component.ComponentType.BOM
    )
    in_scope = _make_sbom(sample_component, "in_scope")
    out_of_scope = _make_sbom(other_component, "out_of_scope")
    fetch[in_scope.id] = HBOM_DATA
    fetch[out_of_scope.id] = HBOM_DATA

    _run("--team-id", str(sample_component.team_id))

    in_scope.refresh_from_db()
    out_of_scope.refresh_from_db()
    assert in_scope.bom_type == "hbom"
    assert out_of_scope.bom_type == "sbom"
    assert out_of_scope.has_hardware_components is None  # never scanned, so never stamped


@pytest.mark.django_db
def test_limit_caps_rows_scanned(sample_component, fetch, enqueue):
    first = _make_sbom(sample_component, "first")
    second = _make_sbom(sample_component, "second")
    fetch[first.id] = HBOM_DATA
    fetch[second.id] = HBOM_DATA

    output = _run("--limit", "1")

    first.refresh_from_db()
    second.refresh_from_db()
    assert "scanned=1" in output
    assert len([s for s in (first, second) if s.bom_type == "hbom"]) == 1
    assert enqueue.call_count == 1
