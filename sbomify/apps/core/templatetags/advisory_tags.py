"""Advisory-id rendering helpers shared by the core, plugins and sboms templates."""

from __future__ import annotations

from collections.abc import Iterable

from django import template

from sbomify.apps.security_advisories.references import advisory_url as _advisory_url
from sbomify.apps.security_advisories.references import insights_url as _insights_url

register = template.Library()


@register.filter
def advisory_url(identifier: str | None, aliases: Iterable[str] | None = None) -> str:
    """The page for an advisory id, or "" when there is none.

    Pass the finding's aliases when it has them, so an id filed under a CVE
    links to that CVE's page::

        {% with url=vuln.id|advisory_url:vuln.aliases %}
            {% if url %}<a href="{{ url }}">{{ vuln.id }}</a>{% else %}<span>{{ vuln.id }}</span>{% endif %}
        {% endwith %}
    """
    return _advisory_url(identifier, aliases)


@register.filter
def insights_url(identifier: str | None) -> str:
    """The Insights page for an advisory id, or "" when Insights does not publish its scheme.

    For a reference that already stores a URL: only Insights replaces it, so a
    publisher's own link for any other scheme survives::

        {% with url=reference.external_id|insights_url|default:reference.url %}
    """
    return _insights_url(identifier)
