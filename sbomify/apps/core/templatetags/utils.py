import json

from django import template

register = template.Library()


@register.filter
def split(value, delimiter):
    return value.split(delimiter)


@register.filter
def pydantic_json(value):
    return json.dumps([v.dict() for v in value])
