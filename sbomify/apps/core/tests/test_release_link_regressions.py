"""Linked release downloads, public navigation and concurrent graph writes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from django.db import close_old_connections, connection
from django.test import Client, RequestFactory
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component, Product, Release, ReleaseLink
from sbomify.apps.core.services import release_links
from sbomify.apps.core.tests import test_release_links, test_slug_urls
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.core.url_utils import resolve_product_identifier
from sbomify.apps.teams.models import Workspace

app = test_release_links.app
toolchain = test_release_links.toolchain
custom_domain_team = test_slug_urls.custom_domain_team
clear_cache = test_slug_urls.clear_cache
setup_app_base_url = test_slug_urls.setup_app_base_url

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("signed_in", [False, True])
@pytest.mark.parametrize("hidden", [None, "product", "component"])
def test_download_checks_accessible_linked_members(
    authenticated_api_client: Any,
    app: Release,
    toolchain: Release,
    mocker: MockerFixture,
    tmp_path: Path,
    signed_in: bool,
    hidden: str | None,
) -> None:
    if hidden == "product":
        toolchain.product.is_public = False
        toolchain.product.save(update_fields=["is_public"])
    visibility = Component.Visibility.PRIVATE if hidden == "component" else Component.Visibility.PUBLIC
    test_release_links._sbom(toolchain, "bundle", visibility=visibility)
    ReleaseLink.objects.create(release=app, linked_release=toolchain)
    assert not app.artifacts.exists()
    package = tmp_path / "aggregate.json"
    package.write_text("{}")
    build = mocker.patch("sbomify.apps.core.apis.get_release_sbom_package", return_value=package)
    client, token = authenticated_api_client

    response = (
        client.get(f"/api/v1/releases/{app.id}/download", **get_api_headers(token))
        if signed_in
        else Client().get(f"/api/v1/releases/{app.id}/download")
    )

    accessible = signed_in or hidden is None
    assert response.status_code == (200 if accessible else 404), response.content
    assert build.called is accessible


@pytest.mark.parametrize("case", ["unique", "collision", "empty"])
def test_ships_with_url_resolves_to_the_linked_release(
    client: Client, custom_domain_team: Workspace, case: str
) -> None:
    team = custom_domain_team
    product = Product.objects.create(name="Toolchain", team=team, is_public=True)
    if case == "collision":
        collision = Product.objects.create(name="Toolchain!", team=team, is_public=True)
        request: Any = RequestFactory().get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team
        owner = resolve_product_identifier(request, product.slug, require_public=True)
        assert owner is not None
        product = collision if owner.id == product.id else product
        Release.objects.create(product=owner, name="v1")
    elif case == "empty":
        product = Product.objects.create(name="!!!", team=team, is_public=True)
    target = Release.objects.create(product=product, name="v1")
    source = test_release_links._release(team, "Application")
    ReleaseLink.objects.create(release=source, linked_release=target)

    page = client.get(f"/product/{source.product_id}/release/{source.id}/", HTTP_HOST="trust.example.com")

    assert page.status_code == 200
    path = page.context["linked_releases"][0]["url"]
    destination = client.get(path, HTTP_HOST="trust.example.com")
    assert destination.status_code == 200
    assert destination.context["release"]["id"] == target.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("long_cycle", [False, True])
def test_concurrent_links_cannot_complete_a_cycle(mocker: MockerFixture, long_cycle: bool) -> None:
    team = Workspace.objects.create(name="Example")
    a, b, c, d = [test_release_links._release(team, name) for name in ("A", "B", "C", "D")]
    if long_cycle:
        ReleaseLink.objects.create(release=b, linked_release=c)
        ReleaseLink.objects.create(release=d, linked_release=a)
    source2, target2 = (c, d) if long_cycle else (b, a)
    first_checked, second_started = Event(), Event()
    reaches = release_links._reaches

    def check(start: Release, target: Release) -> bool:
        result = reaches(start, target)
        if target.id == a.id:
            first_checked.set()
            assert second_started.wait(10)
        else:
            second_started.set()
        return result

    mocker.patch.object(release_links, "_reaches", side_effect=check)

    def observe_lock(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        # Let the first transaction commit once the second is attempting
        # the workspace lock. Without the lock, check() above releases it
        # only after both requests have observed an acyclic graph.
        if "FOR UPDATE" in sql and Workspace._meta.db_table in sql:
            second_started.set()
        return execute(sql, params, many, context)

    def link(source_id: str, target_id: str, *, second: bool = False) -> Any:
        close_old_connections()
        try:
            source = Release.objects.select_related("product").get(pk=source_id)
            target = Release.objects.select_related("product").get(pk=target_id)
            if second:
                with connection.execute_wrapper(observe_lock):
                    return release_links.link_release(source, target)
            return release_links.link_release(source, target)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(link, a.id, b.id)
        assert first_checked.wait(10)
        second = pool.submit(link, source2.id, target2.id, second=True)
        results = [first.result(timeout=15), second.result(timeout=15)]

    assert results[0].ok
    assert not results[1].ok
    assert results[1].status_code == 400
    assert ReleaseLink.objects.filter(release=a, linked_release=b).exists()
    assert not ReleaseLink.objects.filter(release=source2, linked_release=target2).exists()
