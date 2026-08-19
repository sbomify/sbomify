import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from narrator import Narrator
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
    team_with_business_plan,  # noqa: F401
)
from sbomify.apps.sboms.models import SBOM, Component, Product
from sbomify.apps.teams.models import Member, Team

# Full HD. Marketplace listings (AWS, GitHub, Atlassian) reject or upscale
# anything below 1080p, so this is the floor for every recording — the video
# encoder gets exactly these dimensions. ``device_scale_factor`` below doubles
# it again for stills, so screenshots land at 3840x2160.
RECORDING_WIDTH = 1920
RECORDING_HEIGHT = 1080
OUTPUT_DIR = Path(__file__).parent / "output"

# Minimal valid PDF for fake uploads in screencasts.
MINIMAL_PDF = (
    b"%PDF-1.0\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF\n"
)
CLICK_INDICATOR_JS = Path(__file__).parent / "click_indicator.js"
LOGO_SVG = Path(__file__).parent.parent / "sbomify" / "static" / "img" / "logo-circle.svg"

# Match the app's dark-mode background so the recording never flashes white.
APP_BG_COLOR = "#0A0A23"

# Splash screen shown while the first real page loads.  The logo SVG is read
# once at import time and embedded directly in the HTML.  Force the SVG to
# scale within its container by replacing the hardcoded dimensions.
_logo_svg_content = (
    LOGO_SVG.read_text().replace('width="257" height="257"', 'width="100%" height="100%"') if LOGO_SVG.exists() else ""
)
SPLASH_HTML = f"""\
<html style="background:{APP_BG_COLOR}">
<body style="margin:0;display:flex;justify-content:center;align-items:center;
             min-height:100vh;background:{APP_BG_COLOR}">
  <div style="opacity:0.35;width:120px;height:120px">
    {_logo_svg_content}
  </div>
</body>
</html>"""


@pytest.fixture(autouse=True)
def disable_billing(settings) -> None:
    """Disable Stripe billing so screencasts don't hit payment APIs."""
    settings.BILLING = False


_SCREENSHOT_MIN_PACE_MS = 800
_SCREENSHOT_INTERVAL_SEC = 3.0

_screenshot_state: dict[str, Any] = {
    "dir": None,
    "hero_dir": None,
    "last_time": 0.0,
    "counter": 0,
}

# Hero-shot names become filenames, so keep them to a slug we can trust.
_HERO_NAME_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Generator[None, Any, None]:
    """Stash each phase's outcome so fixtures can tell a pass from a failure.

    Without this the narration teardown would raise "beats never spoken" on top
    of whatever actually broke the recording, burying the real error.
    """
    outcome = yield
    item.stash.setdefault(_REPORT_KEY, {})[call.when] = outcome.get_result().passed


_REPORT_KEY = pytest.StashKey[dict]()


def _test_passed(request: pytest.FixtureRequest) -> bool:
    return bool(request.node.stash.get(_REPORT_KEY, {}).get("call", False))


def _recording_name(request: pytest.FixtureRequest) -> str:
    """Filename stem for the recorded artifacts.

    For parametrized tests, produces ``<func>_<param_id>`` so the
    pytest brackets do not end up in filenames (which trips shell
    globs and downstream cleanup heuristics).
    """
    node = request.node
    callspec = getattr(node, "callspec", None)
    if callspec is not None:
        return f"{node.originalname}_{callspec.id}"
    return node.name


def _maybe_capture_screenshot(page: Page) -> None:
    out_dir = _screenshot_state["dir"]
    if out_dir is None:
        return
    now = time.monotonic()
    if now - _screenshot_state["last_time"] < _SCREENSHOT_INTERVAL_SEC:
        return
    _screenshot_state["counter"] += 1
    path = out_dir / f"frame_{_screenshot_state['counter']:03d}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except PlaywrightError as exc:
        print(f"[screencasts] screenshot capture failed: {exc}", file=sys.stderr)
        return
    _screenshot_state["last_time"] = now


def _set_caption_visible(page: Page, visible: bool) -> None:
    """Toggle the narration caption's visibility without removing it.

    ``visibility`` rather than ``display`` so the caption keeps its box and
    does not reflow the page between the hide and the restore — a reflow mid
    recording is visible as a jump in the video.
    """
    try:
        page.evaluate(
            """(payload) => {
                const bar = document.getElementById(payload.id);
                if (bar) bar.style.visibility = payload.visible ? 'visible' : 'hidden';
            }""",
            {"id": CAPTION_ID, "visible": visible},
        )
    except PlaywrightError:
        # The page can navigate out from under a hero shot; a missing caption
        # is not worth failing a recording over.
        pass


