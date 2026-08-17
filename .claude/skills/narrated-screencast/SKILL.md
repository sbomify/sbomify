---
name: narrated-screencast
description: Write, synthesize, and record voiceover narration for sbomify screencasts in screencasts/. Use when adding or reworking narration for a screencast, changing the pronunciation map, fixing dead air or mispronounced acronyms in a recording, or when a screencast script fails to record because the UI moved.
---

# Narrated screencasts

Screencasts live in `screencasts/`, record through Playwright at 1920×1080, and
publish to Cloudflare R2 for embedding on sbomify.com. Narration is spoken by
the xAI TTS API, timed by the recording itself, and muxed in afterwards.

Read `screencasts/README.md` first — it distinguishes the short FAQ recordings
(one flow each, paired with an FAQ entry that supplies the surrounding text)
from the marketplace walkthrough (`marketplace_walkthrough.py` +
`walkthrough_chapters.py`), which plays cold with nothing to lean on.

## Three outputs, not one

Every narrated recording produces:

| File | What it is |
| --- | --- |
| `<name>.webm` | video + muxed Opus narration |
| `<name>.vtt` | **WebVTT subtitles cut from the same offsets** |
| `<name>.narration.json` | the timing manifest the other two are built from |

**Subtitles are required, not a nicety.** A narrated recording suppresses the
on-screen lower-third — `caption()` returns early when a narration script
exists, because the voice already carries the explanation. That makes the
`.vtt` the only path for a viewer who is muted, deaf or hard of hearing, or
scanning for a phrase, and it is what search engines index. Never ship the
`.webm` without its `.vtt`; the player needs
`<track kind="subtitles" srclang="en" default>`.

Cue times are derived from the audio timeline, never typed by hand, so words
cannot drift from the voice. `mux_narration` splits each beat into cues of at
most two ~42-character lines and shares the beat's duration between them in
proportion to length.

## The one rule that matters

**Narration is a voiceover, not a caption track.** A person talks *continuously
over* a demo; they do not speak, fall silent, click something, then resume.

`narrate(page, key)` therefore **starts** a line and returns immediately, so the
clicking and typing underneath keep running while the line plays. It waits only
for the *previous* line to finish, so lines never overlap each other.

That has three consequences you must design around:

- **Put each line before the action it describes**, never after.
- **Never call `narrate()` twice in a row** before an action. Both lines play
  before anything happens and the action then runs in silence. Interleave them
  (`narrate` → part of the action → `narrate` → rest), or merge them into one
  longer line with a `[pause]`.
- For a repetitive loop, narrate **every couple of iterations**, not every one.
  Map beat keys by index:

```python
component_beats = {0: "components_first", 1: "components_rest", 3: "components_last"}
for index, name in enumerate(COMPONENTS):
    if beat := component_beats.get(index):
        narrate(page, beat)
    _create_component(page, name)
```

Use `settle(page)` only where the picture must not move until the sentence
lands. The `recording_page` fixture already settles at the end so the closing
line is never clipped.

## Target: silence under about 10%

Measure it — do not eyeball it:

```bash
python3 -c "
import json; d=json.load(open('screencasts/output/<name>.narration.json'))
t=d['wall_duration_ms']/1000; s=sum(b['duration'] for b in d['beats'])
print(f'video {t:.1f}s spoken {s:.1f}s silent {t-s:.1f}s ({(t-s)/t*100:.0f}%)')
prev=0.0
for b in d['beats']:
    st=b['offset_ms']/1000
    if st-prev>2: print(f'  {st-prev:5.1f}s gap before {b[\"key\"]}')
    prev=st+b['duration']
"
```

Every gap over ~2s is either a missing line or an action that is too slow. Fix
whichever is actually at fault:

- **Missing copy** → add a beat, or lengthen the line that covers that stretch.
- **Slow action** → machine strings (a CPE, a package URL, any URL) should be
  typed at `delay=25`, not the human-paced default. Nobody wants to watch a CPE
  typed at reading speed. Prose the viewer is meant to read stays slower.
- **Recording at 1920×1080 is slow.** The 4K hero screenshots taken during
  `pace()`, page reloads, and HTMX panel loads all cost real seconds, so write
  more generously than feels natural — a line that seemed long on the page is
  usually still shorter than the action underneath it.
- **Dead cold open** → put the first `narrate()` *before* `start_on_dashboard`,
  so the opening line plays over the splash instead of the video starting on
  several seconds of silent logo.

## Pronunciation: probe, never guess

**The synthesizer speaks hyphens aloud as the word "dash".** `ess-bom` comes out
"s dash bom". Never put a hyphen in a `replace` value — join the sounds
(`essbomify`) or use IPA between slashes (`/ˈɛsbɑm/`).

**Isolated probes lie.** `essbomify` passed a single-word probe and was then
spelled out letter by letter inside a real sentence. Always finish with `proof`,
which reads back the actual delivered audio.

Three commands, in the order you should use them:

```bash
./bin/record_screencasts.sh try SBOM "essbom" "/ˈɛsbɑm/"   # compare candidates
./bin/record_screencasts.sh verify                          # audit the whole map
./bin/record_screencasts.sh proof <screencast>              # read back real lines
```

And before spending a recording run, always:

```bash
./bin/record_screencasts.sh lint    # every narrate() key exists; no orphan copy
```

`try` prints what was heard *and* the clip duration — duration is the tiebreak,
because speech-to-text normalises "ess dash bom" and "ess bom" to similar text
while the spoken separator makes the clip measurably longer.

Read `proof` output with judgement: a spelled-out run is **correct** for API and
URL and **wrong** for SBOM, so the flag means look, not fail.

