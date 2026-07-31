"""Artifact lifecycle PostHog events: VEX/CBOM/HBOM ship under their own names
instead of all reading as SBOM activity."""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


@pytest.fixture
def component(sample_team_with_owner_member):
    return Component.objects.create(
        name="analytics-component", team=sample_team_with_owner_member.team, component_type="bom"
    )


def _store_row(component: Component, bom_type: str, source: str, version: str) -> SBOM:
    return SBOM.objects.create(
        name="artifact",
        version=version,
        component=component,
        format="cyclonedx",
        format_version="1.6",
        source=source,
        sbom_filename=f"{bom_type}-{version}.json",
        bom_type=bom_type,
    )


class TestUploadEvents:
    @pytest.mark.parametrize(
        "bom_type,source,expected_event",
        [
            ("sbom", "api", "sbom:uploaded"),
            ("vex", "manual_upload", "vex:uploaded"),
            ("vex", "sbomify-triage", "vex:uploaded"),
            ("cbom", "api", "cbom:uploaded"),
            ("hbom", "api", "hbom:uploaded"),
        ],
    )
    def test_row_creation_fires_type_specific_event(
        self, component, mocker, django_capture_on_commit_callbacks, bom_type, source, expected_event
    ) -> None:
        capture = mocker.patch("sbomify.apps.core.posthog_service.capture")
        with django_capture_on_commit_callbacks(execute=True):
            row = _store_row(component, bom_type, source, "1.0.0")
        events_fired = [(call.args[1], call.args[2]) for call in capture.call_args_list]
        matching = [props for name, props in events_fired if name == expected_event]
        assert len(matching) == 1, events_fired
        assert matching[0]["sbom_id"] == row.id
        assert matching[0]["source"] == source
        # No cross-typed event fired for this row.
        other_names = {name for name, _ in events_fired} - {expected_event, "bom_artifact:first_uploaded"}
        assert not any(name.endswith(":uploaded") for name in other_names), events_fired


class TestDownloadEvents:
    def test_vex_download_ships_as_vex_event(self, component, sample_user, mocker) -> None:
        import json

        from django.test import Client

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        row = _store_row(component, "vex", "manual_upload", "1.0.0")
        mocker.patch(
            "sbomify.apps.core.object_store.S3Client.get_sbom_data",
            return_value=json.dumps({"bomFormat": "CycloneDX"}).encode(),
        )
        # The owner's session already grants access via check_component_access;
        # no access mock is needed.
        capture = mocker.patch("sbomify.apps.core.posthog_service.capture")
        mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)

        client = Client()
        setup_authenticated_client_session(client, component.team, sample_user)
        response = client.get(f"/sbom/download/{row.id}")
        assert response.status_code == 200
        names = [call.args[1] for call in capture.call_args_list]
        assert "vex:downloaded" in names
        assert "sbom:downloaded" not in names

    def test_download_filename_is_sanitized(self, component, sample_user, mocker) -> None:
        """A CR/LF-bearing artifact name cannot break or inject the
        Content-Disposition header."""
        import json

        from django.test import Client

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        row = _store_row(component, "sbom", "api", "1.0.0")
        row.name = "evil\r\nSet-Cookie: x=y.json"
        row.save(update_fields=["name"])
        mocker.patch(
            "sbomify.apps.core.object_store.S3Client.get_sbom_data",
            return_value=json.dumps({"bomFormat": "CycloneDX"}).encode(),
        )

        client = Client()
        setup_authenticated_client_session(client, component.team, sample_user)
        response = client.get(f"/sbom/download/{row.id}")
        assert response.status_code == 200
        disposition = response["Content-Disposition"]
        assert "\r" not in disposition and "\n" not in disposition
        assert "Set-Cookie" not in disposition or "evil-Set-Cookie" in disposition
        assert disposition.startswith('attachment; filename="')


class TestDeleteEvents:
    def test_vex_delete_fires_typed_event(
        self, component, sample_user, mocker, sample_team_with_owner_member, django_capture_on_commit_callbacks
    ) -> None:
        from django.test import Client

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        row = _store_row(component, "vex", "manual_upload", "1.0.0")
        mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object", return_value=None)
        mocker.patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply", return_value=None)
        capture_for_request = mocker.patch("sbomify.apps.core.posthog_service.capture_for_request")

        client = Client()
        setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
        # The delete event is deferred to transaction commit.
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(f"/component/{component.id}/vex/", {"_method": "DELETE", "sbom_id": row.id})
        assert response.status_code == 200, response.content
        names = [call.args[1] for call in capture_for_request.call_args_list]
        assert "vex:deleted" in names
        assert "sbom:deleted" not in names


