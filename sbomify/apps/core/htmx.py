import json
from typing import Optional

from django.http import HttpResponse


def htmx_success_response(message: str, triggers: Optional[dict] = None) -> HttpResponse:
    response = HttpResponse()
    trigger_data = {"messages": [{"type": "success", "message": message}]}
    if triggers:
        trigger_data.update(triggers)
    response["HX-Trigger"] = json.dumps(trigger_data)
    return response


def htmx_error_response(message: str) -> HttpResponse:
    response = HttpResponse()
    response["HX-Reswap"] = "none"
    response["HX-Trigger"] = json.dumps(
        {
            "messages": [{"type": "error", "message": message}],
        }
    )
    return response
