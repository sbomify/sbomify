"""A custom domain is verified by fetching this deployment's challenge from it.

The Host header of a request is whatever the client sent, so a request carrying
the domain proves nothing about where the domain's DNS points. Only the probe,
which fetches the domain through public DNS, can mark it verified.
"""

import gzip
import io
import json
import socket

import pytest
import urllib3
from django.test import Client

from sbomify.apps.teams.models import Team
from sbomify.apps.teams.tasks import PROBE_MAX_BYTES, probe_custom_domain, verify_custom_domains
from sbomify.apps.teams.utils import custom_domain_challenge

DOMAIN = "trust.example.com"
PUBLIC_ADDRESS = "93.184.215.14"


@pytest.fixture
def claimed(db):
    return Team.objects.create(name="Claimant", billing_plan="business", custom_domain=DOMAIN)


@pytest.fixture(autouse=True)
def dns(mocker) -> dict[str, list[str]]:
    """What the domain resolves to: a public address unless a test says otherwise.

    An empty answer does not resolve. Other names resolve as usual.
    """
    answers = {DOMAIN: [PUBLIC_ADDRESS]}
    resolve = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host not in answers:
            return resolve(host, port, *args, **kwargs)
        if not answers[host]:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in answers[host]
        ]

    mocker.patch("socket.getaddrinfo", side_effect=getaddrinfo)
    return answers


@pytest.fixture
def fetch(mocker):
    """The probe's request, answered without a network."""
    return mocker.patch.object(urllib3.HTTPSConnectionPool, "urlopen", autospec=True)


def _response(status: int, body: bytes, headers: dict[str, str] | None = None) -> urllib3.HTTPResponse:
    return urllib3.HTTPResponse(body=io.BytesIO(body), headers=headers, status=status, preload_content=False)


def _routed_here(pool, method: str, url: str, headers: dict[str, str], **kwargs) -> urllib3.HTTPResponse:
    """What the probe receives when the domain's DNS points at this deployment."""
    served = Client().get(url, HTTP_HOST=headers["Host"], secure=True)
    return _response(served.status_code, served.content)


def _routed_here_compressed(pool, method: str, url: str, headers: dict[str, str], **kwargs) -> urllib3.HTTPResponse:
    """The same, through a proxy that compresses the answer."""
    served = _routed_here(pool, method, url, headers)
    return _response(served.status, gzip.compress(served.read()), {"Content-Encoding": "gzip"})


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
def test_the_probe_verifies_a_domain_that_serves_the_challenge(claimed, fetch, routed):
    Team.objects.filter(pk=claimed.pk).update(custom_domain_verification_failures=1)
    fetch.side_effect = routed

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is True
    assert claimed.custom_domain_verification_failures == 0
    assert claimed.custom_domain_last_checked_at is not None
    # The handshake names the domain and checks its certificate, and no redirect
    # is followed, so the answer comes from the domain itself.
    pool = fetch.call_args.args[0]
    assert pool.conn_kw["server_hostname"] == DOMAIN
    assert pool.cert_reqs == "CERT_REQUIRED"
    assert fetch.call_args.kwargs["redirect"] is False


@pytest.mark.parametrize(
    ("answers", "connected"),
    [
        ([PUBLIC_ADDRESS], PUBLIC_ADDRESS),
        (["10.0.0.5", PUBLIC_ADDRESS], PUBLIC_ADDRESS),
        (["::1", "2606:4700:4700::1111"], "2606:4700:4700::1111"),
    ],
)
def test_the_probe_connects_once_to_the_public_address_it_checked(claimed, dns, mocker, answers, connected):
    dns[DOMAIN] = answers
    connect = mocker.patch("urllib3.util.connection.create_connection", side_effect=OSError("unreachable"))

    probe_custom_domain(claimed.pk, DOMAIN)

    # The connection goes to the address that passed the check, not to the name,
    # so a DNS answer that changes after the check cannot move it. One attempt:
    # the task's backoff schedules the next.
    connect.assert_called_once()
    assert connect.call_args.args[0] == (connected, 443)
    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


@pytest.mark.parametrize(
    "answers",
    [
        [],
        ["127.0.0.1", "::1"],
        ["10.0.0.5", "172.16.0.5", "192.168.0.5", "fd00::5"],
        ["169.254.169.254", "fe80::1"],
        ["100.64.0.5"],
        ["0.0.0.0", "::"],
        ["224.0.0.251", "ff02::1"],
        ["fec0::5"],
        ["::ffff:10.0.0.5"],
        ["64:ff9b::a00:5"],
    ],
    ids=[
        "unresolved",
        "loopback",
        "private",
        "link-local",
        "shared",
        "unspecified",
        "multicast",
        "site-local",
        "ipv4-mapped",
        "nat64",
    ],
)
def test_the_probe_does_not_connect_to_a_domain_without_a_public_address(claimed, dns, mocker, answers):
    dns[DOMAIN] = answers
    connect = mocker.patch("urllib3.util.connection.create_connection", side_effect=OSError("unreachable"))

    probe_custom_domain(claimed.pk, DOMAIN)

    connect.assert_not_called()
    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_the_probe_stops_reading_and_rejects_an_oversized_answer(claimed, fetch):
    answer = json.dumps({"challenge": custom_domain_challenge(claimed.pk, DOMAIN)}).encode()
    served = _response(200, answer + b" " * PROBE_MAX_BYTES * 4)
    fetch.return_value = served

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False
    assert served.tell() <= PROBE_MAX_BYTES + 1


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
def test_the_probe_rejects_a_domain_that_serves_anything_else(claimed, fetch, status, body):
    fetch.return_value = _response(status, body)

    probe_custom_domain(claimed.pk, DOMAIN)

    claimed.refresh_from_db()
    assert claimed.custom_domain_validated is False


def test_the_probe_does_not_verify_a_domain_changed_while_it_ran(claimed, fetch):
    def fetch_then_change(*args, **kwargs) -> urllib3.HTTPResponse:
        response = _routed_here(*args, **kwargs)
        Team.objects.filter(pk=claimed.pk).update(custom_domain="other.example.com")
        return response

    fetch.side_effect = fetch_then_change

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
