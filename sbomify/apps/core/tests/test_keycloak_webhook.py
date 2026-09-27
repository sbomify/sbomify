"""The Keycloak webhook view outlived its URL, so it is deleted rather than left for someone to route."""

from collections.abc import Iterator

from django.urls import URLResolver, get_resolver

from sbomify.apps.core import views


def _view_names(resolver: URLResolver) -> Iterator[str]:
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            yield from _view_names(pattern)
        else:
            yield getattr(pattern.callback, "__name__", "")


def test_core_views_do_not_define_keycloak_webhook() -> None:
    assert not hasattr(views, "keycloak_webhook")


def test_no_route_resolves_to_keycloak_webhook() -> None:
    assert "keycloak_webhook" not in set(_view_names(get_resolver()))
