"""DT triage → VEX sync, and pinning the VEX written for a release's version."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.core.models import Component, Release, ReleaseArtifact
from sbomify.apps.core.services.vex_pins import refresh_vex_pins_for_component, sync_vex_pins
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
            patch("sbomify.apps.core.object_store.StorageClient") as s3_cls,
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
        # Stored under the version of the SBOM the DT project holds, so it
        # applies to that version's scans and to no other.
        assert vex.version == sbom.version
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
            version=sbom.version,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="existing-vex.json",
            source="dependency-track",
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

    def test_the_same_triage_for_another_version_is_stored_for_that_version(self, sample_team_with_owner_member):
        """Dedup is per version: identical statements on a new version still need a VEX of their own."""
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="demo-app",
            version="0.9.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="existing-vex.json",
            source="dependency-track",
        )

        reapply = self._run_sync(sbom, TRIAGED_VEX)

        versions = set(
            SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value).values_list("version", flat=True)
        )
        assert versions == {"0.9.0", sbom.version}
        reapply.assert_called_once_with(str(component.id))


def _vex(component: Component, version: str, filename: str) -> SBOM:
    return SBOM.objects.create(
        component=component,
        bom_type=SBOM.BomType.VEX.value,
        name="app-vex",
        version=version,
        format="cyclonedx",
        format_version="1.5",
        sbom_filename=filename,
    )


def _release(team, name: str) -> Release:
    from sbomify.apps.core.models import Product

    product = Product.objects.create(name=name, team=team)
    return Release.objects.create(product=product, name="r1")


def _vex_pins(release: Release) -> list[str]:
    return list(release.artifacts.filter(sbom__bom_type=SBOM.BomType.VEX.value).values_list("sbom_id", flat=True))


@pytest.mark.django_db
class TestReleaseVexAutopin:
    def test_pinning_sbom_artifact_pins_the_vex_written_for_its_version(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        # "v1.0.0" and "1.0.0" are one version.
        vex = _vex(component, "v1.0.0", "v.json")
        release = _release(team, "dt-sync-p")

        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        assert _vex_pins(release) == [vex.id]

    def test_a_vex_for_another_version_is_never_pinned(self, sample_team_with_owner_member):
        """A newer release must not inherit statements verified against an older build."""
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        _vex(component, "0.9.0", "old.json")
        release = _release(team, "dt-sync-other")

        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        assert _vex_pins(release) == []

    def test_refresh_repoints_pins_to_the_newest_vex_for_the_version(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        old_vex = _vex(component, "1.0.0", "v1.json")
        release = _release(team, "dt-sync-p2")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        assert _vex_pins(release) == [old_vex.id]

        new_vex = _vex(component, "1.0.0", "v1-reissued.json")
        _vex(component, "2.0.0", "v2.json")

        changed = refresh_vex_pins_for_component(str(component.id))

        assert changed == 1
        # slot semantics: the old pin is gone, not duplicated, and the VEX for
        # the newer version stays out of this release
        assert _vex_pins(release) == [new_vex.id]

    def test_an_sbom_leaving_the_release_takes_its_vex_with_it(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        _vex(component, "1.0.0", "v1.json")
        release = _release(team, "dt-sync-leave")
        shipped = ReleaseArtifact.objects.create(release=release, sbom=sbom)

        shipped.delete()

        assert _vex_pins(release) == []

    def test_manual_pin_is_authoritative(self, sample_team_with_owner_member):
        """A hand-pinned VEX evicts the auto pin and survives newer VEX arrivals."""
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        _vex(component, "1.0.0", "v1.json")
        release = _release(team, "dt-sync-p4")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)  # auto-pins the 1.0.0 VEX

        chosen_vex = _vex(component, "chosen", "chosen.json")
        ReleaseArtifact.objects.create(release=release, sbom=chosen_vex)  # manual pin

        assert _vex_pins(release) == [chosen_vex.id]

        # An even newer VEX for the shipped version must NOT displace the manual pin.
        _vex(component, "1.0.0", "v1-reissued.json")
        assert refresh_vex_pins_for_component(str(component.id)) == 0
        assert _vex_pins(release) == [chosen_vex.id]

    def test_component_without_vex_is_untouched(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        component, sbom = _component_with_sbom(team)
        release = _release(team, "dt-sync-p3")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        assert not sync_vex_pins(release, component)
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


@pytest.mark.django_db
def test_the_latest_release_never_carries_a_vex_for_an_older_version(sample_team_with_owner_member):
    """The latest release ships the newest SBOM, so a VEX for an earlier version stays out of it."""
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="latest-old-vex-c", team=team)
    from sbomify.apps.core.models import Product

    product = Product.objects.create(name="latest-old-vex-p", team=team)
    component.products.add(product)
    SBOM.objects.create(
        name="app-vex",
        version="1",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="v.json",
        component=component,
        bom_type=SBOM.BomType.VEX.value,
    )
    SBOM.objects.create(
        name="app",
        version="2",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a2.json",
        component=component,
    )
    release = Release.get_or_create_latest_release(product)

    release.refresh_latest_artifacts()
    assert _vex_pins(release) == []

    # The VEX for the shipped version arrives and lands on the latest release.
    current = SBOM.objects.create(
        name="app-vex",
        version="2",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="v2.json",
        component=component,
        bom_type=SBOM.BomType.VEX.value,
    )
    assert _vex_pins(release) == [current.id]

    # A newer SBOM version leaves that VEX behind.
    SBOM.objects.create(
        name="app",
        version="3",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a3.json",
        component=component,
    )
    assert _vex_pins(release) == []
