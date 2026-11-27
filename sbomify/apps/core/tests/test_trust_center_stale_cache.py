"""Public Trust Center pages keep loading from a stored copy while the database is down."""

import pytest
from django.core.cache import cache
from django.db import OperationalError
from django.test import Client

from django.http import HttpResponse

from sbomify.apps.core import stale_cache
from sbomify.apps.core.middleware import CustomDomainContextMiddleware
from sbomify.apps.teams.models import Workspace

pytestmark = pytest.mark.django_db

HOST = "trust.example.com"


def stored_key(host: str, path: str) -> str:
    return stale_cache._cache_key(stale_cache._KEY_PREFIX, host, path)


@pytest.fixture(autouse=True)
def setup_app_base_url(settings):
    settings.APP_BASE_URL = "http://app.sbomify.com"


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    # Answer with the 500 a browser would get, instead of re-raising into the test.
    return Client(raise_request_exception=False)


@pytest.fixture
def trust_center(db):
    team = Workspace.objects.create(
        name="Test Company",
        billing_plan="business",
        custom_domain=HOST,
        custom_domain_validated=True,
    )
    team.is_public = True
    team.save(update_fields=["is_public"])
    return team


@pytest.fixture
def database_down(mocker):
    """Fail the way the workspace lookup does when Postgres stops answering."""

    def _down(exc: Exception | None = None):
        return mocker.patch.object(
            CustomDomainContextMiddleware,
            "_get_team_for_domain",
            side_effect=exc or OperationalError("connection to server failed: timeout expired"),
        )

    return _down


def test_serves_stored_copy_when_database_is_unavailable(client, trust_center, database_down):
    fresh = client.get("/", HTTP_HOST=HOST)
    assert fresh.status_code == 200

    database_down()
    stale = client.get("/", HTTP_HOST=HOST)

    assert stale.status_code == 200
    assert stale.content == fresh.content
    assert stale["X-Cache"] == "STALE"
    assert stale["Cache-Control"] == "no-store"
    assert stale["Content-Type"] == fresh["Content-Type"]
    assert int(stale["Age"]) >= 0


def test_head_is_served_without_a_body(client, trust_center, database_down):
    fresh = client.get("/", HTTP_HOST=HOST)
    database_down()

    stale = client.head("/", HTTP_HOST=HOST)

    assert stale.status_code == 200
    assert stale.content == b""
    assert stale["Content-Length"] == str(len(fresh.content))


def test_without_a_stored_copy_the_error_stands(client, trust_center, database_down):
    database_down()

    assert client.get("/", HTTP_HOST=HOST).status_code == 500


def test_other_errors_are_not_masked(client, trust_center, database_down):
    client.get("/", HTTP_HOST=HOST)
    database_down(ValueError("a bug, not an outage"))

    assert client.get("/", HTTP_HOST=HOST).status_code == 500


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"HTTP_HX_REQUEST": "true"}, id="htmx"),
        pytest.param({"HTTP_AUTHORIZATION": "Bearer token"}, id="bearer"),
    ],
)
def test_requests_that_may_get_a_different_response_are_not_stored(client, trust_center, database_down, extra):
    assert client.get("/", HTTP_HOST=HOST, **extra).status_code == 200
    database_down()

    assert client.get("/", HTTP_HOST=HOST).status_code == 500


def test_a_session_holder_is_not_stored_but_is_served_the_public_copy(client, trust_center, database_down, settings):
    signed_in = Client(raise_request_exception=False)
    signed_in.cookies[settings.SESSION_COOKIE_NAME] = "someone-signed-in"
    assert signed_in.get("/", HTTP_HOST=HOST).status_code == 200
    assert cache.get(stored_key(HOST, "/")) is None

    client.get("/", HTTP_HOST=HOST)
    database_down()

    assert signed_in.get("/", HTTP_HOST=HOST)["X-Cache"] == "STALE"


def test_query_strings_are_neither_stored_nor_served(client, trust_center, database_down):
    assert client.get("/?page=2", HTTP_HOST=HOST).status_code == 200
    database_down()
    assert client.get("/?page=2", HTTP_HOST=HOST).status_code == 500


def test_htmx_requests_are_not_served_a_full_page(client, trust_center, database_down):
    client.get("/", HTTP_HOST=HOST)
    database_down()

    assert client.get("/", HTTP_HOST=HOST, HTTP_HX_REQUEST="true").status_code == 500


def test_main_app_pages_are_not_stored(client):
    client.get("/login/", HTTP_HOST="app.sbomify.com")

    assert cache.get(stored_key("app.sbomify.com", "/login/")) is None


def _response(status=200, content=b"page", **headers):
    response = HttpResponse(content, status=status)
    for name, value in headers.items():
        response[name] = value
    return response


def _with_cookie():
    response = _response()
    response.set_cookie("csrftoken", "per-visitor")
    return response


@pytest.mark.parametrize(
    ("response", "storable"),
    [
        pytest.param(_response(), True, id="public-page"),
        pytest.param(_response(status=404), False, id="not-found"),
        pytest.param(_with_cookie(), False, id="sets-cookie"),
        pytest.param(_response(**{"Cache-Control": "private"}), False, id="private"),
        pytest.param(_response(**{"Cache-Control": "no-store"}), False, id="no-store"),
        pytest.param(_response(content=b"x" * 2048), False, id="too-large"),
    ],
)
def test_only_complete_shareable_responses_are_stored(response, storable, settings):
    settings.TRUST_CENTER_STALE_CACHE_MAX_BYTES = 1024

    assert stale_cache._is_storable_response(response) is storable


def test_disabled_with_zero_ttl(client, trust_center, database_down, settings):
    settings.TRUST_CENTER_STALE_CACHE_TTL = 0
    client.get("/", HTTP_HOST=HOST)
    database_down()

    assert client.get("/", HTTP_HOST=HOST).status_code == 500


def test_stored_copy_is_refreshed_at_most_once_per_window(client, trust_center, mocker):
    set_spy = mocker.spy(cache, "set")

    client.get("/", HTTP_HOST=HOST)
    client.get("/", HTTP_HOST=HOST)

    assert [call.args[0] for call in set_spy.call_args_list].count(stored_key(HOST, "/")) == 1


def test_liveness_answers_without_the_database(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = client.get("/UuPha8mu/live/", HTTP_HOST="sbomify-backend:8000")

    assert response.status_code == 200
    assert response.content == b"OK"
