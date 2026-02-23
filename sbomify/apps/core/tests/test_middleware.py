import gzip

from django.http import HttpRequest, HttpResponse
from django.test import override_settings

from sbomify.apps.core.middleware import (
    GzipRequestDecompressionMiddleware,
    RealIPMiddleware,
)


def test_real_ip_middleware():
    """Test that RealIPMiddleware updates REMOTE_ADDR correctly."""
    middleware = RealIPMiddleware(get_response=lambda r: None)
    request = HttpRequest()

    # 1. X-Real-IP present (standard Caddy setup)
    request.META = {
        "HTTP_X_REAL_IP": "1.2.3.4",
        "REMOTE_ADDR": "10.0.0.1",
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "1.2.3.4"

    # 2. No X-Real-IP, should stay as REMOTE_ADDR
    request.META = {
        "REMOTE_ADDR": "10.0.0.1",
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# GzipRequestDecompressionMiddleware tests
# ---------------------------------------------------------------------------

_OK_RESPONSE = HttpResponse("ok")


def _make_middleware(
    get_response=None,
) -> GzipRequestDecompressionMiddleware:
    return GzipRequestDecompressionMiddleware(
        get_response=get_response or (lambda r: _OK_RESPONSE),
    )


def _gzip_request(body: bytes) -> HttpRequest:
    """Return an HttpRequest with a gzip-compressed body."""
    compressed = gzip.compress(body)
    request = HttpRequest()
    request._body = compressed
    request.META["HTTP_CONTENT_ENCODING"] = "gzip"
    request.META["CONTENT_LENGTH"] = str(len(compressed))
    return request


class TestGzipDecompressionPassthrough:
    def test_no_content_encoding_passes_through(self):
        """Requests without Content-Encoding: gzip are untouched."""
        original_body = b"hello"
        request = HttpRequest()
        request._body = original_body

        middleware = _make_middleware()
        response = middleware(request)

        assert response is _OK_RESPONSE
        assert request.body == original_body

    def test_non_gzip_encoding_passes_through(self):
        """Content-Encoding values other than gzip are ignored."""
        request = HttpRequest()
        request._body = b"hello"
        request.META["HTTP_CONTENT_ENCODING"] = "br"

        middleware = _make_middleware()
        response = middleware(request)

        assert response is _OK_RESPONSE

    def test_multiple_content_encodings_gzip_first_returns_400(self):
        """Multiple Content-Encoding values like 'gzip, br' return 400."""
        request = HttpRequest()
        request._body = b"hello"
        request.META["HTTP_CONTENT_ENCODING"] = "gzip, br"

        middleware = _make_middleware()
        response = middleware(request)

        assert response.status_code == 400
        assert b"multiple Content-Encoding" in response.content

    def test_multiple_content_encodings_gzip_last_returns_400(self):
        """Multiple Content-Encoding values like 'br, gzip' return 400."""
        request = HttpRequest()
        request._body = b"hello"
        request.META["HTTP_CONTENT_ENCODING"] = "br, gzip"

        middleware = _make_middleware()
        response = middleware(request)

        assert response.status_code == 400
        assert b"multiple Content-Encoding" in response.content

    def test_whitespace_around_gzip_is_handled(self):
        """Content-Encoding with extra whitespace still works."""
        original = b"test data"
        compressed = gzip.compress(original)
        request = HttpRequest()
        request._body = compressed
        request.META["HTTP_CONTENT_ENCODING"] = "  gzip  "
        request.META["CONTENT_LENGTH"] = str(len(compressed))

        middleware = _make_middleware()
        response = middleware(request)

        assert response is _OK_RESPONSE
        assert request.body == original


class TestGzipDecompressionSuccess:
    def test_decompresses_gzip_body(self):
        """Valid gzip body is decompressed transparently."""
        original = b"The quick brown fox jumps over the lazy dog"
        request = _gzip_request(original)

        captured = {}

        def capture_request(r):
            captured["body"] = r.body
            return _OK_RESPONSE

        middleware = _make_middleware(get_response=capture_request)
        response = middleware(request)

        assert response is _OK_RESPONSE
        assert captured["body"] == original

    def test_content_length_updated(self):
        """CONTENT_LENGTH reflects the decompressed size."""
        original = b"x" * 1000
        request = _gzip_request(original)

        middleware = _make_middleware()
        middleware(request)

        assert request.META["CONTENT_LENGTH"] == str(len(original))

    def test_content_encoding_removed(self):
        """HTTP_CONTENT_ENCODING is removed after decompression."""
        request = _gzip_request(b"data")

        middleware = _make_middleware()
        middleware(request)

        assert "HTTP_CONTENT_ENCODING" not in request.META


class TestGzipDecompressionErrors:
    def test_invalid_gzip_returns_400(self):
        """Non-gzip data with Content-Encoding: gzip returns 400."""
        request = HttpRequest()
        request._body = b"this is not gzip"
        request.META["HTTP_CONTENT_ENCODING"] = "gzip"

        middleware = _make_middleware()
        response = middleware(request)

        assert response.status_code == 400
        assert b"Invalid gzip data" in response.content

    @override_settings(GZIP_REQUEST_MAX_SIZE=50)
    def test_exceeding_size_limit_returns_400(self):
        """Decompressed body exceeding GZIP_REQUEST_MAX_SIZE returns 400."""
        original = b"x" * 100  # 100 bytes, limit set to 50
        request = _gzip_request(original)

        middleware = _make_middleware()
        response = middleware(request)

        assert response.status_code == 400
        assert b"exceeds" in response.content

    @override_settings(GZIP_REQUEST_MAX_SIZE=200)
    def test_within_size_limit_succeeds(self):
        """Decompressed body within GZIP_REQUEST_MAX_SIZE succeeds."""
        original = b"x" * 100  # 100 bytes, limit is 200
        request = _gzip_request(original)

        middleware = _make_middleware()
        response = middleware(request)

        assert response is _OK_RESPONSE
        assert request.body == original