**A replace key may not contain punctuation** — the API rejects it, so
`sbomify.com` cannot be mapped. Left bare it is read as a URL
("s-bomba.fi slash dot-com"). Fix domains in the copy instead: speak
"sbomify dot com" and set `caption:` to the written form, so the subtitle still
reads `sbomify.com`.

Keep `screencasts/narration/pronunciations.yaml` minimal. `CycloneDX`, `SPDX`,
`NTIA` and `VEX` are already correct unmapped — an entry for a term that does
not need one is just a chance to break it. Add a term only when you have heard
it come out wrong, and remember the map is part of the cache key, so changing it
re-synthesizes **every** line in **every** screencast.

## Writing the copy

Read the FAQ page that embeds the screencast first
(`/home/ubuntu/code/sbomify.com/content/faq/…`). Its `answer` field states the
question the video exists to answer — that is the narration's thesis.

Then, in `screencasts/narration/<name>.yaml`:

- Narrate the **why**, never the click. "A release pins exactly what shipped",
  not "click Create Release".
- Read the `text` values top to bottom; they must sound like one person talking
  without stopping. Sentences run into each other across beats.
- Open by naming what the viewer will be able to do; close on the outcome.
- Present tense, second person, active voice. Under 20 words a sentence.
- Ban "as you can see", "simply", "just", "obviously".
- "sbomify" is always lowercase.
- `[pause]`, `[long-pause]`, `<slow>`, `<soft>` are available and are stripped
  from captions automatically. Set `caption:` only when the spoken form differs
  from what should appear on screen.

## Parametrized recordings, and sharing copy

A parametrized screencast renders one clip per param and reads
`narration/<stem>_<param-id>.yaml` — so `plugin_enablement` has six narration
files, one per plugin, all defining the same beat keys with different copy.

When two recordings run the *same* step functions, their narration is shared
with `include:` rather than duplicated:

```yaml
# marketplace_walkthrough.yaml — the long cut
include:
  - walkthrough_chapters_supply_chain
  - walkthrough_chapters_inventory
beats:
  tour_intro: {text: "..."}     # only what belongs to the long cut
```

This is the same reasoning that makes `marketplace_walkthrough.py` import the
chapter functions instead of copying them: the long cut and the short cuts must
not drift apart. Edit chapter copy in the chapter's own file.

## Recording

```bash
./bin/record_screencasts.sh <name>.py     # record, mux audio, cut subtitles
./bin/record_screencasts.sh warm <name>   # synthesize only, to review copy
./bin/record_screencasts.sh warm-all      # cache everything before a long run
./bin/record_screencasts.sh prune         # drop audio no script refers to
```

`warm-all` before a batch is worth it: a cold line blocks the recording while
it synthesizes, and a blocked beat is reported at the end of the run.

`prune` matters because the cache is **committed**. Every edit to a line — or
to the pronunciation map — re-keys that clip, so superseded audio piles up.
Prune before opening a pull request; `--dry-run` first if you want to look.

Synthesis needs `XAI_API_KEY` **only** for lines not already in
`screencasts/narration/audio/`, which is committed. An unchanged re-record makes
zero API calls and works offline.

Expect to iterate: record → measure silence → adjust copy or pacing → re-record.
Two or three passes is normal.

## Before you touch anything: check the base

**Confirm the tree is current before diagnosing a broken screencast.** These
scripts are maintained upstream, and a stale checkout will send you off
repairing selectors that were fixed weeks ago.

```bash
git fetch upstream && git rev-list --left-right --count upstream/master...HEAD
```

`origin` is a fork; `upstream` is `sbomify/sbomify`. If the left number is not
0, rebase before doing anything else. This has already cost one full round of
work: selectors were re-derived by hand — down to an identically-named
`_expand_about_row` helper — that already existed upstream.

When a script does genuinely fail, read the Playwright error for the failing
locator and check the template. A template existing does not mean it is used;
several orphaned templates sit in the tree, so confirm something includes or
serves it.

Two real examples of this rot, both found by recording:

- **Settings tabs are real links now** (`a.settings-tab[href$='/account']`), not
  the old in-page `data-tab` switcher. `conftest.navigate_to_trust_center_tab`
  had already been fixed this way while `account_deletion` and
  `profile_editing` were left broken — so when you find one instance, grep for
  the rest of the pattern.
- **HTMX-loaded panels** can have their container visible before the contents
  land. Wait for the control you are about to click, not the card around it.
- **A row-level `@click` can be swallowed by a child.** `security_advisories`
  navigated from the `<tr>`, but the row's centre — where a click lands — sat
  over a cell whose links are `@click.stop`. Aim at the specific element, and
  assert the navigation happened (`page.wait_for_url`) rather than assuming it.
- **A control that does not exist is not always a timing problem.** Two
  recordings waited on elements that the UI had stopped rendering: the
  lifecycle "Edit" button (only shown once dates exist — a new product shows
  "Set Dates"), and VEX-suppressed rows (now hidden behind a "Show suppressed"
  toggle so the open counts match the working list). Read the template before
  raising a timeout; when a behaviour has genuinely changed, the narration
  usually has to change with it, because the copy was describing the old one.

The recording environment serves no websockets, so any flow that waits on a
broadcast needs a reload fallback with a short timeout.

## Gotchas already paid for

- **Drift correction earns its keep on long videos.** `mux_narration` scales
  offsets by the video/wall ratio. That was ~1.00 on an 80s recording but 0.985
  on a 171s one, which is 2.5s of drift. Keep it.
- **Do not let the narration teardown mask a real failure.** The "beats never
  spoken" assertion only fires when the test passed; otherwise it buries the
  actual error.
- Playwright leaves temp recordings named as 32-char hex; delete only those.
- Output files are written as root — `sudo chown -R ubuntu:ubuntu screencasts/output/`
  before copying anything off the box.
