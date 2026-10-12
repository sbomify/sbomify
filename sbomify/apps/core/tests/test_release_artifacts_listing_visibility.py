"""The release artifact listing follows the release detail's visibility rule.

The release detail hides PRIVATE components' artifacts from anyone who cannot
manage the release. The artifact listing now does the same in ``existing`` mode,
and ``available`` mode, the release editor's picker, needs ``release:manage``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_release(team_with_business_plan):
    team = team_with_business_plan
    product = Product.objects.create(name="Public", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1")
    for visibility in (Component.Visibility.PUBLIC, Component.Visibility.GATED, Component.Visibility.PRIVATE):
        component = Component.objects.create(name=visibility, team=team, visibility=visibility)
        product.components.add(component)
        sbom = SBOM.objects.create(name=visibility, component=component, format="cyclonedx", format_version="1.6")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        document = Document.objects.create(name=visibility, component=component, document_type="attestation")
        ReleaseArtifact.objects.create(release=release, document=document)
    return release


def _url(release: Release, mode: str) -> str:
    return reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id}) + f"?mode={mode}&page_size=-1"


def _listed_component_names(response) -> set[str]:
    return {item["component_name"] for item in response.json()["items"]}


def test_anonymous_existing_listing_leaves_out_private_components(public_release):
    response = Client().get(_url(public_release, "existing"))

    assert response.status_code == 200
    assert _listed_component_names(response) == {Component.Visibility.PUBLIC, Component.Visibility.GATED}


def test_manager_existing_listing_shows_every_component(public_release, authenticated_web_client):
    response = authenticated_web_client.get(_url(public_release, "existing"))

    assert response.status_code == 200
    assert _listed_component_names(response) == {
        Component.Visibility.PUBLIC,
        Component.Visibility.GATED,
        Component.Visibility.PRIVATE,
    }


def test_anonymous_available_listing_is_refused(public_release):
    response = Client().get(_url(public_release, "available"))

    assert response.status_code == 403


def test_manager_available_listing_still_works(public_release, authenticated_web_client):
    response = authenticated_web_client.get(_url(public_release, "available"))

    assert response.status_code == 200


LISTABLE_ROWS = {
    (kind, visibility)
    for kind in ("sbom", "document")
    for visibility in (Component.Visibility.PUBLIC, Component.Visibility.GATED)
}


def _token_client(user, team, scopes) -> Client:
    encoded = create_personal_access_token(user)
    AccessToken.objects.create(user=user, encoded_token=encoded, description="listing", team=team, scopes=scopes)
    return Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")


def _guest_session(team, owner) -> Client:
    guest = get_user_model().objects.create_user(username="listing-guest", email="listing-guest@example.com")
    Member.objects.create(team=team, user=guest, role="guest")
    client = Client()
    setup_authenticated_client_session(client, team, guest)
    return client


def _outsider_session(team, owner) -> Client:
    client = Client()
    client.force_login(get_user_model().objects.create_user(username="listing-out", email="listing-out@example.com"))
    return client


def _read_only_token(team, owner) -> Client:
    return _token_client(owner, team, SCOPE_PRESETS["read_only"])


def _publish_token(team, owner) -> Client:
    return _token_client(owner, team, SCOPE_PRESETS["publish"])


NON_MANAGERS = {
    "anonymous": lambda team, owner: Client(),
    "guest_session": _guest_session,
    "outsider_session": _outsider_session,
    "read_only_token": _read_only_token,
    "publish_token": _publish_token,
}


@pytest.mark.parametrize("caller", NON_MANAGERS)
def test_non_manager_lists_public_and_gated_sboms_and_documents(public_release, sample_user, caller):
    client = NON_MANAGERS[caller](public_release.product.team, sample_user)

    response = client.get(_url(public_release, "existing"))

    assert response.status_code == 200
    assert {(item["artifact_type"], item["component_name"]) for item in response.json()["items"]} == LISTABLE_ROWS
    assert response.json()["pagination"]["total"] == len(LISTABLE_ROWS)


@pytest.mark.parametrize("caller", NON_MANAGERS)
def test_non_manager_available_listing_is_refused(public_release, sample_user, caller):
    client = NON_MANAGERS[caller](public_release.product.team, sample_user)

    assert client.get(_url(public_release, "available")).status_code == 403