def shot(page: Page, name: str, *, full_page: bool = False, settle_ms: int = 400) -> None:
    """Capture a curated, stably-named still into the recording's ``hero/`` dir.

    The timer-driven frames captured by :func:`pace` are incidental — they
    land wherever the 3s cadence happens to fall, so half of them catch a
    modal mid-transition or a table mid-load. Marketplace listings need the
    opposite: a small, deliberately chosen set of images with names that stay
    put across re-records, so a listing that embeds ``04-vulnerability-posture.png``
    keeps working after the next run.

    Call this at the moments worth publishing. ``name`` must be a lowercase
    slug (digits, dashes, underscores) — it becomes the filename, and a
    numeric prefix keeps the set in narrative order in a file browser.

    Any :func:`caption` showing is hidden for the duration of the capture and
    restored afterwards. The video wants the caption — it plays muted and
    needs the narration; a still does not, because the listing supplies its own
    caption, and the lower-third would otherwise sit on top of the table rows
    the screenshot exists to show.

    Args:
        page: The recording page.
        name: Slug for the file, e.g. ``"09-vulnerability-posture"``.
        full_page: Capture the whole scrollable page rather than the viewport.
            Viewport shots match what the video shows and are the default;
            full-page is for long surfaces you want to show entirely.
        settle_ms: Pause before capturing, letting transitions and lazily
            loaded panels finish so the still is not caught mid-animation.
    """
    if not _HERO_NAME_RE.match(name):
        raise ValueError(f"hero shot name must be a lowercase slug, got {name!r}")

    hero_dir = _screenshot_state["hero_dir"]
    if hero_dir is None:
        return

    page.wait_for_timeout(settle_ms)
    _set_caption_visible(page, False)
    try:
        page.screenshot(path=str(hero_dir / f"{name}.png"), full_page=full_page)
    except PlaywrightError as exc:
        print(f"[screencasts] hero shot {name!r} failed: {exc}", file=sys.stderr)
    finally:
        _set_caption_visible(page, True)


def pace(page: Page, ms: int = 600) -> None:
    """Pause for a natural beat between actions.

    Long pauses (>= 800ms) double as screenshot capture points when at
    least 3s have passed since the last frame. Screenshot time is counted
    against the requested pause so the overall delay stays about the same.
    """
    remaining_ms = ms
    if ms >= _SCREENSHOT_MIN_PACE_MS:
        started = time.monotonic()
        _maybe_capture_screenshot(page)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        remaining_ms = max(0, ms - elapsed_ms)
    page.wait_for_timeout(remaining_ms)


# ---------------------------------------------------------------------------
# Narration — spoken voiceover
#
# The voice is synthesized ahead of the recording (see narrator.py) and muxed
# in afterwards (see mux_narration.py), which also writes a WebVTT subtitle
# file from these same offsets.  Because the audio carries the explanation,
# ``caption()`` suppresses its lower-third in a narrated recording and the
# subtitles serve viewers watching muted.
# ---------------------------------------------------------------------------

# Breath between lines.  Short, because a narrator runs one sentence into the
# next rather than pausing between them.
_INTER_BEAT_GAP_MS = 180

_narration_state: dict[str, Any] = {
    "narrator": None,
    "t0": 0.0,
    "beats": [],
    "busy_until": 0.0,
}


def narrate(page: Page, key: str) -> None:
    """Start speaking a narration beat, and return immediately.

    Narration is a voiceover: the line plays *while* the clicking, typing and
    page loads underneath it continue, the way a person talks over a demo.  So
    this does not hold the shot — it notes when the line starts and hands
    control straight back to the script, which keeps working under the voice.

    It does wait for the previous line to finish first, so lines never overlap
    each other.  Use ``settle()`` where the picture must not move on until the
    current sentence has landed.

    Recordings without a narration script are unaffected: ``narrate`` becomes a
    no-op and their existing ``pace()`` and ``caption()`` calls still drive the
    timing.
    """
    narrator: Narrator | None = _narration_state["narrator"]
    if narrator is None:
        return

    settle(page)

    clip = narrator.get(key)
    offset_ms = (time.monotonic() - _narration_state["t0"]) * 1000

    # Start the next line synthesizing while this one plays.  The API returns
    # audio faster than real time, so the request finishes before it is needed.
    narrator.prefetch(narrator.next_key(key))

    _narration_state["beats"].append(
        {
            "key": key,
            "offset_ms": round(offset_ms, 1),
            "duration": clip.duration,
            "sha": clip.sha,
            "caption": clip.caption,
        }
    )
    _narration_state["busy_until"] = time.monotonic() + clip.duration + _INTER_BEAT_GAP_MS / 1000


