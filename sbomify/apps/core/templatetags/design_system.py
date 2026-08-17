"""Design-system component tags — the calling convention for the shared UI library.

Each tag renders the matching template under ``components/tw/``, so a macro file
stays the only place a component's markup lives; these tags just make it callable
and composable. The Frontend (UI) section of AGENTS.md is the contract; ``/design-system/`` is
the live gallery.

Containers are block tags, so a card genuinely contains library components::

    {% load design_system %}
    {% card title="Releases" variant="dashboard" %}
        {% badge text="3 overdue" variant="danger" %}
        {% button text="New release" variant="primary" hx_get=new_release_url %}
    {% endcard %}

Leaves are inline tags::

    {% input name="search" label="Search" hint="Name or identifier" %}

Attribute passthrough: any keyword argument prefixed ``aria_``, ``data_``, ``hx_``
or ``x_`` is rendered as the dashed HTML attribute (``hx_post`` → ``hx-post``), with
its value escaped. A ``True`` value renders the bare attribute. Attribute names that
are not Python identifiers — Alpine's ``@click`` and ``:class`` — go through ``attrs``
as a raw trusted string, never user input.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django import template
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

_TEMPLATE_DIR = "components/tw"
_ATTR_PREFIXES = ("aria_", "data_", "hx_", "x_")

# Tag name -> template name, where the two differ. `breadcrumb` is already taken
# by the trust-center-only inclusion tag in breadcrumb_tags.py.
_ALIASES = {"breadcrumbs": "breadcrumb"}

# Leaf components: self-contained markup, called inline.
_LEAF_COMPONENTS = (
    "alert",
    "avatar",
    "badge",
    "breadcrumbs",
    "button",
    "button_link",
    "checkbox",
    "choice_group",
    "code_block",
    "dropdown",
    "empty_state",
    "icon_button",
    "input",
    "loading_state",
    "pagination",
    "progress",
    "radio",
    "select",
    "skeleton",
    "spinner",
    "tabs",
    "tag",
    "textarea",
    "toggle",
    "token_display",
)

# Container components: wrap content, called as ``{% x %}…{% endx %}``.
_BLOCK_COMPONENTS = (
    "actions_menu",
    "card",
    "modal",
    "page_header",
)


def _pop_attrs(params: dict[str, Any]) -> SafeString:
    """Move attribute-style kwargs out of ``params`` into one attribute string.

    ``attrs`` itself is passed through verbatim — it is author-written markup for
    attribute names Python cannot express, and the component templates already
    render it with ``|safe``.
    """
    pairs: list[SafeString] = []
    for key in [k for k in params if k.startswith(_ATTR_PREFIXES)]:
        value = params.pop(key)
        if value is None or value is False:
            continue
        name = key.replace("_", "-")
        pairs.append(format_html("{}", name) if value is True else format_html('{}="{}"', name, value))

    if raw := params.pop("attrs", ""):
        # Template-author markup for attribute names Python cannot express (@click,
        # :class). Never user input — the component templates already rendered this
        # with |safe before these tags existed.
        pairs.append(mark_safe(raw))  # nosec

    # Every piece above came from format_html or the trusted `attrs` string, so it
    # is already escaped; joining cannot introduce anything new.
    return mark_safe(" ".join(pairs))  # nosec


def _render(name: str, params: dict[str, Any]) -> SafeString:
    params["attrs"] = _pop_attrs(params)
    template = _ALIASES.get(name, name)
    # Django's template engine autoescapes every value it interpolated; this only
    # marks the finished component HTML so a tag can return it without re-escaping.
    return mark_safe(render_to_string(f"{_TEMPLATE_DIR}/{template}.html.j2", params))  # nosec


def _leaf(name: str) -> Callable[..., SafeString]:
    def component(**params: Any) -> SafeString:
        return _render(name, params)

    component.__name__ = name
    component.__doc__ = f"Render the {name} component ({_TEMPLATE_DIR}/{name}.html.j2)."
    return component


def _block(name: str) -> Callable[..., SafeString]:
    def component(content: str, **params: Any) -> SafeString:
        # Stripped so a component can test whether it was given any content at
        # all: an empty block still arrives as the template's whitespace.
        params["content"] = content.strip()
        return _render(name, params)

    component.__name__ = name
    component.__doc__ = f"Render the {name} container ({_TEMPLATE_DIR}/{name}.html.j2) around its block content."
    return component


for _name in _LEAF_COMPONENTS:
    register.simple_tag(_leaf(_name), name=_name)

for _name in _BLOCK_COMPONENTS:
    register.simple_block_tag(_block(_name), name=_name)
