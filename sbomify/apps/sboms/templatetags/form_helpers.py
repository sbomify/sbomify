from __future__ import annotations

from typing import Any

from django import template
from django.forms import CheckboxInput

register = template.Library()


@register.filter(name="is_checkbox")
def is_checkbox(field: Any) -> bool:
    return isinstance(field.field.widget, CheckboxInput)