def settle(page: Page) -> None:
    """Hold until the line currently being spoken has finished.

    Only needed when the next thing on screen would otherwise arrive before the
    sentence describing it does — the script is free to keep acting under the
    voice the rest of the time.
    """
    remaining_ms = int((_narration_state["busy_until"] - time.monotonic()) * 1000)
    if remaining_ms > 0:
        pace(page, remaining_ms)


def smooth_scroll(page: Page, locator: Locator, pause_ms: int = 1200) -> None:
    """Smoothly pan an element to the centre of the viewport, then pause.

    Instant ``scrollIntoView`` jumps read as jarring on the recording; a smooth
    animation plus a pause lets the pan land before the next action (and before
    any ``bounding_box`` read that follows).
    """
    locator.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, pause_ms)


def hover_and_click(page: Page, locator: Locator, pause_ms: int = 250) -> None:
    """Move cursor visibly to the element center, pause, then click.

    This ensures the cursor dot and click ripple are captured by the video
    encoder — without the pause Playwright clicks happen in a single frame.
    An off-viewport target is smooth-panned into view first; Playwright's own
    pre-click auto-scroll is an instant jump the camera would catch.
    """
    scrolled = locator.evaluate(
        """el => {
            const r = el.getBoundingClientRect();
            if (r.top < 0 || r.bottom > window.innerHeight) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return true;
            }
            return false;
        }"""
    )
    if scrolled:
        page.wait_for_timeout(700)
    box = locator.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(pause_ms)
    locator.click()


def type_text(locator: Locator, text: str, delay: int = 80) -> None:
    """Type text character-by-character for a human-like feel."""
    locator.press_sequentially(text, delay=delay)


def dismiss_toasts(page: Page) -> None:
    """Remove all toast notifications from the screen."""
    page.evaluate("""() => {
        const container = document.getElementById('toast-container');
        if (container) {
            const data = window.Alpine?.$data(container);
            if (data) data.toasts = [];
        }
        document.querySelectorAll('.tw-toast').forEach(el => el.remove());
    }""")


def auto_dismiss_toasts(page: Page) -> None:
    """Continuously drain toast notifications for the lifetime of the page.

    Some recordings cross routes that lazy-load HTMX panels which fail
    in the screencast environment (no real S3, no Stripe, no
    notification websocket). The resulting "Failed to load …" toasts
    have nothing to do with the flow being recorded but pile up in
    frame and distract the viewer. This helper installs a
    ``MutationObserver`` on the toast container that drains any new
    toast as soon as it is appended — observers fire only on actual
    DOM mutations, so it adds zero polling overhead vs. a
    ``setInterval(..., 100)`` loop.

    The observer is registered as an ``init_script``, so every
    document the recording navigates through gets a fresh observer
    automatically. The observer is bound to the page and is garbage
    collected with it; no explicit clear is required.
    """
    page.add_init_script(
        """
        (() => {
            const drain = (root) => {
                const container = root.getElementById
                    ? root.getElementById('toast-container')
                    : null;
                if (container) {
                    const data = window.Alpine?.$data(container);
                    if (data && Array.isArray(data.toasts)) data.toasts = [];
                }
                root.querySelectorAll?.('.tw-toast').forEach((el) => el.remove());
            };
            const start = () => {
                drain(document);
                const obs = new MutationObserver((muts) => {
                    for (const m of muts) {
                        if (m.addedNodes && m.addedNodes.length) {
                            drain(document);
                            return;
                        }
                    }
                });
                obs.observe(document.body, { childList: true, subtree: true });
            };
            if (document.body) start();
            else document.addEventListener('DOMContentLoaded', start, { once: true });
        })();
        """
    )


def rewrite_localhost_urls(page: Page) -> None:
    """Replace localhost URLs in the visible DOM with app.sbomify.com.

    Used in screencasts where the trust center public URL or CNAME target
    would otherwise show the test server address.
    """
    page.evaluate("""() => {
        const walk = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                node.textContent = node.textContent
                    .replace(/http:\\/\\/localhost:\\d+/g, 'https://app.sbomify.com')
                    .replace(/\\blocalhost\\b/g, 'app.sbomify.com');
            }
            for (const child of node.childNodes) walk(child);
        };
        walk(document.body);
    }""")


