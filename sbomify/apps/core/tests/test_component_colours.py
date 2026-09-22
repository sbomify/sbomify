"""Keep component colours on the shared palette, including future additions."""

import re
from pathlib import Path

from django.conf import settings

APP_ROOT = Path(settings.BASE_DIR) / "sbomify"
COMPONENTS = APP_ROOT / "templates" / "components"


def component_recipes() -> dict[str, str]:
    recipes = {}
    for template in sorted(COMPONENTS.rglob("*.html*")):
        source = re.sub(r"{% comment %}.*?{% endcomment %}|{#.*?#}", "", template.read_text(), flags=re.S)
        # Colour-picker placeholders and user-supplied values are data, not styles.
        attributes = re.findall(r'(?:[\w:-]*class|style|fill|stroke)="([^"]*)"', source)
        recipes[template.relative_to(COMPONENTS).as_posix()] = " ".join(attributes)
    return recipes


def test_components_do_not_introduce_literal_hues() -> None:
    offenders = {}
    for name, recipe in component_recipes().items():
        literals = re.findall(r"#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])|(?:rgb|hsl|oklch|oklab)a?\([^)]*\)", recipe)
        # Black/white shadow and edge opacity do not define a competing palette.
        bad = [value for value in literals if not re.fullmatch(r"rgb\((?:0_0_0|255_255_255)(?:/[\d.]+)?\)", value)]
        if bad:
            offenders[name] = bad
    assert not offenders, f"Use design-system colour tokens: {offenders}"


def test_foreground_colours_are_not_mixed_into_local_shades() -> None:
    offenders = {
        name: matches
        for name, recipe in component_recipes().items()
        if (
            matches := re.findall(
                r"(?:text|fill|stroke)-\[(?:color:)?color-mix|--[\w-]*(?:ink|foreground):color-mix", recipe
            )
        )
    }
    assert not offenders, f"Foregrounds must use palette tokens directly: {offenders}"


def test_components_do_not_use_tailwinds_unrelated_colour_scales() -> None:
    scales = (
        "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|"
        "indigo|violet|purple|fuchsia|pink|rose"
    )
    offenders = {
        name: matches
        for name, recipe in component_recipes().items()
        if (matches := re.findall(rf"(?:text|bg|border|fill|stroke|ring)-(?:{scales})-\d+", recipe))
    }
    assert not offenders, f"Use the app's semantic colour tokens: {offenders}"


def test_component_colour_variables_exist_in_the_palette() -> None:
    tokens = set(re.findall(r"--color-([\w-]+)\s*:", (APP_ROOT / "assets/css/tailwind.src.css").read_text()))
    offenders = {
        name: sorted(missing)
        for name, recipe in component_recipes().items()
        if (missing := set(re.findall(r"var\(--color-([\w-]+)", recipe)) - tokens)
    }
    assert not offenders, f"Undefined colour tokens silently lose their styling: {offenders}"
