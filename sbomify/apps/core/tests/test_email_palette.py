"""Mail is drawn from the app's light-theme tokens, written out as hex.

Mail clients cannot read CSS custom properties, so the email layouts cannot
reference the tokens in sbomify/assets/css/tailwind.src.css the way a page does.
They copy them instead, and a copy drifts: both layouts sat on a slate palette
and a #4059d0 blue for months after the app had moved to navy, with nothing to
say so. These tests hold every hex in a layout to a value the light theme
actually declares, and every `/* --token */` note to the token it names.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)
TOKENS = BASE_DIR / "sbomify" / "assets" / "css" / "tailwind.src.css"
LAYOUTS = [
    BASE_DIR / "sbomify" / "apps" / "core" / "templates" / "core" / "emails" / "base.html.j2",
    BASE_DIR / "keycloak" / "themes" / "sbomify" / "email" / "html" / "template.ftl",
]

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
DECLARATION = re.compile(r"(--color-[a-z0-9-]+)\s*:\s*rgb\((\d+) (\d+) (\d+)\)")
ANNOTATED = re.compile(r"(#[0-9a-fA-F]{6})[^;]*;\s*/\*\s*(--color-[a-z0-9-]+)\s*\*/")


def _block(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start : css.index("\n}", start)]


def _light_theme() -> dict[str, str]:
    css = TOKENS.read_text()
    tokens: dict[str, str] = {}
    for selector in ("@theme", ":root", ":root.light"):
        for name, r, g, b in DECLARATION.findall(_block(css, selector)):
            tokens[name] = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    return tokens


def _layout(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path.relative_to(BASE_DIR)} is not in this checkout")
    return path.read_text()


@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.name)
def test_every_colour_in_an_email_layout_is_a_light_theme_token(path: Path) -> None:
    palette = set(_light_theme().values())
    invented = sorted({h.lower() for h in HEX.findall(_layout(path))} - palette)
    assert not invented, f"{path.name} uses colours the light theme does not declare: {invented}"


@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.name)
def test_every_token_note_in_an_email_layout_names_its_value(path: Path) -> None:
    tokens = _light_theme()
    wrong = [
        f"{value} is noted as {name}, which is {tokens.get(name, 'not a token')}"
        for value, name in ANNOTATED.findall(_layout(path))
        if tokens.get(name) != value.lower()
    ]
    assert not wrong, f"{path.name}: {wrong}"
