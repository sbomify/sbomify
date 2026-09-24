"""The gzip middleware inflates a request body only for a bearer token we signed.

A compressed body without one gets 401, and an inflated body stays within the
ceiling an uncompressed body gets.
"""

from __future__ import annotations

import gzip
from types import SimpleNamespace

import jwt
import pytest
from django.conf import settings
from django.http import HttpRequest, HttpResponse

from sbomify.apps.access_tokens.utils import create_personal_access_token
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


def test_a_compressed_body_with_a_signed_token_is_inflated():
    token = create_personal_access_token(SimpleNamespace(pk=1))
    request = _compressed_request(f"Bearer {token}")

    response, reached = _run(request)

    assert response.status_code == 200
    assert reached[0].body == BODY


def test_a_compressed_body_inflates_no_further_than_an_uncompressed_body_may_weigh():
    assert settings.GZIP_REQUEST_MAX_SIZE <= settings.DATA_UPLOAD_MAX_MEMORY_SIZE
