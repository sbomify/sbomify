"""Which servers a subscription may read, and how a typed server becomes a TEA 1.0 API base."""

from __future__ import annotations

import socket

import pytest
from django.test import override_settings
from libtea.models import TeaWellKnown

from sbomify.apps.core.domain.exceptions import ValidationError
from sbomify.apps.tea.services import remote

PUBLIC = "93.184.216.34"


@pytest.fixture
def dns(mocker):
    """Answer every lookup with the addresses in ``answers``."""
    answers = {"default": [PUBLIC]}

    def getaddrinfo(host, port, *args, **kwargs):
        addresses = answers.get(host, answers["default"])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses]

    mocker.patch("socket.getaddrinfo", side_effect=getaddrinfo)
    return answers


def test_a_public_https_server_is_allowed(dns):
    remote.check_address("https://tea.example.com/tea/v1.0.0")


@pytest.mark.parametrize(
    "url,addresses",
    [
        ("http://tea.example.com/tea/v1.0.0", [PUBLIC]),
        ("https://tea.example.com/", ["10.0.0.5"]),
        ("https://tea.example.com/", [PUBLIC, "127.0.0.1"]),
        ("https://metadata.google.internal/", [PUBLIC]),
        ("https://user:pass@tea.example.com/", [PUBLIC]),
    ],
)
def test_an_address_off_the_public_internet_is_refused(dns, url, addresses):
    dns["default"] = addresses

    with pytest.raises(ValidationError):
        remote.check_address(url)


@override_settings(TEA_SUBSCRIPTION_ALLOW_PRIVATE_HOSTS=True)
def test_development_allows_private_hosts_but_never_metadata_addresses(dns):
    dns["default"] = ["127.0.0.1"]
    remote.check_address("http://localhost:8000/tea/v1.0.0")

    dns["default"] = ["169.254.169.254"]
    with pytest.raises(ValidationError):
        remote.check_address("http://tea.internal/")


def test_a_versioned_base_must_be_tea_1(dns):
    with pytest.raises(ValidationError, match="TEA 0.4.0"):
        remote.connect("https://tea.example.com/tea/v0.4.0")
    with pytest.raises(ValidationError, match="with its version"):
        remote.connect("https://tea.example.com/tea")

    server = remote.connect("https://tea.example.com/tea/v1.0.0/")

    assert server == remote.RemoteServer("https://tea.example.com/tea/v1.0.0", "1.0.0")


def _well_known(url, *versions):
    return TeaWellKnown.model_validate({"schemaVersion": 1, "endpoints": [{"url": url, "versions": list(versions)}]})


def test_a_domain_that_only_speaks_0_4_0_is_refused(dns, mocker):
    mocker.patch.object(remote, "fetch_well_known", return_value=_well_known("https://tea.example.com/tea", "0.4.0"))

    with pytest.raises(ValidationError, match="speaks TEA 0.4.0"):
        remote.connect("tea.example.com")


def test_a_domain_resolves_to_its_advertised_1_0_endpoint(dns, mocker):
    mocker.patch.object(
        remote, "fetch_well_known", return_value=_well_known("https://api.example.com/tea", "1.0.0", "0.4.0")
    )

    assert remote.connect("tea.example.com") == remote.RemoteServer("https://api.example.com/tea/v1.0.0", "1.0.0")


def test_an_advertised_endpoint_on_a_private_address_is_refused(dns, mocker):
    dns["internal.example.com"] = ["10.1.2.3"]
    mocker.patch.object(
        remote, "fetch_well_known", return_value=_well_known("https://internal.example.com/tea", "1.0.0")
    )

    with pytest.raises(ValidationError, match="public internet"):
        remote.connect("tea.example.com")
