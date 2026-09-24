"""A custom domain is verified by fetching this deployment's challenge from it.

The Host header of a request is whatever the client sent, so a request carrying
the domain proves nothing about where the domain's DNS points. Only the probe,
which fetches the domain through public DNS, can mark it verified.
"""

import gzip
import io
from urllib.parse import urlsplit

import pytest
import requests
import urllib3
from django.test import Client

from sbomify.apps.teams.models import Team
from sbomify.apps.teams.tasks import probe_custom_domain, verify_custom_domains
from sbomify.apps.teams.utils import custom_domain_challenge

DOMAIN = "trust.example.com"


@pytest.fixture
def claimed(db):
    return Team.objects.create(name="Claimant", billing_plan="business", custom_domain=DOMAIN)


def _response(status: int, body: bytes, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.raw = urllib3.HTTPResponse(body=io.BytesIO(body), headers=headers, status=status, preload_content=False)
    return response


def _routed_here(method: str, url: str, **kwargs) -> requests.Response:
    """What the probe receives when the domain's DNS points at this deployment."""
    parts = urlsplit(url)
    served = Client().get(parts.path, HTTP_HOST=parts.hostname, secure=True)
    return _response(served.status_code, served.content)


def _routed_here_compressed(method: str, url: str, **kwargs) -> requests.Response:
    """The same, through a proxy that compresses the answer."""
    served = _routed_here(method, url)
    return _response(served.status_code, gzip.compress(served.raw.read()), {"Content-Encoding": "gzip"})


def test_a_request_carrying_the_domain_does_not_verify_it(client, claimed):
    client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST=DOMAIN)
    client.get("/", HTTP_HOST=DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_a_request_on_the_domain_brings_the_next_probe_forward(client, claimed):
    Team.objects.filter(pk=claimed.pk).update(custom_domain_verification_failures=6)

    client.get("/", HTTP_HOST=DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_verification_failures == 0
    assert claimed.custom_domain_validated is False


def test_each_due_domain_is_counted_and_probed_in_its_own_message(claimed, mocker):
    send = mocker.patch.object(probe_custom_domain, "send")

    verify_custom_domains()

    send.assert_called_once_with(claimed.pk, DOMAIN)
    claimed.refresh_from_db()
    assert claimed.custom_domain_verification_failures == 1
    assert claimed.custom_domain_last_checked_at is not None


@pytest.mark.parametrize("routed", [_routed_here, _routed_here_compressed])
def test_the_probe_verifies_a_domain_that_serves_the_challenge(claimed, mocker, routed):
    Team.objects.filter(pk=claimed.pk).update(custom_domain_verification_failures=1)
    fetch = mocker.patch("sbomify.apps.teams.tasks.request_with_retry", side_effect=routed)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is True
    assert claimed.custom_domain_verification_failures == 0
    assert claimed.custom_domain_last_checked_at is not None
    # A redirect would let the answer come from somewhere other than the domain.
    assert fetch.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, b'{"ok": true, "service": "sbomify", "domain": "trust.example.com"}'),
        (200, b'{"challenge": "0000000000000000000000000000000000000000000000000000000000000000"}'),
        (200, b'["challenge"]'),
        (200, b"<html><body>Welcome</body></html>"),
        (302, b""),
        (404, b""),
    ],
)
def test_the_probe_rejects_a_domain_that_serves_anything_else(claimed, mocker, status, body):
    mocker.patch("sbomify.apps.teams.tasks.request_with_retry", return_value=_response(status, body))

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_the_probe_does_not_verify_a_domain_changed_while_it_ran(claimed, mocker):
    def fetch_then_change(method: str, url: str, **kwargs) -> requests.Response:
        response = _routed_here(method, url)
        Team.objects.filter(pk=claimed.pk).update(custom_domain="other.example.com")
        return response

    mocker.patch("sbomify.apps.teams.tasks.request_with_retry", side_effect=fetch_then_change)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain == "other.example.com"
    assert claimed.custom_domain_validated is False


def test_the_challenge_is_bound_to_the_deployment_the_workspace_and_the_domain(settings):
    challenge = custom_domain_challenge(1, DOMAIN)

    assert challenge != custom_domain_challenge(2, DOMAIN)
    assert challenge != custom_domain_challenge(1, "other.example.com")
    settings.SECRET_KEY = "another-deployment"
    assert challenge != custom_domain_challenge(1, DOMAIN)
