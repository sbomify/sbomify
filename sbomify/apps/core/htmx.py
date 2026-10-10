from __future__ import annotations

import json
from typing import Any, Optional, cast

from django.http import Http404, HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.core.domain.exceptions import DomainError


def refuse_direct_read(request: HttpRequest) -> None:
    """A fragment is not a page: a GET or HEAD that htmx did not send is a 404, whoever asks."""
    if request.method in ("GET", "HEAD") and request.headers.get("HX-Request") != "true":
        raise Http404


class HtmxFragmentMixin(View):
    """A fragment is not a page: a GET that htmx did not send is a 404, not bare markup.

    First in a view's bases, so the 404 comes before any login or role check.
    A view that gates access in its own ``dispatch`` calls ``refuse_direct_read``
    before that gate, for the same order.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        refuse_direct_read(request)
        return cast(HttpResponse, super().dispatch(request, *args, **kwargs))


def htmx_response(
    type: str,
    message: str,
    triggers: Optional[dict[str, Any]] = None,
    content: Optional[Any] = None,
) -> HttpResponse:
    response = HttpResponse()

    trigger_data = {"messages": [{"type": type, "message": message}]}
    if triggers:
        trigger_data.update(triggers)
    response["HX-Trigger"] = json.dumps(trigger_data)

    if content is not None:
        if isinstance(content, dict):
            content = json.dumps(content).encode("utf-8")
        response.content = content

    return response


def htmx_success_response(
    message: str,
    triggers: Optional[dict[str, Any]] = None,
    content: Optional[Any] = None,
) -> HttpResponse:
    return htmx_response("success", message, triggers, content)


def htmx_error_response(
    message: str,
    triggers: Optional[dict[str, Any]] = None,
    content: Optional[Any] = None,
) -> HttpResponse:
    response = htmx_response("error", message, triggers, content)
    response["HX-Reswap"] = "none"
    return response


def htmx_error_from_exception(error: DomainError) -> HttpResponse:
    return htmx_error_response(error.detail, content=error.to_dict())
