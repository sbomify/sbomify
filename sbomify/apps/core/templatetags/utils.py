import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django import template

register = template.Library()


@register.filter
def split(value, delimiter):
    return value.split(delimiter)


@register.filter
def pydantic_json(value):
    if not isinstance(value, list):
        return json.dumps(value.dict())
    return json.dumps([v.dict() for v in value])


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def add_utm(url, campaign="trust_center"):
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
