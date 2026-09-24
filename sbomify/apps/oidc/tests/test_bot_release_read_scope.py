"""An OIDC bot reads release contents only on products that hold its bound component.

The bot keeps ``release:read`` because the publish workflow lists releases to see
whether one already exists, and that grant covers the whole workspace. The
endpoints that hand over what a release contains (the SBOM, VEX and CBOM
downloads and the artifact listing) also confine the bot to the products its
binding publishes to, the rule ``create_release`` already applies.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


@pytest.fixture
def bound_component(team_with_business_plan) -> Component:
    return Component.objects.create(name="Bound", team=team_with_business_plan)


@pytest.fixture
def bot_token(bound_component, sample_user, github_claims_factory, mock_github_jwks) -> str:
    """A GitHub OIDC token exchanged against a binding on ``bound_component``."""
    placeholder = get_user_model().objects.create_user(username="placeholder-read-scope", password="x")
    binding = OIDCBinding.objects.create(
        component=bound_component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository="acme/widget",
        repository_id=12345,
        repository_owner_id=67890,
        bot_user=placeholder,
        created_by=sample_user,
    )
    binding.bot_user = provision_bot_user_for_binding(binding)
    binding.save(update_fields=["bot_user"])

    response = Client().post(
        "/api/v1/auth/oidc/github/exchange",
        data=json.dumps({"component_id": bound_component.id}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {github_claims_factory()}",
    )
    assert response.status_code == 200, response.content
    return response.json()["access_token"]


def _release(component: Component, *, is_public: bool) -> Release:
    product = Product.objects.create(name=f"{component.name}-{is_public}", team=component.team, is_public=is_public)
    product.components.add(component)
    release = Release.objects.create(product=product, name="v1")
    sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return release


@pytest.fixture
def own_release(bound_component) -> Release:
    return _release(bound_component, is_public=False)


@pytest.fixture
def other_component(team_with_business_plan) -> Component:
    return Component.objects.create(name="Other", team=team_with_business_plan)


@pytest.fixture
def other_release(other_component) -> Release:
    return _release(other_component, is_public=False)


@pytest.fixture
def public_other_release(other_component) -> Release:
    return _release(other_component, is_public=True)


@pytest.fixture
def builders(mocker, tmp_path) -> dict:
    """Stand-ins for the aggregate builders, which read artifacts from S3.

    The tests only need to see whether a download is served, and for which audience it was built.
    """
    cache.clear()
    package = tmp_path / "release.cdx.json"
    package.write_text("{}")
    return {
        "sbom": mocker.patch("sbomify.apps.core.apis.get_release_sbom_package", return_value=package),
        "vex": mocker.patch("sbomify.apps.vulnerability_scanning.vex.build_release_vex", return_value={"a": 1}),
        "cbom": mocker.patch("sbomify.apps.core.apis._release_cbom_document", return_value={"a": 1}),
    }


def _get(url: str, token: str):
    return Client().get(url, HTTP_AUTHORIZATION=f"Bearer {token}")


# Every release endpoint that serves what the release contains, relative to /api/v1/releases/<id>/.
CONTENT_PATHS = ("download", "vex/download", "cbom/download", "artifacts?mode=existing")


@pytest.mark.parametrize("path", CONTENT_PATHS)
def test_bot_cannot_read_a_private_product_it_does_not_publish_to(path, bot_token, other_release, builders):
    assert _get(f"/api/v1/releases/{other_release.id}/{path}", bot_token).status_code == 403


def test_bot_gets_the_public_view_of_a_public_product_it_does_not_publish_to(bot_token, public_other_release, builders):
    for path in CONTENT_PATHS:
        assert _get(f"/api/v1/releases/{public_other_release.id}/{path}", bot_token).status_code == 200, path
    assert builders["sbom"].call_args.kwargs["include_non_public"] is False
    assert builders["vex"].call_args.kwargs["include_non_public"] is False


def test_bot_reads_the_whole_release_of_a_product_holding_its_component(bot_token, own_release, builders):
    for path in CONTENT_PATHS:
        assert _get(f"/api/v1/releases/{own_release.id}/{path}", bot_token).status_code == 200, path
    assert builders["sbom"].call_args.kwargs["include_non_public"] is True
    assert builders["vex"].call_args.kwargs["include_non_public"] is True


def test_bot_without_a_binding_is_denied_its_own_product(bot_token, own_release, builders, mocker):
    """Fail closed, as ``create_release`` does.

    Patched rather than deleting the binding: deleting it reaps the bot user, so the request would
    fail at authentication and never reach the check under test.
    """
    mocker.patch("sbomify.apps.oidc.permissions.bound_component_id_for_request", return_value=None)

    assert _get(f"/api/v1/releases/{own_release.id}/download", bot_token).status_code == 403


def test_bot_still_lists_releases_to_check_one_exists(bot_token, own_release):
    """The publish workflow's release-exists check, which the confinement must leave alone."""
    response = _get(f"/api/v1/releases?product_id={own_release.product_id}", bot_token)

    assert response.status_code == 200
    assert str(own_release.id) in {item["id"] for item in response.json()["items"]}
