# Screencasts

Playwright-driven recordings of the app, rendered at **1920x1080** video with
**3840x2160** stills. Two kinds live here:

- **FAQ recordings** — one file per flow (`vex_upload.py`, `trust_center_setup.py`,
  …), each showing a single task. These pair with a specific FAQ entry on
  sbomify.com, which supplies the surrounding explanation. The page links to
  the video by its filename, so renaming a recording breaks the page.
- **The marketplace walkthrough** — `marketplace_walkthrough.py` and
  `walkthrough_chapters.py`. A narrated product tour meant to play cold next to
  a marketplace listing, with no surrounding text to lean on.

## Recording

```bash
./bin/record_screencasts.sh list                      # what's available
./bin/record_screencasts.sh marketplace_walkthrough.py
./bin/record_screencasts.sh all
```

Output lands in `screencasts/output/` (the `.webm`s and the screenshot tree are
git-ignored):

```text
output/
  marketplace_walkthrough.webm            # the ~4 min hero video
  walkthrough_chapters_supply_chain.webm  # the same chapters, as short clips
  walkthrough_chapters_inventory.webm
  walkthrough_chapters_vulnerabilities.webm
  walkthrough_chapters_compliance.webm
  walkthrough_chapters_trust_center.webm
  screenshots/<recording>/
    hero/01-dashboard.png                 # curated, publishable stills
    hero/02-products-list.png
    frame_001.png                         # incidental timer frames
```

Each narrated recording also leaves `<name>.vtt` next to its `.webm`.

Narration is built locally: record with the voice configured (see below),
then upload the `.webm` and `.vtt` files to the `screencasts/` prefix of the
marketing-assets bucket. sbomify.com reads each `.vtt` at build time and prints
it under the video as a transcript.

CI (`.github/workflows/screencasts.yml`, manual dispatch) records without a
voice, so its videos are silent and captioned. Running it syncs those over the
narrated uploads.

## Narration

Every recording is narrated. `caption(page, text)` shows the line as a
lower-third and speaks it with an x.ai voice. It waits for the line before to
finish, then holds until this one has been said, so the next action lands after
the viewer has heard what it is. `caption(page, text, block=False)` lets the
script keep acting (typing into the field the line describes) while it plays.

- **Write lines as string literals in the `caption()` call.** The recording
  synthesises every literal line before the page opens. A line built at runtime
  is synthesised when it is reached, which leaves seconds of dead air on screen.
- **Write for the ear.** One idea per line, plain words, no dashes, and say what
  the viewer sees or why it matters rather than narrating each click. Keep the
  app's own words for things on screen.
- **Spelling for the voice.** `_SPOKEN_SPELLINGS` in `conftest.py` respells a
  word for the voice only (left alone, "sbomify" comes out as "S-bomb-ify").
  The caption keeps the real spelling.

The clips are cached in `output/narration/` by voice and text, so a re-record
only pays for lines that changed. Playwright records video only, so each
recording writes `<name>.narration.json` (every line, when it started, which
clip), and `bin/mux_screencast_narration.py` runs on the host after recording to
mix the clips into an Opus track and write the `.vtt`. `record_screencasts.sh`
calls it for you.

Narration needs one of:

| Variable | Use |
| --- | --- |
| `XAI_API_KEY` | Call `https://api.x.ai/v1/tts` directly |
| `SCREENCAST_TTS_URL` (+ `SCREENCAST_TTS_TOKEN`) | Call a proxy that holds the key instead |
| `SCREENCAST_TTS_VOICE` | Voice id, default `eve` |

With none set, recordings are silent and captioned, and each caption is held
for its reading time so the pacing stays the same.

## The marketplace walkthrough

The tour tells the product's story, a CRA product security lifecycle platform
from SBOM to security disclosure, in five chapters: know what you ship (products,
components, identifiers, lifecycle), every SBOM versioned (artifacts and
releases), triage vulnerabilities with VEX, prove CRA compliance (the
assessment summary and generated documents), and disclose it to customers
(security advisories and the Trust Center).

`walkthrough_chapters.py` is the source of truth: it holds the Pied Piper seed,
the five `chapter_*` step functions, and a parametrized recording that renders
each chapter as its own clip. `marketplace_walkthrough.py` imports the same
step functions and plays them back-to-back with title cards, so the long cut
and the short cuts cannot drift apart.

**For a listing, take the `hero/` stills.** They are named and numbered in
narrative order and stay stable across re-records, so an embedded
`hero/13-vex-preview.png` keeps working after the next run. The timer frames
alongside them are incidental — a frame every 3s, wherever the cadence lands.
Stills `18`–`20` (CRA assessments, CRA summary, security advisories) were added
after `01`–`17`, so their numbers do not follow the chapter order; the older
names were kept so existing embeds keep working.

Captions are burned into the video but hidden for the stills, on the assumption
that the listing writes its own captions. Each caption is also spoken:
`bin/mux_screencast_narration.py` lays the voice-over onto the `.webm` and
writes a matching `.vtt`.

### Adding a chapter

Write a `chapter_*(page)` function and add it to `CHAPTERS`. It gets picked up
by both the tour and the per-chapter clips. Use `caption()` / `clear_caption()`
for narration, `title_card()` for act breaks, and `shot()` at the frames worth
publishing — renumber the existing slugs if you insert one in the middle.
