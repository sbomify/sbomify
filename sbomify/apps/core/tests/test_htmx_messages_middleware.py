import json

import pytest
from django.contrib.messages import constants as message_constants
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from sbomify.apps.core.middleware import HtmxMessagesMiddleware


def _make_request(*, htmx: bool = False) -> HttpRequest:
    """Create a request with message storage attached."""
    request = HttpRequest()
    request.META["SERVER_NAME"] = "testserver"
    request.META["SERVER_PORT"] = "80"
    if htmx:
        request.META["HTTP_HX_REQUEST"] = "true"
    # Attach session and message storage (MessageMiddleware normally does this)
    request.session = {}
    storage = FallbackStorage(request)
    request._messages = storage
    return request


def _make_middleware(response: HttpResponse) -> HtmxMessagesMiddleware:
    """Create middleware that returns the given response."""
    return HtmxMessagesMiddleware(get_response=lambda r: response)


class TestHtmxMessagesMiddleware:
    def test_non_htmx_request_passes_through(self):
        """Non-HTMX requests are returned unchanged."""
        request = _make_request(htmx=False)
        request._messages.add(message_constants.SUCCESS, "Hello")
        response = HttpResponse("OK")

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result is response
        assert "HX-Trigger" not in result

    def test_htmx_request_with_messages(self):
        """HTMX request with Django messages -> messages appear in HX-Trigger."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Item created")
        response = HttpResponse("partial html")

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["messages"] == [{"type": "success", "message": "Item created"}]

    def test_htmx_request_with_multiple_messages(self):
        """Multiple Django messages of different levels are all captured."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Item saved")
        request._messages.add(message_constants.WARNING, "Field deprecated")
        request._messages.add(message_constants.ERROR, "Upload failed")
        response = HttpResponse("partial")

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert len(trigger["messages"]) == 3
        assert trigger["messages"][0] == {"type": "success", "message": "Item saved"}
        assert trigger["messages"][1] == {"type": "warning", "message": "Field deprecated"}
        assert trigger["messages"][2] == {"type": "error", "message": "Upload failed"}

    def test_htmx_request_merges_existing_trigger(self):
        """Messages are merged with existing HX-Trigger data, not overriding."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Saved")
        response = HttpResponse("partial")
        response["HX-Trigger"] = json.dumps({"refresh-list": True})

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["refresh-list"] is True
        assert trigger["messages"] == [{"type": "success", "message": "Saved"}]

    def test_htmx_request_does_not_duplicate_existing_messages(self):
        """If HX-Trigger already has messages key, middleware does not override."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "From session")
        existing_messages = [{"type": "info", "message": "From view"}]
        response = HttpResponse("partial")
        response["HX-Trigger"] = json.dumps({"messages": existing_messages})

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["messages"] == existing_messages

    def test_htmx_redirect_converted_to_hx_redirect(self):
        """HTMX redirect responses are converted to 200 + HX-Redirect header."""
        request = _make_request(htmx=True)
        response = HttpResponseRedirect("/dashboard/")

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.status_code == 200
        assert result["HX-Redirect"] == "/dashboard/"

    def test_htmx_redirect_preserves_cookies_and_headers(self):
        """Cookies and headers from the original redirect response are preserved."""
        request = _make_request(htmx=True)
        response = HttpResponseRedirect("/dashboard/")
        response.set_cookie("sessionid", "abc123", httponly=True)
        response["X-Custom-Header"] = "keep-me"

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.status_code == 200
        assert result["HX-Redirect"] == "/dashboard/"
        assert "sessionid" in result.cookies
        assert result.cookies["sessionid"].value == "abc123"
        assert result["X-Custom-Header"] == "keep-me"
        assert "Location" not in result

    def test_htmx_redirect_preserves_session_messages(self):
        """Messages remain in session when response is a redirect."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Saved")
        response = HttpResponseRedirect("/next/")

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.status_code == 200
        assert result["HX-Redirect"] == "/next/"
        # Messages should still be pending (not consumed by middleware)
        remaining = list(request._messages)
        assert len(remaining) == 1

    @pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
    def test_htmx_redirect_various_status_codes(self, status_code: int):
        """All redirect status codes are converted to 200 + HX-Redirect."""
        request = _make_request(htmx=True)
        response = HttpResponse(status=status_code)
        response["Location"] = "/target/"

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.status_code == 200
        assert result["HX-Redirect"] == "/target/"

    def test_304_not_modified_not_treated_as_redirect(self):
        """304 Not Modified is not converted to HX-Redirect."""
        request = _make_request(htmx=True)
        response = HttpResponse(status=304)

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.status_code == 304
        assert "HX-Redirect" not in result

    def test_htmx_request_no_messages_unchanged(self):
        """HTMX request with no pending messages returns response unchanged."""
        request = _make_request(htmx=True)
        response = HttpResponse("partial html")

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result is response
        assert "HX-Trigger" not in result

    @pytest.mark.parametrize(
        ("level", "expected_type"),
        [
            (message_constants.SUCCESS, "success"),
            (message_constants.ERROR, "error"),
            (message_constants.WARNING, "warning"),
            (message_constants.INFO, "info"),
        ],
    )
    def test_message_level_mapping(self, level: int, expected_type: str):
        """Each Django message level maps to the correct toast type."""
        request = _make_request(htmx=True)
        request._messages.add(level, "test message")
        response = HttpResponse("partial")

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["messages"][0]["type"] == expected_type

    def test_htmx_request_with_plain_string_trigger(self):
        """HX-Trigger with a plain string (not JSON) is handled gracefully."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Done")
        response = HttpResponse("partial")
        response["HX-Trigger"] = "custom-event"

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["custom-event"] is True
        assert trigger["messages"] == [{"type": "success", "message": "Done"}]

    def test_htmx_request_with_comma_separated_plain_string_trigger(self):
        """Comma-separated HX-Trigger string becomes multiple keys with messages merged."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Done")
        response = HttpResponse("partial")
        response["HX-Trigger"] = "event-a, event-b"

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        assert trigger["event-a"] is True
        assert trigger["event-b"] is True
        assert trigger["messages"] == [{"type": "success", "message": "Done"}]

    def test_htmx_request_with_json_array_trigger(self):
        """Non-dict JSON in HX-Trigger (invalid per HTMX spec) is discarded."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Done")
        response = HttpResponse("partial")
        response["HX-Trigger"] = json.dumps(["event-a", "event-b"])

        middleware = _make_middleware(response)
        result = middleware(request)

        trigger = json.loads(result["HX-Trigger"])
        # Invalid array trigger is discarded; only messages remain
        assert trigger == {"messages": [{"type": "success", "message": "Done"}]}

    def test_messages_marked_used_after_middleware(self):
        """After middleware processes messages, storage is marked as used."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Done")
        response = HttpResponse("partial")

        middleware = _make_middleware(response)
        middleware(request)

        # Storage is flagged as used — MessageMiddleware will clear it from session
        assert request._messages.used is True

    def test_response_body_preserved(self):
        """Middleware preserves the original response body when injecting messages."""
        request = _make_request(htmx=True)
        request._messages.add(message_constants.SUCCESS, "Saved")
        response = HttpResponse("original content")

        middleware = _make_middleware(response)
        result = middleware(request)

        assert result.content == b"original content"
