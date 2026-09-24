"""A custom domain is verified by fetching this deployment's challenge from it.

The Host header of a request is whatever the client sent, so a request carrying
the domain proves nothing about where the domain's DNS points. Only the probe,
which fetches the domain through public DNS, can mark it verified.
"""

import gzip
import io
import json
from urllib.parse import urlsplit

import pytest
import requests
import urllib3
from django.test import Client

from sbomify.apps.teams.models import Team
from sbomify.apps.teams.tasks import PROBE_MAX_BYTES, probe_custom_domain, verify_custom_domains
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


def _routed_here(url: str, **kwargs) -> requests.Response:
    """What the probe receives when the domain's DNS points at this deployment."""
    parts = urlsplit(url)
    served = Client().get(parts.path, HTTP_HOST=parts.hostname, secure=True)
    return _response(served.status_code, served.content)


def _routed_here_compressed(url: str, **kwargs) -> requests.Response:
    """The same, through a proxy that compresses the answer."""
    served = _routed_here(url)
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


@pytest.mark.parametrize("change", [{"custom_domain": "other.example.com"}, {"custom_domain_validated": True}])
def test_the_task_leaves_a_domain_that_changed_after_it_was_read(claimed, mocker, change):
    send = mocker.patch.object(probe_custom_domain, "send")

    def change_it_meanwhile(task_name: str, message: str, **kwargs) -> None:
        if message == "probe":
            Team.objects.filter(pk=claimed.pk).update(**change)

    # The breadcrumb is recorded between the task's read and its write.
    mocker.patch("sbomify.apps.teams.tasks.record_task_breadcrumb", side_effect=change_it_meanwhile)

    verify_custom_domains()

    send.assert_not_called()
    claimed.refresh_from_db()
    assert claimed.custom_domain_verification_failures == 0
    assert claimed.custom_domain_last_checked_at is None


@pytest.mark.parametrize("routed", [_routed_here, _routed_here_compressed])
def test_the_probe_verifies_a_domain_that_serves_the_challenge(claimed, mocker, routed):
    Team.objects.filter(pk=claimed.pk).update(custom_domain_verification_failures=1)
    fetch = mocker.patch("sbomify.apps.teams.tasks.requests.get", side_effect=routed)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is True
    assert claimed.custom_domain_verification_failures == 0
    assert claimed.custom_domain_last_checked_at is not None
    # A redirect would let the answer come from somewhere other than the domain,
    # and so would an unchecked certificate.
    assert fetch.call_args.kwargs["allow_redirects"] is False
    assert fetch.call_args.kwargs["verify"] is True


def test_the_probe_makes_one_request(claimed, mocker):
    fetch = mocker.patch("sbomify.apps.teams.tasks.requests.get", side_effect=requests.ConnectionError)

    probe_custom_domain(claimed.pk, DOMAIN)

    # The task's backoff schedules the next attempt.
    fetch.assert_called_once()
    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_the_probe_stops_reading_and_rejects_an_oversized_answer(claimed, mocker):
    answer = json.dumps({"challenge": custom_domain_challenge(claimed.pk, DOMAIN)}).encode()
    served = _response(200, answer + b" " * PROBE_MAX_BYTES * 4)
    mocker.patch("sbomify.apps.teams.tasks.requests.get", return_value=served)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False
    assert served.raw.tell() <= PROBE_MAX_BYTES + 1


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
    mocker.patch("sbomify.apps.teams.tasks.requests.get", return_value=_response(status, body))

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_the_probe_does_not_verify_a_domain_changed_while_it_ran(claimed, mocker):
    def fetch_then_change(url: str, **kwargs) -> requests.Response:
        response = _routed_here(url)
        Team.objects.filter(pk=claimed.pk).update(custom_domain="other.example.com")
        return response

    mocker.patch("sbomify.apps.teams.tasks.requests.get", side_effect=fetch_then_change)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain == "other.example.com"
    assert claimed.custom_domain_validated is False


def test_the_challenge_is_served_only_on_the_custom_domain(client, claimed, settings):
    settings.TRUST_CENTER_DOMAIN = "trustcenters.test"
    Team.objects.filter(pk=claimed.pk).update(is_public=True, slug="claimant")

    response = client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST="claimant.trustcenters.test")

    assert response.status_code == 200
    assert "challenge" not in response.json()


def test_the_challenge_is_bound_to_the_deployment_the_workspace_and_the_domain(settings):
    challenge = custom_domain_challenge(1, DOMAIN)

    assert challenge != custom_domain_challenge(2, DOMAIN)
    assert challenge != custom_domain_challenge(1, "other.example.com")
    settings.SECRET_KEY = "another-deployment"
    assert challenge != custom_domain_challenge(1, DOMAIN)
