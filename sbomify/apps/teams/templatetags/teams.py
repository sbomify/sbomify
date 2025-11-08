from django import template

register = template.Library()


@register.simple_tag
def current_member(members):
    if not members:
        return None
    return next((member for member in members if member.is_me), None)
