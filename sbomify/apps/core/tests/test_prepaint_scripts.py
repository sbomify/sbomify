"""Scripts that set the theme must run before first paint, even behind Cloudflare.

Rocket Loader rewrites every script to run after the page is parsed and painted.
For the theme script that means a frame in the wrong theme on every page load.
"""

import re

import pytest
from django.template.loader import get_template

PREPAINT_SCRIPT = re.compile(r"<script\b[^>]*>\s*(?:{% comment %}.*?{% endcomment %}\s*)?\(function", re.S)


@pytest.mark.parametrize("template", ["core/base.html.j2", "core/public_base.htmx.j2"])
def test_prepaint_theme_scripts_opt_out_of_rocket_loader(template: str) -> None:
    source = get_template(template).template.source
    script = PREPAINT_SCRIPT.search(source)
    assert script is not None
    assert 'data-cfasync="false"' in script.group(0)
