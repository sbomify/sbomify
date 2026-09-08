import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

import wayland_capture
from narrator import Narrator
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
    team_with_business_plan,  # noqa: F401
)
from sbomify.apps.core.object_store import S3Client
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
SMOOTH_SCROLL_JS = Path(__file__).parent / "smooth_scroll.js"

# The current brand mark: the bar emblem plus wordmark, same artwork the app
# renders inline from core/components/brand/logo.html.j2 (identical viewBox,
# 571.45x107). The white variant is the one for a dark ground.
#
# NOT logo-circle.svg. That is the retired mark — nothing in the app references
# it any more, and the splash was still opening every recording on it.
LOGO_SVG = Path(__file__).parent.parent / "sbomify" / "static" / "img" / "sbomify-white.svg"

# Match the app's dark-mode background so the recording never flashes white.
APP_BG_COLOR = "#0A0A23"

# Splash screen shown while the first real page loads. The logo SVG is read
# once at import time and embedded directly in the HTML. It carries a viewBox
# and no width/height, so it scales to whatever box it is given.
_logo_svg_content = LOGO_SVG.read_text() if LOGO_SVG.exists() else ""
SPLASH_HTML = f"""\
<html style="background:{APP_BG_COLOR}">
<body style="margin:0;display:flex;justify-content:center;align-items:center;
             min-height:100vh;background:{APP_BG_COLOR}">
  <div style="opacity:0.35;width:340px">
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
    _log_scene(page)
    wall_ms = ms
    if ms >= _SCREENSHOT_MIN_PACE_MS:
        started = time.monotonic()
        _maybe_capture_screenshot(page)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        wall_ms = max(0, wall_ms - elapsed_ms)
    page.wait_for_timeout(wall_ms)


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
    # The beat currently speaking, so the *next* narrate() can close it out and
    # record how long its visual work really took.  Audio duration is known up
    # front; visual duration is not, and nothing compared the two.
    "open_beat": None,
    # Every surface the recording landed on, as (offset_ms, url).  The manifest
    # used to describe only the audio timeline, so a line that started on the
    # right page and finished three pages later measured as perfectly paced.
    # `audit_timing.py` joins the two.
    "scenes": [],
}


def _short_url(url: str) -> str:
    """Path only, with ids collapsed, so scenes compare across runs."""
    path = urlparse(url).path.rstrip("/") or "/"
    return re.sub(r"/[A-Za-z0-9]{10,}(?=/|$)", "/<id>", path)


def _log_scene(page: Page) -> None:
    """Note the current surface, if it changed since the last note."""
    if _narration_state["narrator"] is None:
        return
    url = _short_url(page.url)
    scenes = _narration_state["scenes"]
    if scenes and scenes[-1]["url"] == url:
        return
    offset_ms = (time.monotonic() - _narration_state["t0"]) * 1000
    scenes.append({"offset_ms": round(offset_ms, 1), "url": url})


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
            # Per-character speech timing, so mux_narration can cut subtitle
            # cues at the moment each word is actually spoken.
            "char_times": [[c, a, b] for c, a, b in clip.char_times] if clip.char_times else None,
            # What was on screen when the line started. Compared against the
            # scene log by `audit_timing.py` to find lines that begin on one
            # surface and end on another — the failure the manifest alone
            # cannot show, because it records only the audio timeline.
            "url": _short_url(page.url),
        }
    )
    # The line occupies clip.duration of *finished* video, so the recording
    # has to sit on it for that much wall clock times the slowdown.
    _narration_state["busy_until"] = time.monotonic() + clip.duration + _INTER_BEAT_GAP_MS / 1000
    _narration_state["open_beat"] = {"entry": _narration_state["beats"][-1], "started": time.monotonic()}


def _close_open_beat() -> None:
    """Record how long the open beat's visual work took, before it is held out.

    Called at the top of :func:`settle`, which is the moment the script has
    finished acting and is about to wait for the voice.  The gap between this
    and the clip duration is the whole timing problem in one number:

        slack > 0   the line outruns the picture; it freezes for that long
        slack < 0   the picture outruns the line; that much silence

    Both were previously invisible and had to be found by watching.
    """
    open_beat = _narration_state.get("open_beat")
    if not open_beat:
        return
    visual_ms = (time.monotonic() - open_beat["started"]) * 1000
    entry = open_beat["entry"]
    entry["visual_ms"] = round(visual_ms, 1)
    entry["slack_ms"] = round(entry["duration"] * 1000 - visual_ms, 1)
    _narration_state["open_beat"] = None


def settle(page: Page) -> None:
    """Hold until the line currently being spoken has finished.

    Only needed when the next thing on screen would otherwise arrive before the
    sentence describing it does — the script is free to keep acting under the
    voice the rest of the time.
    """
    _close_open_beat()
    remaining_ms = int((_narration_state["busy_until"] - time.monotonic()) * 1000)
    if remaining_ms > 0:
        # busy_until is already wall clock; pace() scales what it is given, so
        # hand it the finished-timeline figure or the wait is squared.
        pace(page, remaining_ms)


def smooth_scroll(page: Page, locator: Locator, pause_ms: int = 1200) -> None:
    """Smoothly pan an element to the centre of the viewport, then pause.

    Instant ``scrollIntoView`` jumps read as jarring on the recording; a smooth
    animation plus a pause lets the pan land before the next action (and before
    any ``bounding_box`` read that follows).
    """
    locator.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, pause_ms)

    # Then make sure it actually arrived.
    #
    # The pan is a *preference*, not a promise. It runs inside the page and has
    # been measured not arriving, and when that happens the thing the line is
    # describing sits off-screen with nothing to say so. Verify, and correct.
    _hold_in_frame(page, locator)


def _hold_in_frame(page: Page, locator: Locator, attempts: int = 5) -> None:
    """Scroll ``locator`` into view and keep it there.

    Two things make this harder than one assignment.

    The in-page pan has been measured not arriving, while a plain ``scrollTop``
    assignment in the same document worked and requestAnimationFrame ticked 62
    times a second.

    And after an HTMX save the panel re-renders *asynchronously*, putting the
    document back at the top a moment after the scroll succeeded — so a check
    taken immediately after scrolling passes and the recording still shows the
    top of the page. Every earlier attempt at this verified green that way.

    So: assign directly, wait, and re-check from Python. Repeat until it holds.
    """
    for _ in range(attempts):
        locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                // Something taller than the viewport can never sit wholly
                // inside it; for those, having the top in view is the goal.
                const fits = r.height <= window.innerHeight;
                const ok = fits ? (r.top >= 0 && r.bottom <= window.innerHeight)
                                : (r.top >= 0 && r.top <= window.innerHeight * 0.4);
                if (ok) return;
                // Stop the eased pan first: it reassigns scrollTop from its own
                // progress on every frame and would undo this immediately.
                if (window.__sbomifyCancelScroll) window.__sbomifyCancelScroll();
                const s = document.scrollingElement || document.documentElement;
                const max = s.scrollHeight - window.innerHeight;
                const want = s.scrollTop + r.top - (window.innerHeight - r.height) / 2;
                s.scrollTop = Math.max(0, Math.min(max, want));
            }"""
        )
        page.wait_for_timeout(350)
        # Ask the page, not Playwright. `bounding_box()` and
        # `getBoundingClientRect()` disagreed here, and the page's own view of
        # its layout is the one that decides what the camera sees.
        if locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                const fits = r.height <= window.innerHeight;
                return fits ? (r.top >= 0 && r.bottom <= window.innerHeight)
                            : (r.top >= 0 && r.top <= window.innerHeight * 0.4);
            }"""
        ):
            return
    raise AssertionError(f"could not hold {locator} in frame after {attempts} attempts")


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
        # Wait out the whole pan, not half of it. `smooth_scroll.js` runs the
        # pan for `__sbomifyScrollDuration`; a flat 700ms let the cursor land
        # while the page was still moving under it.
        page.wait_for_timeout(1400 + 120)
    box = locator.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(pause_ms)
    locator.click()


def type_text(locator: Locator, text: str, delay: int = 80, clear: bool = False) -> None:
    """Type text character-by-character for a human-like feel.

    ``clear`` empties the field first. Pass it for any input that arrives with
    a value already in it: typing appends, so the document upload's version box
    (Alpine defaults it to ``1.0``) filmed itself becoming ``1.02024``, which is
    then what the row in the Documents table read.
    """
    if clear:
        locator.fill("")
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


# Where the platform itself lives: what a CNAME points *at*, and the right
# host for anything rendered on an admin screen.
PLATFORM_DOMAIN = "app.sbomify.com"

# The workspace's own trust-center hostname, the one the tour configures on
# camera in chapter 4.
CUSTOM_TRUST_DOMAIN = "trust.piedpiper.com"


def rewrite_localhost_urls(page: Page, domain: str = PLATFORM_DOMAIN) -> None:
    """Replace localhost URLs in the visible DOM with a real-looking host.

    Used in screencasts where the trust center public URL or CNAME target
    would otherwise show the test server address.

    ``domain`` matters, and the default is not always right.  Two different
    hosts are correct in two different places:

    * the **CNAME target** on the settings page is genuinely ours, so those
      pages keep ``app.sbomify.com``;
    * the **public trust centre** is served from the workspace's own domain
      once configured, so it must read ``trust.piedpiper.com``.

    Rewriting everything to ours meant the tour typed ``trust.piedpiper.com``
    into the custom-domain field, saved it, and then showed the finished page
    on ``app.sbomify.com`` — contradicting the line it had just spoken about
    the link carrying your name rather than ours.
    """
    page.evaluate(
        """(domain) => {
        const walk = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                node.textContent = node.textContent
                    .replace(/http:\\/\\/localhost:\\d+/g, 'https://' + domain)
                    .replace(/\\blocalhost\\b/g, domain);
            }
            for (const child of node.childNodes) walk(child);
        };
        walk(document.body);
    }""",
        domain,
    )


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


def title_card(page: Page, eyebrow: str, title: str, hold_ms: int = 3200, linger: bool = False) -> None:
    """Cover the viewport with a branded chapter card, hold, then fade out.

    Used between chapters of the long tour so the viewer gets a beat to
    reset before the next surface appears. ``eyebrow`` is the small label
    above the title (e.g. ``"Chapter 2"``).

    ``linger`` leaves the card up instead of fading it, for the closing card:
    its line is the longest in the tour, so a fixed hold dropped the card —
    and the sbomify.com the voice is reading out — twelve seconds before the
    recording ended, leaving the call to action spoken over a product page.
    The caller finishes with :func:`settle`, which waits for the voice, so the
    video ends on the card.
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

            // The brand-fronted cards (the opener and the closing CTA) carry
            // the real wordmark; chapter cards keep the lettered eyebrow.
            let eyebrow;
            if (payload.logo) {
                eyebrow = document.createElement('div');
                eyebrow.style.cssText = 'width:300px; margin-bottom:10px;';
                eyebrow.innerHTML = payload.logo;
            } else {
                eyebrow = document.createElement('div');
                eyebrow.style.cssText = 'font-size:15px; font-weight:600;' +
                    ' letter-spacing:0.22em; text-transform:uppercase;' +
                    ' color:#818cf8;';
                eyebrow.textContent = payload.eyebrow;
            }

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
            // The card is `position: fixed; inset: 0`, which covers the layout
            // viewport but *not* the scrollbar beside it. Over a long page the
            // strip stays lit down the right edge and, because it takes width,
            // shoves the card's centred content left of frame. The chapter
            // cards sit over app screens that manage their own scrolling and
            // never showed it; the closing card sits over the public trust
            // centre, which does scroll, and showed both.
            document.documentElement.dataset.sbomifyPrevOverflow =
                document.documentElement.style.overflow || '';
            document.documentElement.style.overflow = 'hidden';
            requestAnimationFrame(() => { card.style.opacity = '1'; });
        }""",
        {
            "id": TITLE_CARD_ID,
            "eyebrow": eyebrow,
            "title": title,
            "bg": APP_BG_COLOR,
            "logo": _logo_svg_content if eyebrow.strip().lower() == "sbomify" else "",
        },
    )
    page.wait_for_timeout(hold_ms)
    if linger:
        return
    page.evaluate(
        """(payload) => {
            const card = document.getElementById(payload.id);
            if (!card) return;
            card.style.opacity = '0';
            setTimeout(() => {
                card.remove();
                // Restore whatever the page had, so hiding the scrollbar for
                // the card cannot change how the surface behind it behaves.
                const root = document.documentElement;
                root.style.overflow = root.dataset.sbomifyPrevOverflow || '';
                delete root.dataset.sbomifyPrevOverflow;
            }, payload.removeAfterMs);
        }""",
        {"id": TITLE_CARD_ID, "removeAfterMs": 460},
    )
    page.wait_for_timeout(500)


def clear_title_card(page: Page) -> None:
    """Fade out and remove a card left up by ``title_card(linger=True)``.

    Lets a caller hold a card for exactly as long as something else takes —
    a narration line, a page load — instead of guessing a duration. The
    opening card was sized with ``hold_ms`` and measured leaving the screen at
    4.75s against a 13s hold, so the tour opened on eleven seconds of dim
    splash logo. Holding until the line is done removes the guess.
    """
    page.evaluate(
        """(payload) => {
            const card = document.getElementById(payload.id);
            if (!card) return;
            card.style.opacity = '0';
            setTimeout(() => {
                card.remove();
                const root = document.documentElement;
                root.style.overflow = root.dataset.sbomifyPrevOverflow || '';
                delete root.dataset.sbomifyPrevOverflow;
            }, payload.removeAfterMs);
        }""",
        {"id": TITLE_CARD_ID, "removeAfterMs": 460},
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
    # The caption's own fade is a CSS transition, and CDP slows those, so the
    # wait has to be scaled to match or the next action starts mid-fade.
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


def navigate_to_advisories(page: Page) -> None:
    """Click the sidebar Security Advisories link and wait for the page."""
    link = page.get_by_role("link", name="Security Advisories")
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
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


def install_dict_backed_s3(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], bytes]:
    """Back :class:`S3Client` with an in-process dict instead of a bucket.

    The screencast compose stack runs no object store, so any recording that
    uploads has to stand in for one. **Always store the bytes rather than
    no-op'ing the write.** Discarding them makes the upload return 201 and the
    recording pass, then anything that reads the file back reports the truth:
    ``vex_upload`` closed on "This VEX document doesn't suppress any
    vulnerabilities" about a document whose whole point is a ``not_affected``
    statement, because the detail page could not read what was never kept.

    Every read path funnels through ``get_file_data`` and every write through
    ``upload_data_as_file``, so patching that pair covers SBOMs, VEX and
    documents. Everything above the object store — the upload endpoints,
    ``derive_vex_suppressions``, ``find_matching_statement`` — keeps running for
    real, so what a viewer sees suppressed was genuinely suppressed.

    Returns the store, for the callers that assert against it.
    """
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: S3Client, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: S3Client, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(S3Client, "upload_data_as_file", _put)
    monkeypatch.setattr(S3Client, "get_file_data", _get)
    return store


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

    # Saving reloads the page, which resets the scroll to the top — so the
    # recording would otherwise close on a list of plugins that are all still
    # off, with the one just enabled somewhere below the fold. Bring it back
    # into view and confirm it really came back on.
    #
    # ``scroll_into_view_if_needed`` rather than a smooth-scroll evaluate():
    # the latter starts an animation that the post-save load then cancels, so
    # the frames showed the top of the list however long we paused afterwards.
    pace(page, 800)
    toggle = page.locator(f"[id='plugin-{plugin_slug}']")
    toggle.wait_for(state="visible", timeout=10_000)
    toggle.scroll_into_view_if_needed(timeout=10_000)
    if not toggle.is_checked():
        raise AssertionError(f"plugin {plugin_slug} did not stay enabled after save")
    pace(page, 2000)


def enable_trust_center(page: Page) -> None:
    """Flip the workspace-visibility toggle that turns the trust centre on."""
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    hover_and_click(page, toggle)

    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 2000)


def configure_custom_domain(page: Page, domain: str = CUSTOM_TRUST_DOMAIN) -> None:
    """Type and save the workspace's own trust-centre hostname.

    Split out from :func:`enable_trust_center` so a narrated tour can put the
    line about serving from your own domain *over* this, rather than after it.

    **The dwell happens before the save, deliberately.** Saving the domain
    scrolls this page back to the top: measured, ``scrollTop = 1200`` reads
    back as 1200 and is 0 again within 600ms, and only after the save — before
    it, a scroll holds indefinitely. So no amount of scrolling afterwards keeps
    the field in frame, which is why three earlier attempts at this shipped
    looking identical to the bug. Playwright's own auto-scroll for the click is
    reverted the same way, so the typing was happening off-screen too.

    Working with that instead of against it: pan to the field, type, and hold
    on the filled-in form while the line plays. The save lands at the end of
    the beat, and the page is free to jump wherever it likes afterwards.
    """
    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, domain_input, 900)

    hover_and_click(page, domain_input)
    pace(page, 400)
    type_text(domain_input, domain)

    # Hold on the completed field: this is the only stretch where the hostname,
    # the CNAME instructions beneath it and a stable scroll position coexist.
    pace(page, 2600)

    save_btn = page.locator("button:has-text('Save Domain')")
    save_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    rewrite_localhost_urls(page)
    pace(page, 800)


def enable_and_configure_trust_center(page: Page) -> None:
    """Both halves, for the recordings that narrate them as one step.

    Shared between trust_center_setup and tea_enabling screencasts.
    """
    enable_trust_center(page)
    configure_custom_domain(page)


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


# Where the browser comes from.
#
# In Docker there is a separate Chromium container and we attach to its CDP
# endpoint. That container has no GPU (`--disable-gpu`, no /dev/dri, inside a
# VM), so Chromium rasterises in software and the CDP screencast delivers 12-16
# unique frames a second no matter what — measured, and unchanged by halving the
# rendered pixel count, so it is a capture ceiling rather than a drawing one.
#
# ``SCREENCAST_LOCAL_BROWSER=1`` launches the browser on the host instead. On a
# machine with a real GPU that is the difference between a stutter and a clean
# pan.
LOCAL_BROWSER = os.environ.get("SCREENCAST_LOCAL_BROWSER", "") not in ("", "0", "false")

# Capture through GNOME's shell recorder instead of Playwright's CDP screencast.
#
# The screencast throttles frame *delivery*: ~6 distinct frames a second
# sustained, padded with duplicates, on a GPU-less VM and on a machine with a
# working GPU alike. GNOME's recorder reads the composited output and measured
# 19.4 distinct frames a second on the same page, 205 of 206 frames unique.
#
# Needs a live Wayland session on the recording machine, so it is opt-in.
WAYLAND_CAPTURE = os.environ.get("SCREENCAST_WAYLAND_CAPTURE", "") not in ("", "0", "false")

# What to ask GNOME for. The pipeline tops out below this on integrated
# graphics — 19.4 measured against a request of 30 — but asking for less caps
# it lower, and asking for more costs nothing.
WAYLAND_CAPTURE_FPS = int(os.environ.get("SCREENCAST_CAPTURE_FPS", "30"))

# Which binary to launch. Playwright refuses to install its bundled Chromium on
# an OS it does not recognise (Ubuntu 26.04 among them), and a system Chrome is
# the better choice on a recording rig anyway: it ships the vendor's GPU
# allow-lists. Point this at the executable, e.g. /usr/bin/google-chrome.
LOCAL_BROWSER_PATH = os.environ.get("SCREENCAST_BROWSER_PATH", "") or None

# **Headless Chromium falls back to SwiftShader even when a GPU is present.**
# Measured on an Intel Alder Lake box with /dev/dri readable and the iris driver
# installed:
#
#   --headless=new                        ANGLE (Google, SwiftShader driver)
#   --headless=new --disable-gpu          ANGLE (Google, SwiftShader driver)
#   --headless=new --use-gl=angle
#                  --use-angle=gl-egl     ANGLE (Intel, Mesa Intel(R) Graphics)
#
# So asking for headless is not enough; the GL backend has to be named. With
# these flags the recording rig needs no console session and no X display.
# Only when a window is actually shown. `--window-position` puts it somewhere
# predictable; `--ozone-platform=wayland` makes it a native Wayland surface
# rather than an Xwayland one, which is what the compositor can hand to the
# recorder. `--no-sandbox` is deliberately absent: it raises Chrome's
# "unsupported command-line flag" infobar, which would sit in frame.
WINDOW_FLAGS = [
    "--ozone-platform=wayland",
    "--window-position=0,0",
    f"--window-size={RECORDING_WIDTH},{RECORDING_HEIGHT}",
    "--no-first-run",
    "--disable-infobars",
]

GPU_FLAGS = [
    "--use-gl=angle",
    "--use-angle=gl-egl",
    "--enable-gpu",
    "--enable-gpu-rasterization",
    "--ignore-gpu-blocklist",
]


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Generator[Browser, Any, None]:
    if LOCAL_BROWSER:
        # Headed when GNOME is doing the capturing, because there has to be a
        # real window on the compositor for it to film. A headless browser
        # draws nowhere: the first attempt at this recorded nothing at all and
        # `window.screenX` was meaningless, so the capture area was refused.
        browser_instance = playwright.chromium.launch(
            headless=not WAYLAND_CAPTURE,
            executable_path=LOCAL_BROWSER_PATH,
            args=GPU_FLAGS + (WINDOW_FLAGS if WAYLAND_CAPTURE else []),
        )
    else:
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

# Version history per component, oldest first: (version, CycloneDX spec, age in
# days). Every component carried exactly one SBOM before this, which made the
# artifacts table a single row — and the walkthrough chapter that shows it is
# called "Every artifact, versioned". One row is not a version history, and it
# argues against the feature the chapter is selling.
#
# The spec version climbs 1.5 -> 1.6 across the history because a real pipeline
# picks up a newer generator over a year, and the table has a Format column
# that shows it. The newest entry is the version the tagged release pins and
# the one the product identifiers carry, so the whole frame agrees.
# Version history per component, oldest first: (version, CycloneDX spec, age in
# days).
#
# Two things this has to get right, because both were wrong and both are
# visible in frame:
#
# 1. **Contiguous within a component.** These rows are *all* the SBOMs the
#    component has, so a gap reads as a missing upload rather than a release
#    that was never cut. The first version of this jumped 1.0.0 -> 1.2.0 ->
#    2.1.0 -> 2.4.0, four holes to anyone who reads SemVer.
#
# 2. **Independent between components.** Every component previously shared one
#    series, so the product page listed "2.4.0" four times and the tagged
#    release pinned 2.4.0 of everything — a library, a web dashboard, an API
#    service and a batch worker all in lockstep, which does not happen. Each
#    now runs its own major and its own cadence: the dashboard is on 3.x and
#    ships fastest, the worker is still pre-1.0.
#
# The core library tracks the product version deliberately: it is the component
# the product is named after, and its newest is what PRODUCT_VERSION pins.
#
# The spec version climbs 1.5 -> 1.6 partway through each history because a real
# pipeline picks up a newer generator over time, and the table shows it.
PIED_PIPER_SBOM_VERSIONS: dict[str, list[tuple[str, str, int]]] = {
    "Compression Core Library": [
        ("2.1.0", "1.5", 194),
        ("2.2.0", "1.5", 96),
        ("2.3.0", "1.6", 38),
        ("2.4.0", "1.6", 9),
    ],
    "Web Dashboard": [
        ("3.7.0", "1.5", 171),
        ("3.8.0", "1.6", 84),
        ("3.9.0", "1.6", 31),
        ("3.10.0", "1.6", 5),
    ],
    "REST API Service": [
        ("1.4.0", "1.5", 209),
        ("1.5.0", "1.5", 112),
        ("1.6.0", "1.6", 45),
        ("1.7.0", "1.6", 12),
    ],
    "Data Pipeline Worker": [
        ("0.9.0", "1.5", 156),
        ("0.10.0", "1.5", 73),
        ("0.11.0", "1.6", 26),
        ("0.12.0", "1.6", 7),
    ],
}


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
    history: dict[str, list[SBOM]] = {}
    now = datetime.now(timezone.utc)

    for name, component in pied_piper_product["components"].items():
        slug = component.name.lower().replace(" ", "-")
        versions = []
        for version, spec, days_ago in PIED_PIPER_SBOM_VERSIONS[name]:
            sbom = SBOM.objects.create(
                name=f"com.piedpiper/{slug}",
                version=version,
                format="cyclonedx",
                format_version=spec,
                sbom_filename=f"{slug}-{version}.json",
                source="api",
                component=component,
            )
            # created_at is auto_now_add, so every row would otherwise read as
            # "now" — and `Component.latest_sbom` orders by it, which would
            # make "latest" arbitrary among the four.
            stamped = now - timedelta(days=days_ago)
            SBOM.objects.filter(pk=sbom.pk).update(created_at=stamped)
            sbom.created_at = stamped
            versions.append(sbom)

        history[name] = versions
        # The newest, so the existing consumers of ``sboms`` — which each want
        # "the component's SBOM" — keep getting one object and the right one.
        sboms[name] = versions[-1]

    return {**pied_piper_product, "sboms": sboms, "sbom_history": history}


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

    # Same reasoning, and it has to be on the *model*, not just the session
    # copy below.  ``request.session["current_team"]`` is a cache with a 300s
    # TTL: patching it only holds for the first five minutes of a recording,
    # after which it is rebuilt from the database.  The long tour runs longer
    # than that, so the refresh landed mid-recording and every authenticated page from that point on
    # redirected into the onboarding wizard — a page with no sidebar, which is
    # how this surfaced: chapter 5 timing out on a nav link that had been
    # there all tour.
    if not team.has_completed_wizard:
        team.has_completed_wizard = True
        team.save(update_fields=["has_completed_wizard"])

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

    # Playwright's own recorder is off when GNOME is doing the capturing;
    # running both would encode the same thing twice and fight for the GPU.
    video_options: dict[str, Any] = (
        {}
        if WAYLAND_CAPTURE
        else {
            "record_video_dir": str(OUTPUT_DIR),
            "record_video_size": {"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
        }
    )

    context = browser.new_context(
        base_url=browser_base_url,
        viewport={"width": RECORDING_WIDTH, "height": RECORDING_HEIGHT},
        # A Wayland capture reads real pixels off the compositor, so the page
        # must be laid out at the size it will be filmed at rather than
        # supersampled for stills.
        device_scale_factor=1 if WAYLAND_CAPTURE else 2,
        **video_options,
    )

    # Prevent white flash — set background color before page content loads
    context.add_init_script(f"document.documentElement.style.backgroundColor = '{APP_BG_COLOR}';")

    # Show a cursor dot + click ripple in the recording.
    # Read the file content explicitly (path= can fail with remote CDP).
    click_js = CLICK_INDICATOR_JS.read_text()
    context.add_init_script(click_js)

    # Pan slowly enough for the recorder to catch the motion. See
    # smooth_scroll.js: the screencast captures 12-16 unique frames a
    # second, and Chromium's native smooth scroll finishes inside five of
    # them.
    context.add_init_script(SMOOTH_SCROLL_JS.read_text())

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

    # Replace the white about:blank with a branded splash screen.  This is
    # visible while the first real navigation loads.
    page.set_content(SPLASH_HTML, wait_until="commit")

    recording_name = _recording_name(request)

    capture = None
    if WAYLAND_CAPTURE:
        # Film the page's own content box, not the window and not the screen.
        #
        # The window carries a title bar and a tab strip, and the screen around
        # it carries the dock, the top bar and whatever else is open — a first
        # test recorded a terminal sitting next to the browser. Asking the page
        # where its content actually is puts the frame exactly on the page.
        #
        # These are logical pixels, which is what ScreencastArea expects; GNOME
        # scales up to physical itself (a 1920x1080 request came back 3200x1800
        # on a 166% display).
        box = page.evaluate(
            """() => ({
                x: window.screenX + (window.outerWidth - window.innerWidth) / 2,
                y: window.screenY + (window.outerHeight - window.innerHeight),
                w: window.innerWidth,
                h: window.innerHeight,
            })"""
        )
        capture = wayland_capture.start(
            OUTPUT_DIR / f"{recording_name}.capture.webm",
            WAYLAND_CAPTURE_FPS,
            (int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])),
        )
        # GNOME takes a moment to bring the pipeline up; starting the clock
        # before the first frame exists would shift every narration offset.
        time.sleep(1.5)

    # Capture is running, so this is the zero point every narration offset —
    # and every subtitle cue — is measured against.
    _narration_state["t0"] = time.monotonic()
    _narration_state["capture"] = capture

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

    final_path = OUTPUT_DIR / f"{recording_name}.webm"

    if capture is not None:
        # Stop politely: GNOME writes the file when the recording ends, and a
        # SIGKILL would leave the shell recording with nothing to stop it.
        wayland_capture.stop(capture)
        raw = OUTPUT_DIR / f"{recording_name}.capture.webm"
        if raw.exists():
            _normalise_capture(raw, final_path)
        else:
            # Say *why*. The first version of this printed only that there was
            # no file, so two runs were spent guessing at a reason the helper
            # had already written down.
            out, err = capture.communicate(timeout=10)
            raise RuntimeError(
                f"wayland capture produced no file for {recording_name}\n"
                f"  helper exit : {capture.returncode}\n"
                f"  helper out  : {(out or '').strip()[:500]}\n"
                f"  helper err  : {(err or '').strip()[:800]}"
            )
    elif video:
        video.save_as(str(final_path))

    if narrator is not None:
        _write_narration_manifest(recording_name, narrator, wall_duration_ms, _test_passed(request))


def _normalise_capture(raw: Path, destination: Path) -> None:
    """Scale a shell recording down to the recording's nominal size.

    GNOME hands back physical pixels, so a 1920x1080 request on a fractional-
    scaled display arrives as 3200x1800. Everything downstream — the hero
    stills, the marketplace listings, the e2e baselines — expects 1920x1080,
    and downscaling from a larger capture is free quality rather than a loss.

    Timestamps pass through untouched, so the narration offsets still land.
    """
    subprocess.run(  # nosec B607 - ffmpeg by name from PATH, fixed argv, shell=False
        [
            "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
            "-i", str(raw),
            "-vf", f"scale={RECORDING_WIDTH}:{RECORDING_HEIGHT}:flags=lanczos",
            "-fps_mode", "passthrough",
            "-c:v", "libvpx-vp9", "-crf", "24", "-b:v", "0",
            "-row-mt", "1", "-cpu-used", "4",
            "-an",
            str(destination),
        ],
        check=True,
    )
    raw.unlink()


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
                "scenes": _narration_state["scenes"],
            },
            indent=2,
        )
        + "\n"
    )