# ---------------------------------------------------------------------------
# Narration — chapter title cards and lower-third captions
#
# The FAQ-length recordings need no narration: each shows one action and the
# surrounding FAQ text carries the explanation. A marketplace walkthrough has
# no surrounding text — it plays cold, often muted, next to a listing. These
# two helpers carry the story instead.
#
# Both build their DOM node-by-node and set every dynamic string via
# ``textContent`` rather than ``innerHTML``, matching the existing overlay in
# ``oidc_trusted_publishing.py`` — keeps automated security linters quiet even
# though all content originates in these scripts.
# ---------------------------------------------------------------------------

TITLE_CARD_ID = "__walkthrough-title-card"
CAPTION_ID = "__walkthrough-caption"


def title_card(page: Page, eyebrow: str, title: str, hold_ms: int = 2600) -> None:
    """Cover the viewport with a branded chapter card, hold, then fade out.

    Used between chapters of the long tour so the viewer gets a beat to
    reset before the next surface appears. ``eyebrow`` is the small label
    above the title (e.g. ``"Chapter 2"``).
    """
    page.evaluate(
        """(payload) => {
            const existing = document.getElementById(payload.id);
            if (existing) existing.remove();

            const card = document.createElement('div');
            card.id = payload.id;
            card.style.cssText = `
                position: fixed; inset: 0; z-index: 2147483646;
                display: flex; flex-direction: column;
                justify-content: center; align-items: center; gap: 14px;
                background: ${payload.bg};
                font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
                opacity: 0; transition: opacity 420ms ease;
            `;

            const eyebrow = document.createElement('div');
            eyebrow.style.cssText = 'font-size:15px; font-weight:600;' +
                ' letter-spacing:0.22em; text-transform:uppercase;' +
                ' color:#818cf8;';
            eyebrow.textContent = payload.eyebrow;

            const title = document.createElement('div');
            title.style.cssText = 'font-size:52px; font-weight:700;' +
                ' color:#f8fafc; letter-spacing:-0.02em; text-align:center;' +
                ' max-width:70%; line-height:1.15;';
            title.textContent = payload.title;

            const rule = document.createElement('div');
            rule.style.cssText = 'width:72px; height:3px; border-radius:2px;' +
                ' background:linear-gradient(90deg,#6366f1,#a78bfa);';

            card.appendChild(eyebrow);
            card.appendChild(title);
            card.appendChild(rule);
            document.body.appendChild(card);
            requestAnimationFrame(() => { card.style.opacity = '1'; });
        }""",
        {"id": TITLE_CARD_ID, "eyebrow": eyebrow, "title": title, "bg": APP_BG_COLOR},
    )
    page.wait_for_timeout(hold_ms)
    page.evaluate(
        """(id) => {
            const card = document.getElementById(id);
            if (!card) return;
            card.style.opacity = '0';
            setTimeout(() => card.remove(), 460);
        }""",
        TITLE_CARD_ID,
    )
    page.wait_for_timeout(500)


def caption(page: Page, text: str) -> None:
    """Show (or update) a lower-third caption explaining the current step.

    Anchored bottom-centre and ``pointer-events:none`` so it never intercepts
    a click the recording is about to make. Call :func:`clear_caption` before
    a navigation — the caption lives in the current document and would
    otherwise vanish on its own mid-sentence.

    A recording that has a narration script says this out loud instead, so the
    lower-third is suppressed there rather than duplicating the voiceover on
    screen.  Nothing at the call sites has to change.
    """
    if _narration_state["narrator"] is not None:
        return

    page.evaluate(
        """(payload) => {
            let bar = document.getElementById(payload.id);
            if (!bar) {
                bar = document.createElement('div');
                bar.id = payload.id;
                bar.style.cssText = `
                    position: fixed; bottom: 40px; left: 50%;
                    transform: translateX(-50%);
                    z-index: 2147483645; pointer-events: none;
                    max-width: 74%; padding: 14px 26px;
                    border-radius: 12px;
                    background: rgba(10, 10, 35, 0.92);
                    border: 1px solid rgba(129, 140, 248, 0.28);
                    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.45);
                    color: #f1f5f9; font-size: 19px; line-height: 1.45;
                    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
                    text-align: center;
                    opacity: 0; transition: opacity 260ms ease;
                `;
                document.body.appendChild(bar);
            }
            bar.textContent = payload.text;
            requestAnimationFrame(() => { bar.style.opacity = '1'; });
        }""",
        {"id": CAPTION_ID, "text": text},
    )
    page.wait_for_timeout(260)


