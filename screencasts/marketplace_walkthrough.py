"""Record the full marketplace walkthrough — the product's hero video.

Plays every chapter from ``walkthrough_chapters.py`` back-to-back as one
continuous tour, separated by title cards, opening on a cold dashboard and
closing on the public trust center a customer would actually visit.

Runs about three and a half minutes. Use this as the single overview video on
a listing; for listings that cap video length, record
``walkthrough_chapters.py`` instead, which cuts the same chapters into
standalone clips from the same step functions.

The story arc, in order:

1. **Know what you ship** — workspace, products, the component hierarchy, and
   the identifiers and lifecycle dates that make a product record answerable.
2. **Every artifact, versioned** — SBOMs and documents stored immutably per
   component, pinned to releases.
3. **Know what's exploitable** — the posture dashboard, the per-component
   drill-down, and clearing a false positive with a VEX document.
4. **Share it with customers** — the trust center on a custom domain, and the
   public page it serves.

Chapters 1 and 3 open on the dashboard themselves; the tour relies on that to
return to a known surface between acts rather than tracking where the previous
chapter left the cursor.
"""

import time

import pytest
from playwright.sync_api import Page
from walkthrough_chapters import (  # noqa: F401  (fixtures register by import)
    CHAPTERS,
    fake_s3,
    pied_piper_scanned,
)

from conftest import (
    OUTPUT_DIR,
    auto_dismiss_toasts,
    dismiss_toasts,
    pace,
    title_card,
)


def _write_chapter_markers(markers: list[tuple[float, str]]) -> None:
    """Write YouTube-style chapter markers next to the recording just made.

    Timings shift whenever a chapter's steps change, so hand-maintained
    markers in a video description go stale silently. Emitting them from the
    run that produced the file keeps the description regenerable: re-record,
    open ``marketplace_walkthrough.chapters.txt``, paste it. YouTube requires
    the list to start at 0:00, which is why the first entry is pinned there.

    The offsets are measured from the start of the test body, which is within
    a frame or so of when Playwright started the video (the page — and with it
    the recording — is created by the ``recording_page`` fixture immediately
    before).
    """
    lines = [f"{int(offset // 60)}:{int(offset % 60):02d} {label}" for offset, label in markers]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "marketplace_walkthrough.chapters.txt").write_text("\n".join(lines) + "\n")


# Requested by name rather than as parameters: the tour never touches the
# seeded objects directly, it just needs them to exist (and the object store
# faked) before the first navigation.
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("pied_piper_scanned", "fake_s3")
def marketplace_walkthrough(recording_page: Page) -> None:
    page = recording_page
    started = time.monotonic()
    markers: list[tuple[float, str]] = [(0.0, "Intro")]

    auto_dismiss_toasts(page)

    # The splash screen is already on-screen from the recording_page fixture,
    # so the opening card lands on brand background rather than a white flash.
    title_card(
        page,
        "sbomify",
        "Supply chain transparency, without the spreadsheet",
        hold_ms=3000,
    )

    for _slug, eyebrow, title, step in CHAPTERS:
        # Marked at the title card rather than after it, so a viewer who jumps
        # to a chapter gets its heading rather than landing mid-scroll.
        markers.append((time.monotonic() - started, title))
        title_card(page, eyebrow, title)
        step(page)
        dismiss_toasts(page)
        pace(page, 900)

    markers.append((time.monotonic() - started, "Get started"))

    title_card(
        page,
        "sbomify",
        "Start free at sbomify.com",
        hold_ms=3600,
    )

    _write_chapter_markers(markers)
