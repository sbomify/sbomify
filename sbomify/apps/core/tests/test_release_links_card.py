"""The "Ships with" card: link and unlink other products' releases from the release page."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product, Release, ReleaseLink
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member, Workspace

pytestmark = pytest.mark.django_db


def _release(team: Workspace, product_name: str, version: str) -> Release:
    product = Product.objects.create(name=product_name, team=team)
    return Release.objects.create(product=product, name=version, version=version)


@pytest.fixture
def app(team_with_business_plan) -> Release:
    return _release(team_with_business_plan, "Application", "v2.0.0")


@pytest.fixture
def toolchain(team_with_business_plan) -> Release:
    return _release(team_with_business_plan, "Toolchain", "26.10.3")


@pytest.fixture
def client(team_with_business_plan, sample_user) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    return client


def _url(release: Release) -> str:
    return reverse("core:release_links", args=[release.product_id, release.id])


def _post(client: Client, release: Release, action: str, linked: Release):
    return client.post(_url(release), {"action": action, "linked_release_id": linked.id}, HTTP_HX_REQUEST="true")


def test_a_direct_read_is_a_404_and_an_htmx_read_renders(client, app):
    assert client.get(_url(app)).status_code == 404
    response = client.get(_url(app), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert "Ships with" in response.content.decode()


def test_the_add_dialog_offers_other_products_releases_only(client, app, toolchain):
    sibling = Release.objects.create(product=app.product, name="v1.0.0", version="v1.0.0")
    html = client.get(_url(app), HTTP_HX_REQUEST="true").content.decode()

    assert f'value="{toolchain.id}"' in html
    assert 'label="Toolchain"' in html
    assert f'value="{sibling.id}"' not in html


def test_adding_links_the_release(client, app, toolchain):
    response = _post(client, app, "add", toolchain)

    assert response.status_code == 200
    assert ReleaseLink.objects.filter(release=app, linked_release=toolchain).exists()
    html = response.content.decode()
    assert reverse("core:release_details", args=[toolchain.product_id, toolchain.id]) in html
    assert f'value="{toolchain.id}"' not in html, "a linked release is no longer offered"


def test_removing_unlinks_the_release(client, app, toolchain):
    ReleaseLink.objects.create(release=app, linked_release=toolchain)

    assert _post(client, app, "remove", toolchain).status_code == 200
    assert not ReleaseLink.objects.filter(release=app).exists()


def test_a_refused_link_reports_why(client, app, toolchain):
    ReleaseLink.objects.create(release=toolchain, linked_release=app)

    response = _post(client, app, "add", toolchain)

    assert "links back" in response.headers.get("HX-Trigger", "")
    assert not ReleaseLink.objects.filter(release=app).exists()


def test_a_reader_who_cannot_manage_gets_no_controls(app, toolchain, guest_user, team_with_business_plan):
    Member.objects.create(team=team_with_business_plan, user=guest_user, role="operator")
    ReleaseLink.objects.create(release=app, linked_release=toolchain)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, guest_user)

    html = client.get(_url(app), HTTP_HX_REQUEST="true").content.decode()
    assert "Toolchain" in html
    assert "Add release" not in html

    _post(client, app, "remove", toolchain)
    assert ReleaseLink.objects.filter(release=app).exists()


def test_the_release_page_shows_the_card_to_a_manager(client, app):
    html = client.get(reverse("core:release_details", args=[app.product_id, app.id])).content.decode()
    assert 'id="release-links-card"' in html
    assert "Add release" in html


def test_the_latest_release_takes_no_links(client, app, toolchain):
    latest = Release.objects.create(product=app.product, name="latest", is_latest=True)
    html = client.get(_url(latest), HTTP_HX_REQUEST="true").content.decode()
    assert "Add release" not in html