def clear_caption(page: Page) -> None:
    """Remove the lower-third caption if one is showing."""
    page.evaluate(f"document.getElementById({CAPTION_ID!r})?.remove()")


# ---------------------------------------------------------------------------
# Reusable navigation sequences
# ---------------------------------------------------------------------------


def mock_vuln_trends(page: Page) -> None:
    """Intercept the vulnerability-trends HTMX endpoint with realistic mock data."""
    page.route(
        "**/vulnerability-trends/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body=MOCK_VULN_TRENDS_HTML),
    )


def start_on_dashboard(page: Page, pause_ms: int = 1500) -> None:
    """Navigate to the dashboard and wait for it to load."""
    page.goto("/dashboard")
    page.wait_for_load_state("networkidle")
    pace(page, pause_ms)


def navigate_to_settings(page: Page) -> None:
    """Click the sidebar Settings link and wait for the page to load."""
    settings_link = page.get_by_role("link", name="Settings")
    hover_and_click(page, settings_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_components(page: Page) -> None:
    """Click the sidebar Components link and wait for the page to load."""
    components_link = page.get_by_role("link", name="Components")
    hover_and_click(page, components_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_products(page: Page) -> None:
    """Click the sidebar Products link and wait for the page to load."""
    products_link = page.get_by_role("link", name="Products")
    hover_and_click(page, products_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_releases(page: Page) -> None:
    """Click the sidebar Releases link and wait for the page to load."""
    releases_link = page.get_by_role("link", name="Releases")
    hover_and_click(page, releases_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_plugins(page: Page) -> None:
    """Click the sidebar Plugins link and wait for the page to load."""
    plugins_link = page.get_by_role("link", name="Plugins")
    hover_and_click(page, plugins_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)


def navigate_to_trust_center_tab(page: Page) -> None:
    """Navigate to Settings, then click the Trust Center tab.

    The settings tabs used to be in-page panels switched by a ``data-tab``
    attribute; they are now real links to ``/settings/<tab>``, so the tab is
    matched by its href and the click is a navigation.
    """
    navigate_to_settings(page)
    trust_center_tab = page.locator("a.settings-tab[href$='/trust-center']")
    trust_center_tab.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, trust_center_tab)
    page.wait_for_load_state("networkidle")
    pace(page, 800)


def click_into_row(page: Page, name: str) -> None:
    """Click a table row containing the given name."""
    row = page.locator("tr", has=page.locator(f"span:text-is('{name}')"))
    row.first.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, row.first)
    page.wait_for_load_state("networkidle")
    pace(page, 1000)


def open_new_from_navbar(page: Page, item: str) -> None:
    """Open a create page from the navbar's New menu.

    Product and component creation are pages now (``/products/new/``,
    ``/components/new/``) rather than modals, so there is no
    ``open-add-*-modal`` event to dispatch.  The navbar menu is the entry
    point that looks the same whether the table behind it is empty or full —
    the empty state's "Create Your First …" button only exists while the
    workspace has nothing in it, and it was that empty-vs-populated split
    that broke the assignment opener before.
    """
    new_btn = page.get_by_role("button", name="Create new item")
    new_btn.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, new_btn)
    pace(page, 400)

    menu_item = page.get_by_role("menuitem", name=item, exact=True)
    menu_item.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, menu_item)
    page.wait_for_load_state("networkidle")
    pace(page, 600)


def choose_component_type(page: Page, value: str) -> None:
    """Pick a component type on the New Component page.

    The type is choice tiles rather than a select, and each tile's radio is
    visually hidden, so the click has to land on the label that wraps it.
    """
    tile = page.locator("label").filter(has=page.locator(f"input[name='component_type'][value='{value}']"))
    tile.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, tile)
    pace(page, 500)


def create_global_document_component(page: Page, name: str) -> None:
    """Create a workspace-wide Document component from the New Component page."""
    open_new_from_navbar(page, "Component")

    name_input = page.locator("input#name")
    name_input.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, name)
    pace(page, 500)

    # Document type first: the workspace-wide step only renders while it is
    # picked, and its checkbox stays disabled under any other type.
    choose_component_type(page, "document")

    global_checkbox = page.locator("#is_global")
    global_checkbox.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, global_checkbox)
    pace(page, 600)

    hover_and_click(page, page.get_by_role("button", name="Create component"))
    page.wait_for_load_state("networkidle")
    pace(page, 800)


