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


@register.filter
def humanize_token(value: Any) -> str:
    """A machine code as display text: ``dependency-track`` becomes "Dependency Track".

    The template-side door onto ``core.utils.humanize_token``, for the last
    branch of a badge or a label where no real display name is to hand. Reach
    for a stored label first — a plugin's ``display_name``, a model's
    ``get_FOO_display()`` — and for this only when there is none.
    """
    from sbomify.apps.core.utils import humanize_token as _humanize_token

    return _humanize_token(value)
