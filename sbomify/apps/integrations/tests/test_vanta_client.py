"""The Vanta read client: pagination, auth failures, and tolerant parsing."""

from __future__ import annotations

import pytest
import requests

from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.providers import vanta as vanta_module
from sbomify.apps.integrations.providers.vanta import VantaClient, VantaUnavailable


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _page(items: list[dict], *, next_cursor: str | None = None) -> dict:
    return {
        "results": {
            "data": items,
            "pageInfo": {
                "hasNextPage": next_cursor is not None,
                "endCursor": next_cursor,
            },
        }
    }


@pytest.fixture
def client() -> VantaClient:
    return VantaClient("vat_token", "https://api.vanta.example")


class TestPagination:
    def test_follows_the_cursor_until_the_last_page(self, client, monkeypatch) -> None:
        calls: list[dict] = []
        pages = [
            _page([{"id": "f1"}], next_cursor="cursor-1"),
            _page([{"id": "f2"}]),
        ]

        def fake_request(method, url, **kwargs):
            calls.append(kwargs.get("params") or {})
            return _Response(200, pages[len(calls) - 1])

        monkeypatch.setattr(vanta_module, "request_with_retry", fake_request)

        assert [item["id"] for item in client.frameworks()] == ["f1", "f2"]
        assert calls[0]["pageSize"] == vanta_module.PAGE_SIZE
        assert "pageCursor" not in calls[0]
        assert calls[1]["pageCursor"] == "cursor-1"

    def test_stops_when_the_page_claims_more_but_names_no_cursor(self, client, monkeypatch) -> None:
        """A truthy hasNextPage with a null endCursor would otherwise loop forever."""
        payload = {"results": {"data": [{"id": "f1"}], "pageInfo": {"hasNextPage": True, "endCursor": None}}}
        monkeypatch.setattr(vanta_module, "request_with_retry", lambda *a, **k: _Response(200, payload))

        assert [item["id"] for item in client.frameworks()] == ["f1"]

    def test_sends_the_bearer_token(self, client, monkeypatch) -> None:
        captured: dict[str, object] = {}

        def fake_request(method, url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            return _Response(200, _page([]))

        monkeypatch.setattr(vanta_module, "request_with_retry", fake_request)
        list(client.framework_controls("fw1"))

        assert captured["url"] == "https://api.vanta.example/v1/frameworks/fw1/controls"
        assert captured["headers"]["Authorization"] == "Bearer vat_token"

    def test_a_body_with_no_results_wrapper_is_an_empty_page(self, client, monkeypatch) -> None:
        monkeypatch.setattr(vanta_module, "request_with_retry", lambda *a, **k: _Response(200, {"unexpected": 1}))

        assert list(client.frameworks()) == []

    def test_non_dict_items_are_skipped(self, client, monkeypatch) -> None:
        payload = {"results": {"data": [{"id": "f1"}, "junk", None], "pageInfo": {"hasNextPage": False}}}
        monkeypatch.setattr(vanta_module, "request_with_retry", lambda *a, **k: _Response(200, payload))

        assert [item["id"] for item in client.frameworks()] == ["f1"]


class TestFailures:
    @pytest.mark.parametrize("status", [401, 403])
    def test_a_rejected_credential_asks_for_a_reconnect(self, client, monkeypatch, status) -> None:
        monkeypatch.setattr(vanta_module, "request_with_retry", lambda *a, **k: _Response(status, {}))

        with pytest.raises(ProviderAuthError):
            list(client.frameworks())

    def test_a_server_error_is_not_a_credential_problem(self, client, monkeypatch) -> None:
        """A 500 must not push the workspace into "needs reconnecting"."""
        monkeypatch.setattr(vanta_module, "request_with_retry", lambda *a, **k: _Response(500, {}))

        with pytest.raises(VantaUnavailable):
            list(client.frameworks())
        assert not issubclass(VantaUnavailable, ProviderAuthError)

    def test_an_unreachable_host_raises(self, client, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(vanta_module, "request_with_retry", boom)

        with pytest.raises(VantaUnavailable):
            list(client.frameworks())

    def test_a_non_json_body_raises(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            vanta_module, "request_with_retry", lambda *a, **k: _Response(200, ValueError("not json"))
        )

        with pytest.raises(VantaUnavailable):
            list(client.frameworks())