def enable_and_save_plugin(page: Page, plugin_slug: str) -> None:
    """Navigate to Plugins, toggle the given plugin on, and save.

    Shared by the per-plugin FAQ screencasts in plugin_enablement.py.
    """
    navigate_to_plugins(page)

    page.locator("#plugin-settings-form").wait_for(state="visible", timeout=15_000)
    pace(page, 1500)

    # Attribute selector (not #id) because some plugin slugs contain dots
    # (e.g. bsi-tr03183-v2.1-compliance) which have CSS-special meaning.
    toggle = page.locator(f"[id='plugin-{plugin_slug}']")
    toggle.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 600)
    hover_and_click(page, toggle)
    pace(page, 1200)

    save_btn = page.locator("#plugin-settings-form button[type='submit']")
    save_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 500)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 2000)


def enable_and_configure_trust_center(page: Page) -> None:
    """Enable the trust center and configure a custom domain.

    Shared between trust_center_setup and tea_enabling screencasts.
    """
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    hover_and_click(page, toggle)

    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 2000)

    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    domain_input.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 800)

    hover_and_click(page, domain_input)
    pace(page, 400)
    type_text(domain_input, "trust.piedpiper.com")
    pace(page, 800)

    save_btn = page.locator("button:has-text('Save Domain')")
    save_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    rewrite_localhost_urls(page)
    pace(page, 1500)


# ---------------------------------------------------------------------------
# Mock HTML for the vulnerability-trends HTMX widget
# ---------------------------------------------------------------------------

MOCK_VULN_TRENDS_HTML = """\
<div class="p-6"
     x-cloak
     x-data="{ chartInstance: null, activeChart: 'timeline' }"
     x-init="$nextTick(() => { initVulnerabilityChart($el) })">
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div class="flex items-center gap-2">
            <i class="fas fa-shield-alt text-primary"></i>
            <h4 class="text-lg font-semibold text-text m-0">Vulnerability Trends</h4>
        </div>
        <div class="flex flex-wrap items-center gap-4">
            <div class="flex items-center gap-2">
                <label class="text-xs text-text-muted uppercase tracking-wider">Product</label>
                <select class="tw-form-input w-auto py-1.5 text-sm" disabled>
                    <option>All Products</option>
                </select>
            </div>
            <div class="flex items-center gap-2">
                <label class="text-xs text-text-muted uppercase tracking-wider">Time Range</label>
                <select class="tw-form-input w-auto py-1.5 text-sm" disabled>
                    <option>30 Days</option>
                </select>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        <div class="flex items-center gap-3 p-3 rounded-lg bg-primary/5 border border-primary/10">
            <div class="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-bug text-primary"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-text">47</span>
                <span class="block text-xs text-text-muted">Total</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-red-500/5 border border-red-500/10">
            <div class="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-exclamation-circle text-red-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-red-600">3</span>
                <span class="block text-xs text-text-muted">Critical</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-orange-500/5 border border-orange-500/10">
            <div class="w-10 h-10 rounded-full bg-orange-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-exclamation-triangle text-orange-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-orange-600">8</span>
                <span class="block text-xs text-text-muted">High</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/10">
            <div class="w-10 h-10 rounded-full bg-yellow-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-minus-circle text-yellow-600"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-yellow-700">15</span>
                <span class="block text-xs text-text-muted">Medium</span>
            </div>
        </div>
        <div class="flex items-center gap-3 p-3 rounded-lg bg-cyan-500/5 border border-cyan-500/10">
            <div class="w-10 h-10 rounded-full bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-info-circle text-cyan-500"></i>
            </div>
            <div>
                <span class="text-xl font-bold text-cyan-600">21</span>
                <span class="block text-xs text-text-muted">Low</span>
            </div>
        </div>
    </div>

    <div class="flex flex-col items-center mb-4">
        <div class="inline-flex rounded-lg border border-border overflow-hidden" role="group">
            <button type="button"
                    class="px-4 py-2 text-sm font-medium transition-colors"
                    :class="activeChart === 'timeline' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-line mr-1"></i>Timeline
            </button>
            <button type="button"
                    class="px-4 py-2 text-sm font-medium border-l border-border transition-colors"
                    :class="activeChart === 'severity' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-bar mr-1"></i>Severity
            </button>
            <button type="button"
                    class="px-4 py-2 text-sm font-medium border-l border-border transition-colors"
                    :class="activeChart === 'providers' ? 'bg-primary text-white' : 'bg-surface text-text hover:bg-background'">
                <i class="fas fa-chart-pie mr-1"></i>Providers
            </button>
        </div>
    </div>

    <div class="h-[300px] mb-6">
        <canvas class="vulnerability-chart-canvas"
                data-labels='["Jan 27","Jan 29","Jan 31","Feb 2","Feb 4","Feb 6","Feb 8","Feb 10","Feb 12","Feb 14","Feb 16","Feb 18","Feb 20","Feb 22","Feb 24"]'
                data-critical='[1,2,1,2,1,3,2,3,2,2,3,2,3,3,3]'
                data-high='[3,4,3,5,4,5,6,5,7,6,7,6,8,7,8]'
                data-medium='[8,7,9,8,10,9,11,10,12,11,13,12,14,13,15]'
                data-low='[12,11,13,12,14,15,16,17,18,17,19,18,20,19,21]'
                data-severity-labels='["Critical","High","Medium","Low"]'
                data-severity-values='[3,8,15,21]'
                data-provider-labels='["osv","dependency_track"]'
                data-provider-values='[28,19]'></canvas>
    </div>
</div>
"""


