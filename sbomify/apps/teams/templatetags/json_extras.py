from __future__ import annotations

import json
from typing import Any

from django import template
from django.core.serializers.json import DjangoJSONEncoder

register = template.Library()


@register.filter
def jsonify(value: Any) -> str:
    """
    Convert a Python object to JSON string for use in HTML data attributes.

    This filter properly serializes Python objects to JSON and handles None values
    appropriately for frontend consumption. The output will be HTML-escaped by
    the template's |escape filter.

    Usage: {{ my_dict|jsonify|escape }}
    """
    if value is None:
        return ""

    try:
        return json.dumps(value, cls=DjangoJSONEncoder)
    except (TypeError, ValueError):
        return ""
