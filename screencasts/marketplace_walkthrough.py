"""Record the full marketplace walkthrough — the product's hero video.

Plays every chapter from ``walkthrough_chapters.py`` back-to-back as one
continuous tour, separated by title cards, opening on a cold dashboard and
closing on the public trust center a customer would actually visit.

Runs about four minutes. Use this as the single overview video on a listing;
for listings that cap video length, record ``walkthrough_chapters.py``
instead, which cuts the same chapters into standalone clips from the same step
functions.

sbomify is a CRA product security lifecycle platform, from SBOM to security
disclosure, and it is agent-first with a person in the loop: AI agents do the
legwork, a person makes every call that reaches a customer. The tour shows
both halves for real. Chapters 3 and 5 drive the actual API with a token made
with the "For an AI agent" preset, draw what the agent sent in a terminal
overlay, and show the calls the preset refuses. The story arc, in order:

1. **Know what you ship**: workspace, products, components, and the
   identifiers and lifecycle dates that make a product record answerable.
2. **Every SBOM, versioned**: artifacts stored immutably per component, pinned
   to releases.
3. **Triage with an AI agent**: the workspace vulnerability list, trends, the
   per-component drill-down; an agent rules libwebp not affected, is refused
   when it tries to apply the ruling itself, and sends it for review; a person
   approves it on the Review tab, and the finding closes with its reason.
4. **Prove CRA compliance**: the CRA assessment's summary and generated
   documents, marked complete.
5. **Disclose it to customers**: an agent drafts a security advisory and is
   refused publishing it; a person publishes it, turns on the Trust Center on
   a custom domain, and the public page shows the advisory.

Each chapter opens from the sidebar, so it does not depend on where the
previous one left the page.
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
    narrate,
    pace,
    settle,
    title_card,
)

# The bridge spoken over each chapter's title card. Spelled out rather than
# f"chapter_{slug}" so `narrator.py lint` can see every key is spoken.
CHAPTER_BRIDGES = {
    "supply_chain": "chapter_supply_chain",
    "inventory": "chapter_inventory",
    "vulnerabilities": "chapter_vulnerabilities",
    "compliance": "chapter_compliance",
    "trust_center": "chapter_trust_center",
}


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
    # Spoken over the splash and the opening card, so neither plays silent.
    narrate(page, "tour_intro")
    title_card(
        page,
        "sbomify",
        "Agents do the legwork. You make the call.",
        hold_ms=3000,
    )

    for slug, eyebrow, title, step in CHAPTERS:
        # Marked at the title card rather than after it, so a viewer who jumps
        # to a chapter gets its heading rather than landing mid-scroll.
        markers.append((time.monotonic() - started, title))
        # The bridge plays over the card; the chapter's own first line lives
        # inside its step function and would otherwise leave the card silent.
        narrate(page, CHAPTER_BRIDGES[slug])
        title_card(page, eyebrow, title)
        step(page)
        dismiss_toasts(page)
        pace(page, 300)

    markers.append((time.monotonic() - started, "Get started"))

    narrate(page, "tour_outro")
    title_card(
        page,
        "sbomify",
        "Start free at sbomify.com",
        hold_ms=3600,
        linger=True,
    )
    settle(page)

    _write_chapter_markers(markers)
