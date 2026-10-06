"""A fragment route answers htmx and gives a direct visit a 404, not bare markup."""

from typing import Any

import pytest
from django.http import Http404, HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.core.htmx import HtmxFragmentMixin
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session


class _Fragment(HtmxFragmentMixin):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return HttpResponse("fragment")

    post = delete = get


@pytest.mark.parametrize("method", ["get", "head"])
def test_a_direct_read_is_a_404(method: str) -> None:
    with pytest.raises(Http404):
        _Fragment.as_view()(getattr(RequestFactory(), method)("/fragment/"))


def test_an_htmx_read_renders_the_fragment() -> None:
    response = _Fragment.as_view()(RequestFactory().get("/fragment/", HTTP_HX_REQUEST="true"))
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["post", "delete"])
def test_writes_pass_through(method: str) -> None:
    response = _Fragment.as_view()(getattr(RequestFactory(), method)("/fragment/"))
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name,arg",
    [
        ("core:product_links", "product"),
        ("documents:documents_table", "component"),
        ("oidc:trusted_publishers", "component"),
        ("plugins:plugins_summary", None),
        ("sboms:sboms_table", "component"),
        ("teams:team_tokens", "team"),
    ],
)
def test_each_app_guards_its_fragments(url_name, arg, sample_user, sample_product, sample_component) -> None:
    team = sample_component.team
    client = Client()
    setup_authenticated_client_session(client, team, sample_user)
    kwargs = {
        None: {},
        "product": {"product_id": sample_product.id},
        "component": {"component_id": sample_component.id},
        "team": {"team_key": team.key},
    }[arg]
    url = reverse(url_name, kwargs=kwargs)

    assert client.get(url).status_code == 404
    assert client.get(url, HTTP_HX_REQUEST="true").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name,arg",
    [
        ("core:product_links", "product"),
        ("oidc:trusted_publishers", "component"),
        ("plugins:plugins_summary", None),
        ("teams:team_tokens", "team"),
    ],
)
def test_an_htmx_read_without_a_session_still_meets_the_login_gate(url_name, arg, sample_product, sample_component):
    """The guard runs before each view's own checks, so it may only ever add a
    404: an htmx read from someone signed out is still sent to sign in."""
    kwargs = {
        None: {},
        "product": {"product_id": sample_product.id},
        "component": {"component_id": sample_component.id},
        "team": {"team_key": sample_component.team.key},
    }[arg]

    response = Client().get(reverse(url_name, kwargs=kwargs), HTTP_HX_REQUEST="true")

    assert response.status_code == 302
    assert response["Location"].startswith("/login")
