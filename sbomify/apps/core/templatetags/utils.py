from __future__ import annotations

import json
from typing import Any

from django import template

register = template.Library()


@register.filter
def pydantic_json(value: Any) -> Any:
    if not isinstance(value, list):
        return json.dumps(value.dict())
    return json.dumps([v.dict() for v in value])


@register.filter
def get_item(dictionary: Any, key: Any) -> Any:
    """Get an item from a dictionary by key."""
    if dictionary is None:
        return None
    return dictionary.get(key)
