"""Every status a component renders has to be readable in the theme it renders in.

test_component_colours.py pins which token a component reaches for. It passed
while the severity badges were unreadable on a white surface, because the token
it compared against was the same value in both themes: matching the palette says
nothing about whether the palette works.

This measures instead. It walks the gallery in both themes, computes the WCAG
2.1 contrast of every visible piece of text against the surface actually behind
it, and fails on anything below the AA threshold for its size.
"""

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.test_design_system_view import _debug_urlconf_fixture

debug_gallery = _debug_urlconf_fixture(True)

# Chromium serialises color-mix()/oklab() literally, so a regex over the computed
# string reads an oklab lightness as a red channel. The canvas converts for us.
MEASURE_JS = r"""
() => {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  const cache = new Map();
  const parse = (value) => {
    if (!value || value === 'transparent' || value === 'none') return null;
    if (cache.has(value)) return cache.get(value);
    let rgba = null;
    try {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = '#000';
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      rgba = [d[0], d[1], d[2], d[3] / 255];
    } catch (e) { rgba = null; }
    cache.set(value, rgba);
    return rgba;
  };
  const channel = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const luminance = (c) => 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2]);
  const ratio = (a, b) => {
    const [l1, l2] = [luminance(a), luminance(b)];
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  const over = (fg, bg) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));

  // The surface a caller actually reads the text on: composite every
  // translucent layer between the element and the first opaque one.
  const backdrop = (el) => {
    const layers = [];
    let node = el;
    let gradient = false;
    while (node) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== 'none') gradient = true;
      const colour = parse(style.backgroundColor);
      if (colour && colour[3] > 0) {
        layers.push(colour);
        if (colour[3] === 1) break;
      }
      node = node.parentElement;
    }
    let base = [255, 255, 255];
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return { rgb: base, gradient };
  };

  const hidden = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return true;
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return true;
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.clip === 'rect(0px, 0px, 0px, 0px)' || s.clipPath === 'inset(50%)') return true;
    }
    return false;
  };

  const findings = [];
  for (const el of document.querySelectorAll(SCOPE)) {
    if (hidden(el)) continue;
    const own = [...el.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim())
      .map((n) => n.textContent.trim())
      .join(' ');
    if (!own) continue;
    const style = getComputedStyle(el);
    const ink = parse(style.color);
    if (!ink) continue;
    const behind = backdrop(el);
    // A gradient backdrop is sampled as its solid layers only, so the measured
    // ratio is an estimate; skip rather than report a number we cannot stand by.
    if (behind.gradient) continue;
    const size = parseFloat(style.fontSize);
    const weight = Number(style.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const required = large ? 3.0 : 4.5;
    const measured = ratio(over(ink, behind.rgb), behind.rgb);
    if (measured >= required) continue;
    findings.push({
      text: own.slice(0, 40),
      ratio: Number(measured.toFixed(2)),
      required,
      ink: style.color,
      behind: 'rgb(' + behind.rgb.map(Math.round).join(' ') + ')',
      size: Number(size.toFixed(1)),
    });
  }
  return findings;
}
"""

# The status and severity carriers: every component that renders a state as text
# over a tint of that state. These are the recipes the ink tokens exist for.
STATUS_SCOPE = (
    "[data-level], [data-status], [data-format], [data-variant], "
    "[data-level] *, [data-status] *, [data-format] *, [data-variant] *"
)


def _measure(page: Page, scope: str) -> list[dict]:
    return page.evaluate(MEASURE_JS.replace("SCOPE", repr(scope)))


def _report(findings: list[dict], theme: str) -> str:
    lines = [f"{len(findings)} unreadable in the {theme} theme:"]
    for f in sorted(findings, key=lambda f: f["ratio"]):
        lines.append(
            f"  {f['ratio']}:1 (needs {f['required']}) {f['ink']} on {f['behind']} at {f['size']}px, text {f['text']!r}"
        )
    return "\n".join(lines)


@pytest.mark.django_db
@pytest.mark.usefixtures("debug_gallery")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_status_and_severity_are_readable_in_both_themes(authenticated_page: Page, theme: str) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.goto("/design-system/")
    expect(page.get_by_role("heading", name="Severity badges", exact=True)).to_be_attached()
    page.wait_for_timeout(300)

    assert page.locator(STATUS_SCOPE).count(), "the contrast check must exercise rendered status components"
    measured = _measure(page, STATUS_SCOPE)
    assert not measured, _report(measured, theme)
