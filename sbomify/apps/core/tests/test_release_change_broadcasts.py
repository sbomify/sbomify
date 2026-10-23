"""Changes to a release's artifact set from outside the release page tell the workspace.

Release views repaint on ``release_updated``. Tagging an artifact from its own
page, sbomify maintaining the "latest" release on upload, and attaching a
component to a product all change a release's artifacts, so each sends it, and
only once the change is committed. A component metadata edit sends
``component_updated``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.db import transaction

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(team_with_business_plan: Workspace) -> dict[str, Any]:
    team = team_with_business_plan
    product = Product.objects.create(name="Tagged Product", team=team)
    component = Component.objects.create(name="Tagged Component", team=team)
    release = Release.objects.create(name="v1.0.0", product=product)
    other_release = Release.objects.create(name="v2.0.0", product=product)
    sbom = SBOM.objects.create(name="tagged-sbom", component=component, format="cyclonedx", version="1.0.0")
    document = Document.objects.create(name="tagged-doc", component=component, version="1.0.0")
    return {
        "team": team,
        "product": product,
        "component": component,
        "release": release,
        "other_release": other_release,
        "sbom": sbom,
        "document": document,
    }


def _release_updates(mock_broadcast: Any) -> list[dict[str, Any]]:
    return [
        call.kwargs["data"]
        for call in mock_broadcast.call_args_list
        if call.kwargs["message_type"] == "release_updated"
    ]


@pytest.mark.parametrize("kind", ["sboms", "documents"])
def test_tagging_an_artifact_into_releases_broadcasts_each_release(
    kind: str,
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client
    artifact = setup["sbom"] if kind == "sboms" else setup["document"]
    release_ids = [str(setup["release"].id), str(setup["other_release"].id)]

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post(
            f"/api/v1/{kind}/{artifact.id}/releases",
            data=json.dumps({"release_ids": release_ids}),
            content_type="application/json",
            **get_api_headers(token),
        )

    assert response.status_code == 201, response.content
    updates = _release_updates(mock_broadcast)
    assert sorted(update["release_id"] for update in updates) == sorted(release_ids)
    assert all(update["product_id"] == str(setup["product"].id) for update in updates)
    assert mock_broadcast.call_args.kwargs["workspace_key"] == setup["team"].key


@pytest.mark.parametrize("kind", ["sboms", "documents"])
def test_tagging_an_artifact_already_in_the_release_broadcasts_nothing(
    kind: str,
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client
    artifact = setup["sbom"] if kind == "sboms" else setup["document"]
    field = "sbom" if kind == "sboms" else "document"
    ReleaseArtifact.objects.create(release=setup["release"], **{field: artifact})

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post(
            f"/api/v1/{kind}/{artifact.id}/releases",
            data=json.dumps({"release_ids": [str(setup["release"].id)]}),
            content_type="application/json",
            **get_api_headers(token),
        )

    assert response.status_code == 400
    assert _release_updates(mock_broadcast) == []


@pytest.mark.parametrize("kind", ["sboms", "documents"])
def test_untagging_an_artifact_from_a_release_broadcasts_it(
    kind: str,
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client
    artifact = setup["sbom"] if kind == "sboms" else setup["document"]
    field = "sbom" if kind == "sboms" else "document"
    ReleaseArtifact.objects.create(release=setup["release"], **{field: artifact})

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.delete(
            f"/api/v1/{kind}/{artifact.id}/releases/{setup['release'].id}",
            **get_api_headers(token),
        )

    assert response.status_code == 204, response.content
    mock_broadcast.assert_called_once()
    assert _release_updates(mock_broadcast) == [
        {"release_id": str(setup["release"].id), "product_id": str(setup["product"].id), "name": "v1.0.0"}
    ]


@pytest.mark.parametrize("kind", ["sboms", "documents"])
def test_untagging_an_artifact_not_in_the_release_broadcasts_nothing(
    kind: str,
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client
    artifact = setup["sbom"] if kind == "sboms" else setup["document"]

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.delete(
            f"/api/v1/{kind}/{artifact.id}/releases/{setup['release'].id}",
            **get_api_headers(token),
        )

    assert response.status_code == 404
    mock_broadcast.assert_not_called()


class TestLatestReleaseMaintenance:
    """The signals that keep each product's "latest" release current broadcast it."""

    @pytest.fixture
    def attached(self, setup: dict[str, Any]) -> dict[str, Any]:
        setup["component"].products.add(setup["product"])
        return setup

    def test_a_new_sbom_broadcasts_the_latest_release_once(
        self, attached: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            SBOM.objects.create(name="next", component=attached["component"], format="cyclonedx", version="2.0.0")

        latest = Release.objects.get(product=attached["product"], is_latest=True)
        assert _release_updates(mock_broadcast) == [
            {"release_id": str(latest.id), "product_id": str(attached["product"].id), "name": latest.name}
        ]
        assert mock_broadcast.call_args.kwargs["workspace_key"] == attached["team"].key

    def test_a_new_document_broadcasts_the_latest_release(
        self, attached: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            Document.objects.create(name="next-doc", component=attached["component"], version="2.0.0")

        latest = Release.objects.get(product=attached["product"], is_latest=True)
        assert [update["release_id"] for update in _release_updates(mock_broadcast)] == [str(latest.id)]

    def test_several_uploads_in_one_transaction_all_name_the_latest_release(
        self, attached: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            with transaction.atomic():
                SBOM.objects.create(name="a", component=attached["component"], format="cyclonedx", version="2.0.0")
                SBOM.objects.create(name="b", component=attached["component"], format="spdx", version="2.0.0")
                Document.objects.create(name="c", component=attached["component"], version="2.0.0")

        # Pages debounce, so these repaint once; nothing is sent before the commit.
        latest = Release.objects.get(product=attached["product"], is_latest=True)
        updates = _release_updates(mock_broadcast)
        assert updates
        assert {update["release_id"] for update in updates} == {str(latest.id)}

    def test_a_rolled_back_upload_broadcasts_nothing_and_the_next_one_still_does(
        self, attached: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            try:
                with transaction.atomic():
                    SBOM.objects.create(name="a", component=attached["component"], format="cyclonedx", version="2")
                    raise RuntimeError("abort")
            except RuntimeError:
                pass
            SBOM.objects.create(name="b", component=attached["component"], format="cyclonedx", version="3")

        assert len(_release_updates(mock_broadcast)) == 1

    def test_an_artifact_outside_any_product_broadcasts_nothing(
        self, setup: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            SBOM.objects.create(name="loose", component=setup["component"], format="cyclonedx", version="2.0.0")

        assert _release_updates(mock_broadcast) == []

    def test_attaching_a_component_broadcasts_the_products_latest_release(
        self, setup: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        with (
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            setup["component"].products.add(setup["product"])

        latest = Release.objects.get(product=setup["product"], is_latest=True)
        assert [update["release_id"] for update in _release_updates(mock_broadcast)] == [str(latest.id)]

    def test_a_new_sbom_costs_no_query_per_product_for_the_broadcast(
        self, attached: dict[str, Any], django_capture_on_commit_callbacks: Any
    ) -> None:
        second = Product.objects.create(name="Second Product", team=attached["team"])
        attached["component"].products.add(second)
        SBOM.objects.create(name="warm", component=attached["component"], format="cyclonedx", version="1.5.0")

        def upload(version: str) -> int:
            with (
                patch("sbomify.apps.core.utils.broadcast_to_workspace"),
                django_capture_on_commit_callbacks(execute=True),
            ):
                from django.db import connection
                from django.test.utils import CaptureQueriesContext

                with CaptureQueriesContext(connection) as ctx:
                    SBOM.objects.create(name="n", component=attached["component"], format="cyclonedx", version=version)
            return len(ctx.captured_queries)

        baseline = upload("2.0.0")
        with patch("sbomify.apps.core.signals._schedule_latest_release_updated"):
            without_broadcast = upload("3.0.0")
        assert baseline == without_broadcast


def test_patching_component_metadata_broadcasts_component_updated(
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client
    component = setup["component"]

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.patch(
            f"/api/v1/components/{component.id}/metadata",
            data=json.dumps({"lifecycle_phase": "build"}),
            content_type="application/json",
            **get_api_headers(token),
        )

    assert response.status_code == 204, response.content
    mock_broadcast.assert_called_once()
    assert mock_broadcast.call_args.kwargs["workspace_key"] == setup["team"].key
    assert mock_broadcast.call_args.kwargs["message_type"] == "component_updated"
    assert mock_broadcast.call_args.kwargs["data"] == {"component_id": str(component.id), "name": component.name}


def test_a_rejected_component_metadata_patch_broadcasts_nothing(
    setup: dict[str, Any],
    authenticated_api_client: tuple[Any, Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, token = authenticated_api_client

    with (
        patch("sbomify.apps.core.apis.broadcast_to_workspace") as mock_broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.patch(
            f"/api/v1/components/{setup['component'].id}/metadata",
            data=json.dumps({"contact_profile_id": "missing"}),
            content_type="application/json",
            **get_api_headers(token),
        )

    assert response.status_code == 404
    mock_broadcast.assert_not_called()
