"""The health check path is one setting shared by Django, Caddy, compose and Helm."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import resolve

from sbomify.health_check_path import DEFAULT_HEALTH_CHECK_PATH, resolve_health_check_path


@pytest.mark.parametrize("value", [None, ""])
def test_unset_falls_back_to_default(value: str | None) -> None:
    assert resolve_health_check_path(value) == DEFAULT_HEALTH_CHECK_PATH == "/UuPha8mu/"


@pytest.mark.parametrize("value", ["/healthz/", "/Abc_12-x/"])
def test_valid_path_is_returned_verbatim(value: str) -> None:
    assert resolve_health_check_path(value) == value


@pytest.mark.parametrize(
    "value",
    ["healthz", "/healthz", "healthz/", "/a/b/", "//", "/he alth/", "/health.check/", "/x/*"],
)
def test_invalid_path_is_refused(value: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="HEALTH_CHECK_PATH"):
        resolve_health_check_path(value)


def test_health_check_url_is_served_under_setting() -> None:
    assert resolve(settings.HEALTH_CHECK_PATH).url_name is not None
