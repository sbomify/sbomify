from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


@register.filter
def split(value: Any, delimiter: Any) -> Any:
    return value.split(delimiter)


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
def add_utm(url: Any, campaign: Any = "trust_center") -> Any:
    """
    Add UTM tracking parameters to a URL.

    Usage in templates:
        {{ link.url|add_utm }}
        {{ link.url|add_utm:"product_page" }}

    Adds:
        - utm_source=sbomify
        - utm_medium=trust_center
        - utm_campaign=<campaign arg or 'trust_center'>
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Only add UTM params to external URLs (those with a netloc/domain)
        if not parsed.netloc:
            return url

        # Parse existing query parameters
        existing_params = parse_qs(parsed.query, keep_blank_values=True)

        # Add UTM parameters (don't overwrite if they exist)
        utm_params = {
            "utm_source": "sbomify",
            "utm_medium": "trust_center",
            "utm_campaign": campaign or "trust_center",
        }

        for key, value in utm_params.items():
            if key not in existing_params:
                existing_params[key] = [value]

        # Rebuild the URL with new query string
        # Flatten the params dict (parse_qs returns lists)
        flat_params = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
        new_query = urlencode(flat_params, doseq=True)

        new_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
        return new_url
    except Exception:
        # If anything goes wrong, return the original URL
        return url


SEVERITY_LEVELS = ("critical", "high", "medium", "low")


@register.filter
def severity_unknown(counts: dict[str, Any] | None) -> int:
    """The part of a severity total that none of the named levels account for."""
    if not counts:
        return 0
    named = sum(counts.get(level) or 0 for level in SEVERITY_LEVELS)
    return max(0, (counts.get("total") or 0) - named)


@register.filter
def severity_breakdown(counts: dict[str, Any] | None) -> str:
    """Written severity counts, worst first: "3 critical, 13 high, 2 unknown"."""
    if not counts:
        return ""
    parts = [(counts.get(level) or 0, level) for level in SEVERITY_LEVELS]
    parts.append((severity_unknown(counts), "unknown"))
    return ", ".join(f"{intcomma(count)} {label}" for count, label in parts if count)
