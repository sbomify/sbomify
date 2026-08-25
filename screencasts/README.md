# Screencasts

Playwright-driven recordings of the app, rendered at **1920x1080** video with
**3840x2160** stills. Two kinds live here:

- **FAQ recordings** — one file per flow (`vex_upload.py`, `trust_center_setup.py`,
  …), each showing a single task. These pair with a specific FAQ entry on
  sbomify.com, which supplies the surrounding explanation.
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
  marketplace_walkthrough.webm            # the ~3.5 min hero video
  walkthrough_chapters_supply_chain.webm  # the same chapters, as short clips
  walkthrough_chapters_inventory.webm
  walkthrough_chapters_vulnerabilities.webm
  walkthrough_chapters_trust_center.webm
  screenshots/<recording>/
    hero/01-dashboard.png                 # curated, publishable stills
    hero/02-products-list.png
    frame_001.png                         # incidental timer frames
```

CI (`.github/workflows/screencasts.yml`, manual dispatch) records the same
targets and syncs `*.webm` and the screenshot tree to Cloudflare R2.

### Record on a machine with a GPU

**Anything being published should be recorded on macOS**, not in Docker.

The container has no GPU — `/dev/dri` is not exposed, it runs in a VM, and
Chromium starts with `--disable-gpu` — so rasterisation is software and the
CDP screencast delivers 12-16 unique frames a second whatever you do. The
recording is *correct*, but a page pan lands in five to eight frames and reads
as a stutter.

On a Mac, Chromium composites through Metal. Point Playwright at a locally
launched browser instead of the container's CDP endpoint:

```bash
docker compose -f docker-compose.tests.yml up -d db redis sbomify-s3
SCREENCAST_LOCAL_BROWSER=1 uv run pytest screencasts/marketplace_walkthrough.py \
    --override-ini="python_files=*.py" \
    --override-ini="python_functions=marketplace_walkthrough" -s
uv run python screencasts/transcode.py marketplace_walkthrough
uv run python screencasts/mux_narration.py marketplace_walkthrough
```

The services still run in Docker; only the browser and the test process move to
the host.

**Install the app's font on that machine first.** The pages load Figtree from
Google Fonts with `display=swap`, which means text renders in a fallback until
the webfont arrives — and on a fresh install there is barely a fallback to
render in. The recording then has the wrong typography and nothing reports it:

```bash
sudo apt-get install -y fonts-liberation fonts-dejavu-core fonts-noto-core
mkdir -p ~/.local/share/fonts
curl -sSL -o ~/.local/share/fonts/Figtree-variable.ttf \
    "https://github.com/google/fonts/raw/main/ofl/figtree/Figtree%5Bwght%5D.ttf"
fc-cache -f
fc-list | grep -c Figtree      # expect 8
``` `SCREENCAST_LOCAL_BROWSER=1` launches Chromium **headed** on purpose:
headless still composites through SwiftShader on several platforms, which is
the thing being avoided.

`transcode.py` re-encodes Playwright's VP8 output to VP9 (it bands on the app's
flat gradients) and must run before `mux_narration.py`, which lays the audio on
from the timing manifest.

## The marketplace walkthrough

`walkthrough_chapters.py` is the source of truth: it holds the Pied Piper seed,
the four `chapter_*` step functions, and a parametrized recording that renders
each chapter as its own clip. `marketplace_walkthrough.py` imports the same
step functions and plays them back-to-back with title cards, so the long cut
and the short cuts cannot drift apart.

**For a listing, take the `hero/` stills.** They are named and numbered in
narrative order and stay stable across re-records, so an embedded
`hero/13-vex-preview.png` keeps working after the next run. The timer frames
alongside them are incidental — a frame every 3s, wherever the cadence lands.

Captions are burned into the video but hidden for the stills, on the assumption
that the video plays muted and the listing writes its own captions.

### Run the steps in order, and stop if one fails

**transcode, then mux, then score.** Each reads what the last wrote, and only
the first can safely be skipped in isolation — carrying on past a failed
transcode leaves a recording that is muxed and scored and still VP8, which
plays perfectly and reports nothing. That has happened: a crashed transcode
pool left three of 27 unconverted and the remaining steps ran over them
regardless. If transcode fails, fix it and re-run it before muxing.

The video stream is copied by both later steps, so a recording caught in that
state can be repaired in place with `-c:v libvpx-vp9 -crf 24 -c:a copy` rather
than re-recorded; it costs the same encode it would have had.

### The music pass

Every recording carries a bed:

```bash
uv run python screencasts/score.py <recording> ~/ledger_trace.m4a --loop
```

`--loop` covers a cut longer than the track, and does nothing when the track is
already long enough, so it can be passed across a batch of mixed lengths. The
repeat is not a restart from the top, which lands a cold open in the middle of
a paragraph; `choose_loop` searches for a passage whose texture matches the
outgoing bar and crossfades back to that.

Scoring cannot read its own output, or a rerun would stack a second bed, so the
mux is kept as `<name>.dry.webm` and **the scored mix takes the plain
`<name>.webm`**. The file you play is the finished one; the sidecar is
scratch. `mux_narration` deletes the sidecar whenever it rewrites a recording,
so a sidecar on disk always matches the recording beside it.

One caveat worth keeping in view. Moreno and Mayer (2000) tested background
music against instructional material directly and found it depressed both
retention and transfer. That result is about teaching, and these are mostly
short task clips rather than lectures, but if a clip ever feels cluttered the
bed is the first thing to pull.

### Adding a chapter

Write a `chapter_*(page)` function and add it to `CHAPTERS`. It gets picked up
by both the tour and the per-chapter clips. Use `caption()` / `clear_caption()`
for narration, `title_card()` for act breaks, and `shot()` at the frames worth
publishing — renumber the existing slugs if you insert one in the middle.
