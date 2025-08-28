"""
Template tags for UTM parameter handling
"""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django import template

register = template.Library()


@register.filter
def add_utm(url, utm_params):
    """
    Add UTM parameters to external URLs only, while preserving existing query parameters.
    Internal sbomify links are not modified.

    Usage: {{ link.url|add_utm:"source=sbomify&medium=public_page&campaign=product_links" }}
    """
    if not url or not utm_params:
        return url

    # Parse the URL
    parsed = urlparse(url)

    # Check if this is an external URL
    # Internal URLs: relative paths, localhost, dev.sbomify.com, sbomify.com
    internal_domains = ["localhost", "dev.sbomify.com", "sbomify.com", "127.0.0.1"]

    # If it's a relative URL or internal domain, don't add UTM
    if not parsed.netloc or parsed.netloc in internal_domains:
        return url

    # Parse existing query parameters
    query_dict = parse_qs(parsed.query)

    # Parse UTM parameters to add
    utm_dict = parse_qs(utm_params)

    # Merge the parameters (UTM parameters override existing ones)
    for key, value in utm_dict.items():
        query_dict[key] = value

    # Rebuild the URL
    new_query = urlencode(query_dict, doseq=True)
    new_parsed = parsed._replace(query=new_query)

    return urlunparse(new_parsed)


@register.simple_tag
def utm_link(url, source="sbomify", medium="public_page", campaign="product_links", content=""):
    """
    Create a URL with UTM parameters.

    Usage: {% utm_link link.url source="sbomify" medium="public_page" campaign="product_links" content=link.link_type %}
    """
    if not url:
        return url

    utm_params = f"utm_source={source}&utm_medium={medium}&utm_campaign={campaign}"
    if content:
        utm_params += f"&utm_content={content}"

    return add_utm(url, utm_params)
