"""Advisory-id rendering helpers shared by the core, plugins and sboms templates."""

from __future__ import annotations

from django import template

from sbomify.apps.security_advisories.references import advisory_url as _advisory_url

register = template.Library()


@register.filter
def advisory_url(identifier: str | None) -> str:
    """The authoritative page for an advisory id, or "" when there is none.

    Templates pair this with a plain-text fallback::

        {% with url=alias|advisory_url %}
            {% if url %}<a href="{{ url }}">{{ alias }}</a>{% else %}<span>{{ alias }}</span>{% endif %}
        {% endwith %}
    """
    return _advisory_url(identifier)
