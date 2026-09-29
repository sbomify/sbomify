"""The gzip middleware inflates a request body only for a bearer token we signed.

A compressed body without one gets 401 before it is inflated, and an inflated
body stays within the ceiling an uncompressed body gets.
"""

from __future__ import annotations

import gzip
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.test import override_settings

from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, create_personal_access_token
from sbomify.apps.core.middleware import GzipRequestDecompressionMiddleware

BODY = b'{"bomFormat": "CycloneDX"}'


def _compressed_request(authorization: str | None) -> HttpRequest:
    request = HttpRequest()
    request._body = gzip.compress(BODY)
    request.META["HTTP_CONTENT_ENCODING"] = "gzip"
    if authorization is not None:
        request.META["HTTP_AUTHORIZATION"] = authorization
    return request


def _run(request: HttpRequest) -> tuple[HttpResponse, list[HttpRequest]]:
    reached: list[HttpRequest] = []

    def view(r: HttpRequest) -> HttpResponse:
        reached.append(r)
        return HttpResponse("ok")

    return GzipRequestDecompressionMiddleware(view)(request), reached


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer not-a-token",
        "Bearer " + jwt.encode({"sub": "1"}, "a-key-that-is-not-ours-and-long-enough", algorithm="HS256"),
    ],
    ids=["no token", "garbage", "signed elsewhere"],
)
def test_a_compressed_body_without_a_signed_token_is_not_inflated(authorization):
    response, reached = _run(_compressed_request(authorization))

    assert response.status_code == 401
    assert reached == []


def test_the_refusal_is_the_json_every_api_401_carries():
    response, _ = _run(_compressed_request(None))

    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content) == {
        "detail": "A compressed request body needs a valid API token",
        "error_code": "UNAUTHORIZED",
    }


@pytest.mark.parametrize(
    "expires_in, audience",
    [(-60, settings.JWT_AUDIENCE), (600, "another-service")],
    ids=["expired", "another audience"],
)
def test_an_oidc_token_out_of_date_or_for_another_audience_inflates_nothing(expires_in, audience):
    claims = {
        "iss": settings.JWT_ISSUER,
        "sub": "1",
        "token_type": TOKEN_TYPE_OIDC,
        "exp": int(time.time()) + expires_in,
        "aud": audience,
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    response, reached = _run(_compressed_request(f"Bearer {token}"))

    assert response.status_code == 401
    assert reached == []


@pytest.mark.parametrize("scheme", ["Token", "Basic"])
def test_a_signed_token_under_another_scheme_inflates_nothing(scheme):
    token = create_personal_access_token(SimpleNamespace(pk=1))

    response, reached = _run(_compressed_request(f"{scheme} {token}"))

    assert response.status_code == 401
    assert reached == []


@override_settings(GZIP_REQUEST_MAX_SIZE=len(BODY) - 1)
def test_a_compressed_body_without_a_token_is_refused_before_it_is_inflated():
    response, reached = _run(_compressed_request(None))

    assert response.status_code == 401  # inflating first would stop at the ceiling with 400
    assert reached == []


def test_a_body_without_a_token_is_refused_before_it_is_read_as_gzip():
    request = _compressed_request(None)
    request._body = b"not gzip at all"

    response, reached = _run(request)

    assert response.status_code == 401  # reading it first would fail on the gzip header with 400
    assert reached == []


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_a_compressed_body_with_a_signed_token_is_inflated(scheme):
    token = create_personal_access_token(SimpleNamespace(pk=1))
    request = _compressed_request(f"{scheme} {token}")

    response, reached = _run(request)

    assert response.status_code == 200
    assert reached[0].body == BODY


def test_a_compressed_body_with_an_in_date_oidc_token_is_inflated():
    token = create_personal_access_token(
        SimpleNamespace(pk=1), expires_at=time.time() + 600, token_type=TOKEN_TYPE_OIDC
    )

    response, reached = _run(_compressed_request(f"Bearer {token}"))

    assert response.status_code == 200
    assert reached[0].body == BODY


def test_a_compressed_body_inflates_no_further_than_an_uncompressed_body_may_weigh():
    assert settings.GZIP_REQUEST_MAX_SIZE <= settings.DATA_UPLOAD_MAX_MEMORY_SIZE