class TestReleaseDownloadEvents:
    def test_release_sbom_download_captures_vendor_scoped_event(
        self, component, sample_user, mocker, sample_team_with_owner_member, tmp_path
    ) -> None:
        from django.test import Client

        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.sboms.models import ProductComponent

        team = sample_team_with_owner_member.team
        product = Product.objects.create(team=team, name="Analytics SBOM Product")
        ProductComponent.objects.create(product=product, component=component)
        release = Release.objects.create(product=product, name="v1")
        sbom_row = _store_row(component, "sbom", "api", "1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=sbom_row)

        merged = tmp_path / "merged.cdx.json"
        merged.write_text('{"bomFormat": "CycloneDX"}')
        mocker.patch("sbomify.apps.core.apis.get_release_sbom_package", return_value=merged)
        capture_for_request = mocker.patch("sbomify.apps.core.apis.capture_for_request")

        client = Client()
        setup_authenticated_client_session(client, team, sample_user)
        response = client.get(f"/api/v1/releases/{release.id}/download")
        assert response.status_code == 200, response.content
        assert capture_for_request.call_count == 1
        args, kwargs = capture_for_request.call_args
        assert args[1] == "release_sbom:downloaded"
        assert args[2]["format"] == "cyclonedx"
        assert kwargs["team_key"] == team.key

    def test_release_vex_download_captures_vendor_scoped_event(
        self, component, sample_user, mocker, sample_team_with_owner_member
    ) -> None:
        import json

        from django.test import Client

        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.sboms.models import ProductComponent

        team = sample_team_with_owner_member.team
        product = Product.objects.create(team=team, name="Analytics Product")
        ProductComponent.objects.create(product=product, component=component)
        release = Release.objects.create(product=product, name="v1")
        vex_row = _store_row(component, "vex", "manual_upload", "1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=vex_row)
        mocker.patch(
            "sbomify.apps.core.object_store.S3Client.get_sbom_data",
            return_value=json.dumps(
                {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "vulnerabilities": []}
            ).encode(),
        )
        capture_for_request = mocker.patch("sbomify.apps.core.apis.capture_for_request")

        client = Client()
        setup_authenticated_client_session(client, team, sample_user)
        response = client.get(f"/api/v1/releases/{release.id}/vex/download")
        assert response.status_code == 200, response.content
        assert capture_for_request.call_count == 1
        args, kwargs = capture_for_request.call_args
        assert args[1] == "release_vex:downloaded"
        assert args[2]["release_id"] == str(release.id)
        assert kwargs["team_key"] == team.key

    def test_release_cbom_download_captures_vendor_scoped_event(
        self, component, sample_user, mocker, sample_team_with_owner_member
    ) -> None:
        from django.test import Client

        from sbomify.apps.core.models import Product, Release, ReleaseArtifact
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.sboms.models import ProductComponent

        team = sample_team_with_owner_member.team
        product = Product.objects.create(team=team, name="Analytics CBOM Product")
        ProductComponent.objects.create(product=product, component=component)
        release = Release.objects.create(product=product, name="v1")
        cbom_row = _store_row(component, "cbom", "api", "1.0.0")
        ReleaseArtifact.objects.create(release=release, sbom=cbom_row)
        mocker.patch(
            "sbomify.apps.sboms.cbom.build_release_cbom",
            return_value={"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1},
        )
        capture_for_request = mocker.patch("sbomify.apps.core.apis.capture_for_request")

        client = Client()
        setup_authenticated_client_session(client, team, sample_user)
        response = client.get(f"/api/v1/releases/{release.id}/cbom/download")
        assert response.status_code == 200, response.content
        assert capture_for_request.call_count == 1
        args, kwargs = capture_for_request.call_args
        assert args[1] == "release_cbom:downloaded"
        assert args[2]["release_id"] == str(release.id)
        assert kwargs["team_key"] == team.key