@pytest.fixture(scope="session")
def playwright() -> Generator[Playwright, Any, None]:
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Generator[Browser, Any, None]:
    browser_instance = playwright.chromium.connect_over_cdp(settings.PLAYWRIGHT_CDP_ENDPOINT)
    yield browser_instance
    browser_instance.close()


@pytest.fixture
def browser_base_url(live_server) -> str:
    original_hostname = urlparse(live_server.url).hostname
    return live_server.url.replace(
        original_hostname,
        getattr(settings, "PLAYWRIGHT_DJANGO_HOST", original_hostname),
    )


@pytest.fixture
def deletable_team(
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
) -> Team:
    """Unmark the team as default so the delete button is enabled."""
    Member.objects.filter(user=sample_user, team=team_with_business_plan).update(is_default_team=False)
    return team_with_business_plan


# ---------------------------------------------------------------------------
# ORM fixtures — pre-create the Pied Piper hierarchy for screencasts that
# need it as a precondition rather than the thing being demonstrated.
# ---------------------------------------------------------------------------

PIED_PIPER_COMPONENTS = [
    "Compression Core Library",
    "Web Dashboard",
    "REST API Service",
    "Data Pipeline Worker",
]

PIED_PIPER_PRODUCT_NAME = "Pied Piper Compression Engine"


@pytest.fixture
def pied_piper_product(deletable_team: Team) -> dict:
    """Create the Pied Piper hierarchy via ORM (4 components attached to 1 product).

    Returns dict with keys: product, components (dict).
    """
    team = deletable_team

    components = {name: Component.objects.create(team=team, name=name) for name in PIED_PIPER_COMPONENTS}

    product = Product.objects.create(
        team=team,
        name=PIED_PIPER_PRODUCT_NAME,
        description="Middle-out compression platform for enterprise data optimization",
    )
    product.components.set(components.values())

    return {"product": product, "components": components}


@pytest.fixture
def pied_piper_with_sboms(pied_piper_product: dict) -> dict:
    """Extend pied_piper_product with a CycloneDX SBOM record per component.

    Returns same dict plus 'sboms' key.
    Note: creating SBOMs triggers a signal that auto-creates a 'latest' Release.
    """
    sboms = {}
    for name, component in pied_piper_product["components"].items():
        sbom = SBOM.objects.create(
            name=f"com.piedpiper/{component.name.lower().replace(' ', '-')}",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename=f"{component.name.lower().replace(' ', '-')}.json",
            source="api",
            component=component,
        )
        sboms[name] = sbom

    return {**pied_piper_product, "sboms": sboms}


