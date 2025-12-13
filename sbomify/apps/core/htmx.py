import json
from typing import Any, Optional

from django.http import HttpResponse


def htmx_response(
    type: str, message: str, triggers: Optional[dict] = None, content: Optional[Any] = None
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


def htmx_success_response(message: str, triggers: Optional[dict] = None, content: Optional[Any] = None) -> HttpResponse:
    return htmx_response("success", message, triggers, content)


def htmx_error_response(message: str, triggers: Optional[dict] = None, content: Optional[Any] = None) -> HttpResponse:
    response = htmx_response("error", message, triggers, content)
    response["HX-Reswap"] = "none"
    return response
