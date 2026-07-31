"""DT triage → VEX sync, and automatic release VEX pinning."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.core.models import Component, Release, ReleaseArtifact
from sbomify.apps.core.services.vex_pins import ensure_latest_vex_pinned, refresh_vex_pins_for_component
from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.sboms.models import SBOM

TRIAGED_VEX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "serialNumber": "urn:uuid:11111111-1111-1111-1111-111111111111",
    "version": 1,
    "metadata": {"timestamp": "2026-07-14T10:00:00Z", "component": {"name": "demo-app", "type": "application"}},
    "vulnerabilities": [
        {
            "id": "CVE-2026-0001",
            "analysis": {"state": "NOT_AFFECTED", "justification": "CODE_NOT_REACHABLE"},
        }
    ],
}

UNTRIAGED_VEX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "vulnerabilities": [
        {"id": "CVE-2026-0002"},
        {"id": "CVE-2026-0003", "analysis": {"state": "IN_TRIAGE"}},
    ],
}


def _component_with_sbom(team) -> tuple[Component, SBOM]:
    component = Component.objects.create(name="dt-sync-c", team=team)
    sbom = SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )
    return component, sbom


def _version_row(sbom: SBOM) -> SimpleNamespace:
    return SimpleNamespace(dt_project_version_uuid="11111111-2222-3333-4444-555555555555", sbom=sbom)


@pytest.mark.django_db
class TestTriageVexSync:
    def _run_sync(self, sbom: SBOM, vex_doc: dict) -> MagicMock:
        plugin = DependencyTrackPlugin()
        client = MagicMock()
        client.get_project_vex.return_value = json.dumps(vex_doc).encode()
        with (
            patch("sbomify.apps.core.object_store.S3Client") as s3_cls,
            patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply") as reapply,
        ):
            s3 = s3_cls.return_value
            s3.upload_sbom.side_effect = lambda payload: "hash-of-payload.json"
            s3.get_sbom_data.side_effect = lambda name: json.dumps(TRIAGED_VEX).encode()
            plugin._sync_triage_vex(client, _version_row(sbom))
        return reapply

    def test_sync_is_off_by_default(self, sample_team_with_owner_member):
        """The hosted DT is a scanner backend, not a VEX source: without the
        sync_triage_vex config flag, no scan ever reads analysis decisions."""
        _, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        plugin = DependencyTrackPlugin()
        client = MagicMock()

        plugin._sync_triage_vex_safely(client, _version_row(sbom))

        client.get_project_vex.assert_not_called()

    def test_permission_403_logs_one_line_without_traceback(self, sample_team_with_owner_member, mocker):
        """With the sync enabled, a missing VULNERABILITY_ANALYSIS permission
        repeats identically on every scan — one actionable line, no traceback
        spam, scan unaffected."""
        from sbomify.apps.plugins.builtins import dependency_track as dt_module
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

        _, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        plugin = DependencyTrackPlugin({"sync_triage_vex": True})
        client = MagicMock()
        client.get_project_vex.side_effect = DependencyTrackAPIError("DT API request failed (403):", status_code=403)
        warn = mocker.patch.object(dt_module.logger, "warning")

        plugin._sync_triage_vex_safely(client, _version_row(sbom))

        assert warn.call_count == 1
        args, kwargs = warn.call_args
        assert "VULNERABILITY_ANALYSIS" in args[0]
        assert "exc_info" not in kwargs

    def test_unexpected_sync_error_keeps_traceback(self, sample_team_with_owner_member, mocker):
        from sbomify.apps.plugins.builtins import dependency_track as dt_module
        from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

        _, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        plugin = DependencyTrackPlugin({"sync_triage_vex": True})
        client = MagicMock()
        client.get_project_vex.side_effect = DependencyTrackAPIError("boom", status_code=500)
        warn = mocker.patch.object(dt_module.logger, "warning")

        plugin._sync_triage_vex_safely(client, _version_row(sbom))

        assert warn.call_count == 1
        assert warn.call_args.kwargs.get("exc_info") is True

    def test_triaged_export_creates_vex_artifact(self, sample_team_with_owner_member):
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)

        reapply = self._run_sync(sbom, TRIAGED_VEX)

        vex = SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value).first()
        assert vex is not None
        assert vex.source == "dependency-track"
        assert vex.name == "demo-app"
        assert vex.sbom_filename == "hash-of-payload.json"
        reapply.assert_called_once_with(str(component.id))

    def test_untriaged_export_creates_nothing(self, sample_team_with_owner_member):
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)

        reapply = self._run_sync(sbom, UNTRIAGED_VEX)

        assert not SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value).exists()
        reapply.assert_not_called()

    def test_identical_content_dedups_despite_volatile_fields(self, sample_team_with_owner_member):
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="demo-app",
            version="dt-triage-0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="existing-vex.json",
        )

        # Same statements, different serialNumber/timestamp/doc-version — the
        # shape every fresh DT export has.
        fresh = json.loads(json.dumps(TRIAGED_VEX))
        fresh["serialNumber"] = "urn:uuid:99999999-9999-9999-9999-999999999999"
        fresh["version"] = 7
        fresh["metadata"]["timestamp"] = "2026-07-14T11:00:00Z"

        reapply = self._run_sync(sbom, fresh)

        assert SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value).count() == 1
        reapply.assert_not_called()


@pytest.mark.django_db
class TestReleaseVexAutopin:
    def test_pinning_sbom_artifact_auto_pins_latest_vex(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        vex = SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="v1",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="v.json",
        )
        from sbomify.apps.core.models import Product

        product = Product.objects.create(name="dt-sync-p", team=team)
        release = Release.objects.create(product=product, name="r1")

        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        pinned = release.artifacts.filter(sbom__bom_type=SBOM.BomType.VEX.value)
        assert list(pinned.values_list("sbom_id", flat=True)) == [vex.id]

    def test_refresh_repoints_pins_to_newest_vex(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        old_vex = SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="v1",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="v1.json",
        )
        from sbomify.apps.core.models import Product

        product = Product.objects.create(name="dt-sync-p2", team=team)
        release = Release.objects.create(product=product, name="r1")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        assert release.artifacts.filter(sbom=old_vex).exists()

        new_vex = SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="v2",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="v2.json",
        )

        changed = refresh_vex_pins_for_component(str(component.id))

        assert changed == 1
        vex_pins = release.artifacts.filter(sbom__bom_type=SBOM.BomType.VEX.value)
        assert list(vex_pins.values_list("sbom_id", flat=True)) == [new_vex.id]
        # slot semantics: the old pin is gone, not duplicated
        assert not release.artifacts.filter(sbom=old_vex).exists()

    def test_manual_pin_is_authoritative(self, sample_team_with_owner_member):
        """A hand-pinned VEX evicts the auto pin and survives newer VEX arrivals."""
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="v1",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="v1.json",
        )
        from sbomify.apps.core.models import Product

        product = Product.objects.create(name="dt-sync-p4", team=team)
        release = Release.objects.create(product=product, name="r1")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)  # auto-pins v1

        chosen_vex = SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="chosen",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="chosen.json",
        )
        ReleaseArtifact.objects.create(release=release, sbom=chosen_vex)  # manual pin

        vex_pins = release.artifacts.filter(sbom__bom_type=SBOM.BomType.VEX.value)
        assert list(vex_pins.values_list("sbom_id", flat=True)) == [chosen_vex.id]

        # An even newer VEX must NOT displace the manual pin.
        SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="app-vex",
            version="v3",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="v3.json",
        )
        assert refresh_vex_pins_for_component(str(component.id)) == 0
        assert list(vex_pins.values_list("sbom_id", flat=True)) == [chosen_vex.id]

    def test_component_without_vex_is_untouched(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        from sbomify.apps.core.models import Product

        product = Product.objects.create(name="dt-sync-p3", team=team)
        release = Release.objects.create(product=product, name="r1")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        assert not ensure_latest_vex_pinned(release, component)
        assert release.artifacts.count() == 1


@pytest.mark.django_db
def test_refresh_latest_artifacts_with_vex_component(sample_team_with_owner_member):
    """Bulk latest-release maintenance must not collide with the auto-pin signal.

    refresh_latest_artifacts adds the component's VEX slot itself (under
    suppressed collection signals); if the auto-pin signal ran mid-bulk it
    would create the same (release, sbom) row first and abort the transaction
    with a unique violation.
    """
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="bulk-refresh-c", team=team)
    SBOM.objects.create(
        name="app",
        version="1",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )
    SBOM.objects.create(
        name="app-vex",
        version="1",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="v.json",
        component=component,
        bom_type=SBOM.BomType.VEX.value,
    )
    from sbomify.apps.core.models import Product

    product = Product.objects.create(name="bulk-refresh-p", team=team)
    component.products.add(product)
    release = Release.get_or_create_latest_release(product)

    release.refresh_latest_artifacts()

    types = sorted(release.artifacts.values_list("sbom__bom_type", flat=True))
    assert "vex" in types and "sbom" in types
    # Maintenance-created pins are sbomify-managed: the VEX slot stays
    # re-pointable by refresh_vex_pins instead of reading as a manual snapshot.
    assert release.artifacts.filter(sbom__bom_type=SBOM.BomType.VEX.value, auto_pinned=True).exists()