def setup_browser_session(
    browser_base_url: str,
    sample_user: AbstractBaseUser,
    team: Team,
) -> dict[str, Any]:
    # A team with an active business subscription has finished plan selection.
    # The shared fixture leaves ``has_selected_billing_plan`` at its model
    # default (False), which makes the dashboard (and other authenticated
    # pages) redirect into the onboarding plan-selection wizard mid-recording.
    if not team.has_selected_billing_plan:
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_selected_billing_plan"])

    django_client = Client()
    setup_authenticated_client_session(django_client, team, sample_user)

    session = django_client.session
    session["current_team"]["has_completed_wizard"] = True
    session["current_team"]["billing_plan"] = team.billing_plan
    session.save()

    return {
        "name": "sessionid",
        "value": session.session_key,
        "domain": urlparse(browser_base_url).hostname,
        "path": "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


@pytest.fixture
def recording_context(
    browser: Browser,
    browser_base_url: str,
    sample_user: AbstractBaseUser,
    deletable_team: Team,
) -> Generator[BrowserContext, Any, None]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    context = browser.new_context(
        base_url=browser_base_url,
        viewport={"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
        device_scale_factor=2,
        record_video_dir=str(OUTPUT_DIR),
        record_video_size={"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
    )

    # Prevent white flash — set background color before page content loads
    context.add_init_script(f"document.documentElement.style.backgroundColor = '{APP_BG_COLOR}';")

    # Show a cursor dot + click ripple in the recording.
    # Read the file content explicitly (path= can fail with remote CDP).
    click_js = CLICK_INDICATOR_JS.read_text()
    context.add_init_script(click_js)

    session_cookie = setup_browser_session(browser_base_url, sample_user, deletable_team)
    context.add_cookies([session_cookie])

    yield context

    context.close()


@pytest.fixture
def recording_page(
    request: pytest.FixtureRequest,
    recording_context: BrowserContext,
) -> Generator[Page, Any, None]:
    page = recording_context.new_page()

    # Video capture starts with the page, so this is the zero point every
    # narration offset — and every subtitle cue — is measured against.
    _narration_state["t0"] = time.monotonic()

    # Replace the white about:blank with a branded splash screen.  This is
    # visible while the first real navigation loads.
    page.set_content(SPLASH_HTML, wait_until="commit")

    recording_name = _recording_name(request)

    narrator = Narrator.for_recording(recording_name)
    _narration_state["narrator"] = narrator
    _narration_state["beats"] = []
    _narration_state["busy_until"] = 0.0
    if narrator is not None:
        # Synthesize the opening line while the splash screen and the first
        # navigation are still on screen, so its latency never reaches the video.
        narrator.prefetch(narrator.beat_keys[0])

    screenshot_dir = OUTPUT_DIR / "screenshots" / recording_name
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    hero_dir = screenshot_dir / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)
    _screenshot_state["dir"] = screenshot_dir
    _screenshot_state["hero_dir"] = hero_dir
    _screenshot_state["last_time"] = 0.0
    _screenshot_state["counter"] = 0

    try:
        yield page
    finally:
        _screenshot_state["dir"] = None
        _screenshot_state["hero_dir"] = None

    # Let the closing line finish before capture stops, or it gets clipped.
    if narrator is not None:
        settle(page)

    wall_duration_ms = (time.monotonic() - _narration_state["t0"]) * 1000

    # Grab the video handle, close the page (finalizes recording),
    # then save to a meaningful filename.
    video = page.video
    page.close()

    if video:
        final_path = OUTPUT_DIR / f"{recording_name}.webm"
        video.save_as(str(final_path))

    if narrator is not None:
        _write_narration_manifest(recording_name, narrator, wall_duration_ms, _test_passed(request))


def _write_narration_manifest(
    recording_name: str,
    narrator: Narrator,
    wall_duration_ms: float,
    passed: bool,
) -> None:
    """Record where each spoken line landed.

    ``mux_narration`` reads this to lay the audio back down at the same offsets
    and to cut the WebVTT subtitle file from the same timings.
    """
    spoken = [beat["key"] for beat in _narration_state["beats"]]

    # Only meaningful for a recording that ran to completion — after a failure
    # the unspoken beats are a symptom, not the cause.
    if passed and (unused := [key for key in narrator.beat_keys if key not in spoken]):
        raise AssertionError(f"{recording_name}: narration beats never spoken: {', '.join(unused)}")

    if narrator.blocked_beats:
        print(
            f"[narration] {recording_name}: synthesis blocked the recording at "
            f"{', '.join(narrator.blocked_beats)} — prefetch is not keeping up",
            file=sys.stderr,
        )

    manifest = OUTPUT_DIR / f"{recording_name}.narration.json"
    manifest.write_text(
        json.dumps(
            {
                "recording": recording_name,
                "wall_duration_ms": round(wall_duration_ms, 1),
                "beats": _narration_state["beats"],
            },
            indent=2,
        )
        + "\n"
    )
