import json
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase

from sbomify.apps.core.apis import list_release_artifacts
from sbomify.apps.core.models import Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import (
    get_api_headers,
)
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Member, Workspace

User = get_user_model()


class TestReleaseArtifactsAPI(TestCase):
    """Test release artifacts API to ensure correct version field mapping."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

        # Create test team
        self.team = Workspace.objects.create(key="test-team", name="Test Team")

        # Create test product
        self.product = Product.objects.create(team=self.team, name="Test Product", is_public=True)

        # Create test release
        self.release = Release.objects.create(product=self.product, name="v1.0.0", description="Test release")

        # Create test component
        self.component = Component.objects.create(
            team=self.team,
            name="test-component",
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PUBLIC,
        )

        # Create test SBOM with different version and format_version
        self.sbom = SBOM.objects.create(
            name="test-sbom",
            version="sha256:abc123def456",  # Actual SBOM version
            format="cyclonedx",
            format_version="1.5",  # CDX format version
            component=self.component,
            source="test",
        )

        # Add SBOM to release as artifact
        self.release_artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

    def test_page_size_minus_one_returns_every_artifact_in_both_modes(self):
        """The table paginates client-side, so a clamped -1 would hide rows.

        The available branch does its own clamping rather than going through
        _paginate_queryset, so the two modes have to be checked separately.
        """
        # Available artifacts are drawn from the product's components, so the
        # component has to be attached or that list stays empty.
        self.product.components.add(self.component)
        extras = [
            SBOM.objects.create(
                name=f"extra-sbom-{index}",
                version=f"1.0.{index}",
                format="cyclonedx",
                format_version="1.6",
                component=self.component,
            )
            for index in range(4)
        ]
        # Two pinned, two not, so neither mode is trivially satisfied.
        for sbom in extras[:2]:
            ReleaseArtifact.objects.get_or_create(release=self.release, sbom=sbom)

        # The available listing is the release editor's picker and answers only
        # someone who can edit the release.
        editor = User.objects.create_user(username="release-editor", email="editor@example.com")
        Member.objects.create(team=self.team, user=editor, role="owner")
        client = Client()
        client.force_login(editor)

        for mode in ("existing", "available"):
            response = client.get(f"/api/v1/releases/{self.release.id}/artifacts?mode={mode}&page_size=-1")
            assert response.status_code == 200, mode
            payload = json.loads(response.content)
            assert payload["pagination"]["total"] > 1, f"{mode} fixture proves nothing"
            assert payload["pagination"]["page_size"] >= payload["pagination"]["total"], mode
            assert len(payload["items"]) == payload["pagination"]["total"], mode
            # Both modes have to report the same shape, or a client walking
            # pages gets a different contract depending on what it asked for.
            assert payload["pagination"]["page"] == 1, mode
            assert payload["pagination"]["total_pages"] == 1, mode
            assert payload["pagination"]["has_previous"] is False, mode

    def test_bom_type_survives_response_serialisation(self):
        """bom_type must reach the client through the response schema.

        Regression guard: the payload dicts carried bom_type but the Ninja
        response schemas silently stripped it, so VEX artifacts rendered as
        duplicate SBOMs. Goes through the full HTTP stack on purpose — calling
        the view function directly bypasses schema serialisation and cannot
        catch a stripped field.
        """
        vex = SBOM.objects.create(
            name="test-vex",
            version="v1",
            format="cyclonedx",
            format_version="1.6",
            component=self.component,
            bom_type=SBOM.BomType.VEX,
        )
        ReleaseArtifact.objects.create(release=self.release, sbom=vex)

        response = Client().get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing")
        assert response.status_code == 200
        by_name = {item["artifact_name"]: item for item in response.json()["items"]}
        assert by_name["test-vex"]["bom_type"] == "vex"
        assert by_name["test-sbom"]["bom_type"] == "sbom"

    def test_sbom_version_returns_actual_version_not_format_version(self):
        """Test that sbom_version returns actual version not format version."""
        # Clear existing artifacts from the release
        ReleaseArtifact.objects.filter(release=self.release).delete()

        # Create an SBOM with both format version and actual version
        sbom = SBOM.objects.create(
            name="test-sbom-unique",
            component=self.component,
            format="CycloneDX",
            format_version="1.4",  # This is the format version
            version="2.0.1",  # This is the actual version
        )

        # Create a release artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=sbom)

        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        # Call the API function directly
        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        # Should return a dict with items and pagination
        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)
        self.assertIn("pagination", response_data)
        self.assertEqual(len(response_data["items"]), 1)

        artifact = response_data["items"][0]
        self.assertEqual(artifact["sbom_version"], "2.0.1")  # Should be actual version, not format version
        self.assertEqual(artifact["sbom_format"], "CycloneDX")  # Format should still be available

    def test_empty_sbom_version_returns_empty_string(self):
        """Test that empty sbom version returns empty string."""
        # Clear existing artifacts from the release
        ReleaseArtifact.objects.filter(release=self.release).delete()

        # Create an SBOM with empty version
        sbom = SBOM.objects.create(
            name="test-sbom-empty",
            component=self.component,
            format="CycloneDX",
            format_version="1.4",
            version="",  # Empty version
        )

        # Create a release artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=sbom)

        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        # Should return a dict with items and pagination
        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)

        # Find the empty version artifact
        empty_artifact = None
        for artifact in response_data["items"]:
            if artifact["artifact_name"] == "test-sbom-empty":
                empty_artifact = artifact
                break

        self.assertIsNotNone(empty_artifact)
        self.assertEqual(empty_artifact["sbom_version"], "")  # Should be empty string for None version

    def test_component_slug_in_response(self):
        """Test that component_slug is included in release artifact response."""
        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)

        artifact = response_data["items"][0]
        # Component should have a slug (it's auto-generated from name)
        # Since we didn't specify slug in setUp, we expect it to be derived from name "test-component"
        # However, checking if the field exists is the key here
        self.assertIn("component_slug", artifact)
        # We can also check that it's a string given the component has a name
        # Depending on how logic works, it might be None if component has no slug,
        # but in our test we want to ensure the field is present.


@pytest.mark.django_db
class TestAddArtifactsToReleaseAPI:
    """Test the add_artifacts_to_release API endpoint with API token authentication.

    This tests the fix for the 403 Forbidden bug where API token-based access
    was incorrectly denied due to _get_user_team_id() returning the wrong team.
    Also tests 409 Conflict behavior for duplicate artifacts.
    """

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan: Workspace, sample_user: User) -> None:
        """Set up test data using shared fixtures."""
        self.team = team_with_business_plan
        self.user = sample_user

        # Create product
        self.product = Product.objects.create(name="Test Product", team=self.team, is_public=False)

        # Create release (not latest - we can add artifacts to non-latest releases)
        self.release = Release.objects.create(name="v1.0.0", product=self.product, is_latest=False, is_prerelease=False)

        # Create component
        self.component = Component.objects.create(
            name="Test Component", team=self.team, visibility=Component.Visibility.PRIVATE
        )

        # Create SBOM
        self.sbom = SBOM.objects.create(name="Test SBOM", component=self.component, format="cyclonedx", version="1.0.0")

    def test_add_artifact_with_api_token_succeeds(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact with API token authentication succeeds.

        This tests the fix for the access control bug where _get_user_team_id()
        was returning the wrong team for API token requests.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert data["artifact_type"] == "sbom"
        assert data["artifact_name"] == "Test SBOM"

        # Verify artifact was created
        assert ReleaseArtifact.objects.filter(release=self.release, sbom=self.sbom).exists()

    def test_pinning_an_artifact_broadcasts_to_the_workspace(
        self, authenticated_api_client: tuple[Client, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        """Open release views repaint on the broadcast instead of waiting for a reload."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        with (
            patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(
                f"/api/v1/releases/{self.release.id}/artifacts",
                data=json.dumps({"sbom_id": str(self.sbom.id)}),
                content_type="application/json",
                **headers,
            )

        assert response.status_code == 201
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.kwargs["message_type"] == "release_updated"
        assert mock_broadcast.call_args.kwargs["data"]["release_id"] == str(self.release.id)

    def test_unpinning_an_artifact_broadcasts_to_the_workspace(
        self, authenticated_api_client: tuple[Client, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)
        artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        with (
            patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.delete(
                f"/api/v1/releases/{self.release.id}/artifacts/{artifact.id}",
                **headers,
            )

        assert response.status_code == 204
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.kwargs["message_type"] == "release_updated"

    def test_add_duplicate_artifact_returns_409_conflict(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding a duplicate artifact returns 409 Conflict.

        This tests the RESTful behavior where trying to add an artifact
        that already exists in the release returns 409 Conflict.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add the artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        # Try to add the same artifact again
        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert "already in this release" in data["detail"]
        assert data["error_code"] == "DUPLICATE_ARTIFACT"

    def test_add_artifact_unauthenticated_returns_403(self) -> None:
        """Test that adding an artifact without authentication returns 403."""
        client = Client()

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_add_artifact_to_latest_release_returns_400(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact to a 'latest' release returns 400.

        Latest releases are auto-managed and cannot have artifacts added manually.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a latest release
        latest_release = Release.objects.create(
            name="latest", product=self.product, is_latest=True, is_prerelease=False
        )

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{latest_release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "latest" in data["detail"].lower()

    def test_add_artifact_from_different_team_returns_403(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact from a different team returns 403."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a different team with a component and SBOM
        other_team = Workspace.objects.create(name="Other Team")
        other_component = Component.objects.create(name="Other Component", team=other_team)
        other_sbom = SBOM.objects.create(
            name="Other SBOM", component=other_component, format="cyclonedx", version="1.0.0"
        )

        payload = {"sbom_id": str(other_sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        # Generic error to avoid information disclosure
        assert data["detail"] == "Access denied"

    def test_add_duplicate_document_returns_409_conflict(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding a duplicate document returns 409 Conflict.

        This tests the RESTful behavior for documents (same as SBOMs).
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a document
        document = Document.objects.create(
            name="Test Document",
            component=self.component,
            document_type="attestation",
            version="1.0.0",
        )

        # First, add the document to release
        ReleaseArtifact.objects.create(release=self.release, document=document)

        # Try to add the same document again
        payload = {"document_id": str(document.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert "already in this release" in data["detail"]
        assert data["error_code"] == "DUPLICATE_ARTIFACT"

    def test_remove_artifact_with_api_token_succeeds(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that removing an artifact with API token authentication succeeds.

        This tests that the access control fix also works for remove_artifact_from_release.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add artifact to release first
        artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        response = client.delete(
            f"/api/v1/releases/{self.release.id}/artifacts/{artifact.id}",
            **headers,
        )

        assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.content}"

        # Verify artifact was removed
        assert not ReleaseArtifact.objects.filter(id=artifact.id).exists()

    def test_remove_artifact_unauthenticated_returns_403(self) -> None:
        """Test that removing an artifact without authentication returns 403."""
        client = Client()

        # Add artifact to release first
        artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        response = client.delete(
            f"/api/v1/releases/{self.release.id}/artifacts/{artifact.id}",
        )

        assert response.status_code == 403

        # Verify artifact still exists
        assert ReleaseArtifact.objects.filter(id=artifact.id).exists()


@pytest.mark.django_db
class TestReplaceArtifactInRelease:
    """``replace: true`` on the add-artifact endpoint, through v1 and v2."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan: Workspace, sample_user: User) -> None:
        self.team = team_with_business_plan
        self.product = Product.objects.create(name="Replace Product", team=self.team)
        self.release = Release.objects.create(name="v1.0.0", product=self.product)
        self.component = Component.objects.create(name="Replace Component", team=self.team)
        self.old = SBOM.objects.create(name="old", component=self.component, format="cyclonedx", version="1.0.0")
        self.new = SBOM.objects.create(name="new", component=self.component, format="cyclonedx", version="2.0.0")
        ReleaseArtifact.objects.create(release=self.release, sbom=self.old)
        self.member = Member.objects.get(team=self.team, user=sample_user)

    def _add(self, client: Client, token: Any, payload: dict[str, Any], version: str = "v1") -> Any:
        return client.post(
            f"/api/{version}/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **get_api_headers(token),
        )

    @pytest.mark.parametrize("version", ["v1", "v2"])
    @pytest.mark.parametrize("with_other_artifact", [False, True])
    def test_replace_is_one_collection_update(
        self, authenticated_api_client: tuple[Client, Any], version: str, with_other_artifact: bool
    ) -> None:
        """A swap is one ARTIFACT_UPDATED, not a removal followed by an add."""
        client, token = authenticated_api_client
        if with_other_artifact:
            other = Component.objects.create(name="Other Component", team=self.team)
            ReleaseArtifact.objects.create(
                release=self.release,
                sbom=SBOM.objects.create(name="other", component=other, format="cyclonedx", version="1.0.0"),
            )
        before = Release.objects.get(pk=self.release.pk).collection_version

        response = self._add(client, token, {"sbom_id": self.new.id, "replace": True}, version)

        assert response.status_code == 201, response.content
        assert response.json()["replaced"] is True
        release = Release.objects.get(pk=self.release.pk)
        assert release.collection_version == before + 1
        assert release.collection_update_reason == Release.CollectionUpdateReason.ARTIFACT_UPDATED

    def test_replace_broadcasts_after_commit(
        self, authenticated_api_client: tuple[Client, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        client, token = authenticated_api_client

        with patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast:
            with django_capture_on_commit_callbacks(execute=False) as callbacks:
                response = self._add(client, token, {"sbom_id": self.new.id, "replace": True})
            assert response.status_code == 201
            mock_broadcast.assert_not_called()
            for callback in callbacks:
                callback()
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.kwargs["message_type"] == "release_updated"
        assert mock_broadcast.call_args.kwargs["data"]["release_id"] == str(self.release.id)

    def test_replace_with_nothing_to_replace_is_a_plain_add(self, authenticated_api_client: tuple[Client, Any]) -> None:
        client, token = authenticated_api_client
        ReleaseArtifact.objects.filter(release=self.release).delete()

        response = self._add(client, token, {"sbom_id": self.new.id, "replace": True})

        assert response.status_code == 201
        assert response.json()["replaced"] is False
        assert response.json()["replaced_artifact_name"] is None
        assert list(ReleaseArtifact.objects.filter(release=self.release).values_list("sbom_id", flat=True)) == [
            self.new.id
        ]

    def test_replace_never_evicts_another_bom_type(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """A CBOM in the same format sits beside the component's SBOM, it does not take its slot."""
        client, token = authenticated_api_client
        cbom = SBOM.objects.create(
            name="cbom", component=self.component, format="cyclonedx", version="1.0.0", bom_type=SBOM.BomType.CBOM
        )

        response = self._add(client, token, {"sbom_id": cbom.id, "replace": True})

        assert response.status_code == 201
        assert response.json()["replaced"] is False
        assert set(ReleaseArtifact.objects.filter(release=self.release).values_list("sbom_id", flat=True)) == {
            self.old.id,
            cbom.id,
        }

    def test_replace_same_artifact_is_still_a_conflict(self, authenticated_api_client: tuple[Client, Any]) -> None:
        client, token = authenticated_api_client

        response = self._add(client, token, {"sbom_id": self.old.id, "replace": True})

        assert response.status_code == 409

    @pytest.mark.parametrize("role,status", [("member", 201), ("operator", 403), ("guest", 403)])
    def test_replace_needs_the_publish_tier(
        self, authenticated_api_client: tuple[Client, Any], role: str, status: int
    ) -> None:
        client, token = authenticated_api_client
        self.member.role = role
        self.member.save(update_fields=["role"])

        response = self._add(client, token, {"sbom_id": self.new.id, "replace": True})

        assert response.status_code == status
        expected = self.new.id if status == 201 else self.old.id
        assert list(ReleaseArtifact.objects.filter(release=self.release).values_list("sbom_id", flat=True)) == [
            expected
        ]

    def test_replace_moves_the_vex_pin_to_the_new_version(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """The swap re-points the auto VEX pin at the version the release now ships, in the same one bump."""
        from sbomify.apps.core.services.vex_pins import sync_vex_pins

        client, token = authenticated_api_client
        vex_for = {
            version: SBOM.objects.create(
                name=f"vex-{version}",
                component=self.component,
                format="cyclonedx",
                version=version,
                bom_type=SBOM.BomType.VEX,
                source="manual_upload",
            )
            for version in ("1.0.0", "2.0.0")
        }
        sync_vex_pins(self.release, self.component)
        assert set(self.release.artifacts.filter(auto_pinned=True).values_list("sbom_id", flat=True)) == {
            vex_for["1.0.0"].id
        }
        before = Release.objects.get(pk=self.release.pk).collection_version

        response = self._add(client, token, {"sbom_id": self.new.id, "replace": True})

        assert response.status_code == 201
        assert set(self.release.artifacts.values_list("sbom_id", flat=True)) == {self.new.id, vex_for["2.0.0"].id}
        release = Release.objects.get(pk=self.release.pk)
        assert release.collection_version == before + 1
        assert release.collection_update_reason == Release.CollectionUpdateReason.ARTIFACT_UPDATED

    def test_tagging_an_sbom_into_a_release_replaces_as_one_update(
        self, authenticated_api_client: tuple[Client, Any]
    ) -> None:
        """POST /sboms/{id}/releases always replaces; it records the swap the same way."""
        client, token = authenticated_api_client
        before = Release.objects.get(pk=self.release.pk).collection_version

        response = client.post(
            f"/api/v1/sboms/{self.new.id}/releases",
            data=json.dumps({"release_ids": [self.release.id]}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 201, response.content
        release = Release.objects.get(pk=self.release.pk)
        assert release.collection_version == before + 1
        assert release.collection_update_reason == Release.CollectionUpdateReason.ARTIFACT_UPDATED

    def test_replacing_a_hand_pinned_vex_drops_the_auto_pins(
        self, authenticated_api_client: tuple[Client, Any]
    ) -> None:
        """A hand pin outranks sbomify's auto pins for the component, through a swap as through an add."""
        from sbomify.apps.core.models import _suppress_collection_signals

        client, token = authenticated_api_client

        def vex(name: str, artifact_format: str) -> SBOM:
            return SBOM.objects.create(
                name=name,
                component=self.component,
                format=artifact_format,
                version="1.0.0",
                bom_type=SBOM.BomType.VEX,
                source="manual_upload",
            )

        auto = vex("auto", "cyclonedx")
        hand = vex("hand", "openvex")
        signals_muted = _suppress_collection_signals.set(True)
        try:
            ReleaseArtifact.objects.create(release=self.release, sbom=auto, auto_pinned=True)
            ReleaseArtifact.objects.create(release=self.release, sbom=hand)
        finally:
            _suppress_collection_signals.reset(signals_muted)
        newer = vex("newer", "openvex")

        response = self._add(client, token, {"sbom_id": newer.id, "replace": True})

        assert response.status_code == 201
        assert response.json()["replaced_artifact_name"] == "hand"
        assert set(self.release.artifacts.values_list("sbom_id", flat=True)) == {self.old.id, newer.id}
