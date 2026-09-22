from __future__ import annotations

import json
from typing import Any, Optional, cast

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBase

from sbomify.apps.core.domain.exceptions import DomainError


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


class HtmxFragmentMixin:
    """A view whose template is a section rather than a page.

    These render markup that extends no base: no head, no stylesheet, no
    script. htmx swaps them into a page that already has all three, which is
    the only context they make sense in. Typed into a browser they answered
    200 and served the markup on its own, looking like nothing and doing
    nothing, and a URL that answers 200 also passes an uptime check.

    That stayed a curiosity until an email linked one of them. Every admin
    reviewing an access request landed on a bare section, and the only reason
    it took a customer report to find is that nothing else pointed at any of
    these. This says out loud that they are not pages.

    GET and HEAD are guarded. HEAD matters as much as GET here: Django's
    ``View.setup`` aliases ``head`` to ``get`` when a view defines no ``head``
    of its own, so a HEAD that skipped this check answered 200 while the same
    GET answered 404, and HEAD is what an uptime check sends.

    POST is not guarded. It arrives with a CSRF token from a form that meant
    to submit, and refusing those would break any form that ever submits
    without htmx.
    """

    #: Everything that reaches ``get`` and so would render the section.
    _GUARDED_METHODS = frozenset({"GET", "HEAD"})

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if request.method in self._GUARDED_METHODS and request.headers.get("HX-Request") != "true":
            raise Http404("This endpoint renders a section of a page, not a page.")
        # The mixin is declared standalone so it can be slotted in anywhere in a
        # view's bases; mypy cannot see the View underneath it from here.
        return cast(HttpResponseBase, super().dispatch(request, *args, **kwargs))  # type: ignore[misc]
