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

## Does the voice describe what is on screen? Run `audit_timing.py`

**Do this before the silence check.** Silence is the cheaper problem and the
one you will notice anyway; a line describing the wrong screen is the one that
survives review.

```bash
uv run python screencasts/audit_timing.py marketplace_walkthrough
```

It joins the two timelines in `<name>.narration.json` — `beats` (when each line
was spoken) and `scenes` (every surface the recording landed on) — and reports:

- **SPILL** — the line outlasts the surface it opened on. The worst instance
  found this way was a 22.6s VEX line where the script clicked Apply about four
  seconds in, so "nothing has been written yet" was spoken **eight seconds
  after the write**. Fix by splitting the beat at the action, not by padding.
- **FROZEN** — the picture holds still while audio runs on, because the beat's
  visual work finished early and `narrate` is waiting out the clip.
- **SILENT SCENE** — a surface nobody narrates.

The recording writes the scene log automatically; a manifest without one
predates the instrumentation and the auditor will say so.

**Why the silence check is not enough:** the tour measured 2% silence with zero
gaps over 2s — a perfect score — while several lines were describing pages the
tour had already left. Two different measurements, and they do not substitute
for each other.

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
  several seconds of silent logo. The same applies at every **chapter card**:
  the card is silent unless a line is narrated *before* it, because the
  chapter's own first line lives inside its step function and runs after. That
  left a nine-second hole after the walkthrough's opening line.

### Pace: match the job, and measure both halves of it

**Instructional and persuasive screencasts want different speeds, and picking
the wrong guidance is easy to do.** This is written from getting it wrong: the
walkthrough shipped at `speed: 0.85` on guidance for dense technical *teaching*,
and its opening line measured **103 wpm** — Miller's least-persuasive condition
almost exactly, on the first thing any viewer hears.

| Job | Target | Why |
| --- | --- | --- |
| FAQ clip, answering a question somebody already has | 130-140 wpm | comprehension is the goal; the viewer is already sold |
| Marketing tour, cold audience | 140-155 wpm | credibility and momentum are the goal |

The evidence for the second row: screencast narration guidance lands at 130-150
with **140 measuring most credible**; Miller et al. (1976) found **195 wpm
persuaded better than 102**, fast reading as confident and knowledgeable; and
Smith & Shaffer (1991) found speed helps *most* when the audience does not
already agree — which is exactly a cold marketplace viewer. Do not carry the
110-130 teaching figure onto a video whose job is to persuade.

**Measure the rate two ways, because "slow" has two causes.** Overall wpm mixes
them; articulation rate (excluding tagged pauses) separates them:

```bash
uv run python -c "
import json, glob, re
w=s=p=0
for f in glob.glob('screencasts/output/*.narration.json'):
    d=json.load(open(f))
    for b in d['beats']:
        w+=len(b['caption'].split()); s+=b['duration']
print(f'{w/s*60:.0f} wpm overall')
"
```

A corpus can measure fine overall and still open badly. Ours averaged 134 wpm
— in band — while `tour_intro` sat at 103 because it carried two `[long-pause]`
tags in three sentences, 12% of its runtime. **Check the opening line on its
own.** It is the one that decides whether anyone sees the rest.

**A flat voice is the part no wpm figure catches.** See "Choosing a voice".

`speed` in the narration YAML is the lever, and it is part of the audio cache
key, so changing it re-synthesizes everything.

`speed` and `voice` come from the *including* file — `include:` merges beats
only — so the long cut and every chapter script must carry the same values or
the same beat is synthesized twice at two speeds and the cuts drift apart.

### Choosing a voice

xAI offers 28 (`GET /v1/tts/voices`), and the API says nothing about how
animated any of them is. Measure it: synthesize one line per candidate and take
the standard deviation of F0 in semitones. On this corpus `ara` — the original
pick — measured **3.36 st**, one of the flattest available, against `carina` at
**6.14 st**. Nearly double, and audible immediately.

Audition with a line that is *representative*, not the slowest thing you have
written. Auditioning all eight female voices on `tour_intro`, the sleepiest
copy in the corpus, made every one of them sound flat and buried the actual
difference between them.

### `[pause]` is a no-op — use `[long-pause]`

Measured against a baseline line, and this matters because the copy was full of
`[pause]` on the assumption it inserted a beat:

| tag | adds | of which silent |
| --- | --- | --- |
| `[pause]` | **+0.09s** | — |
| `[long-pause]` | +1.60s | **1.34s** |
| `[breath]` | +1.20s | 0.27s |
| `[sigh]` | +0.32s | — |
| `<slow>` | +0.96s | — |
| `<soft>` | +0.63s | — |
| `, ,` | +1.20s | leaks as the word "diagnostic" |

`[pause]` buys 90 milliseconds. **`[long-pause]` is the real rest.** `[breath]`
is mostly *audible inhale* — 1.2s added, only 0.27s of it quiet — and reads as
gasping between sentences; it was tried across the walkthrough and rejected by
ear. Duration alone cannot tell a rest from a breath, so measure the silence
inside the interval, not the length of the clip:

```bash
ffmpeg -i probe.wav -af silencedetect=noise=-45dB:d=0.12 -f null - 2>&1 | grep silence_duration
```

**Place them, do not sprinkle them.** Guidance is to pause *after introducing a
new concept* and *before moving to a new screen* — one per genuine turn. The
walkthrough accumulated 18, 26 seconds of a 379-second script, several of them
mid-explanation where they read as hesitation rather than emphasis. Thinning
them to 7 (the opening turn, the close's setup and its call to action, and the
two pivots in the VEX chapter) took 15 seconds out and moved the corpus from
134 to 152 wpm without touching a single word.

Watch the density in short lines especially: two `[long-pause]` tags in a
three-sentence opener made 12% of it silence and dragged it to 103 wpm.

## Smoothness: record where there is a GPU

**Record on macOS, with a locally launched browser.** Set
`SCREENCAST_LOCAL_BROWSER=1` and Playwright launches Chromium on the host
instead of attaching to the Docker container's CDP endpoint. On a Mac that
browser composites through Metal, and the recording is captured at the frame
rate Playwright asks for.

In Docker on Linux it is not. That container has no GPU — `/dev/dri` is not
exposed, it runs in a VM, and Chromium starts with `--disable-gpu` — so
rasterisation is software and the CDP screencast yields **12-16 unique frames a
second** whatever you do. Measured across pages of wildly different weight and
unchanged by halving the rendered pixel count (`device_scale_factor` 2→1 moved
77 unique frames to 71), so it is a capture ceiling rather than drawing cost.
At that rate a page pan lands in five to eight distinct frames and stutters.

### What used to be here, and why it is gone

A `SCREENCAST_SLOWDOWN=N` mechanism recorded N times slower and a `retime.py`
divided the timestamps afterwards, which did lift the sampled rate (11.6 →
24.3 distinct fps at N=3). It is removed, because it was the source of a whole
class of bugs that cost far more than the smoothness was worth:

- **Pans silently stopped arriving.** The eased scroll in `smooth_scroll.js`
  was measured moving one pixel in eighteen seconds at N=3, while a direct
  `scrollTop` assignment worked and `requestAnimationFrame` ticked 62 times a
  second. *Every* pan in the recording was frozen, and nothing said so.
- **Title cards showed for a third of their duration** — 2600ms of hold
  rendered as 867ms — because `wait_for_timeout` and JS timers are wall clock
  while the video is divided afterwards.
- **Clicks landed mid-pan**, because the wait for the scroll was not scaled
  with the scroll.
- **Probes verified against a different system.** They defaulted to N=1 where
  the pan works, so four separate "fixes" for the same defect all measured
  green and all shipped broken.

If a Linux recording is unavoidable, expect the stutter and do not reintroduce
the slowdown; fix it by moving the capture, not by pacing around it.

### Banding: Playwright writes VP8

The recorder's own output is **VP8 at a fixed, fairly low quality**, and it
bands visibly on the app's flat gradients. `transcode.py` re-encodes to VP9 at
crf 24, timestamps untouched, and must run **before** `mux_narration.py`. Do
not raise crf to 30 — the picture softens enough to hurt both the look and the
measurement.

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

### Structure, for anything longer than one answer

A single FAQ clip answers a question and stops. A multi-chapter tour needs a
story, and the difference is not decoration — it decides whether each chapter
has a reason to exist beyond being next.

- **One question, one person, one moment.** The tour opens on "it's Friday
  afternoon, and a customer wants to know whether you're affected by a
  vulnerability in libwebp". Before that it was an architecture tour: five
  chapters mapped to the app's own information architecture, with the pain
  stated once and then dropped.
- **Close the loop the opening opened.** Do not recap features. The outro
  answers the question the first line asked, in the same words.
- **Never bury the best line.** The close was once a four-item feature list
  with "hand your customers a link instead of an apology" landing third, in the
  middle of an inventory, exactly where the close needs weight.
- **Bridges raise stakes; they do not signpost sequence.** A draft that opened
  four of five chapters with "So" / "Then" / "And then" / "And last" read end to
  end as a list of rooms being visited rather than a story getting harder.
- **Say the numbers that are on screen.** If the dashboard shows 10 findings and
  2 critical, say so. The visual is handing over specifics for free and abstract
  copy ("what needs attention") refuses them.
- **The story and the seed must be the same story.** The vulnerability the
  narration names is the one the fixture seeds and the one chapter 3 clears with
  a VEX. See "The seed is part of the argument" below.

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

The full pipeline, in order — **transcode before mux**, always:

```bash
SCREENCAST_LOCAL_BROWSER=1 <record>                  # host browser, on a GPU
uv run python screencasts/transcode.py <name>        # VP8 -> VP9 quality pass
uv run python screencasts/mux_narration.py <name>    # audio + .vtt
```

`transcode.py` is idempotent by marker file, so a re-run after a partial failure
will not re-encode something already converted. Delete `<name>.transcoded.json`
to force it.

Expect to iterate: record → `audit_timing.py` → adjust copy or staging →
re-record. Two or three passes is normal.

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

The design-system conversion is the sharpest lesson so far: it broke 9 of 17
recordings at once, and **not one of them broke on a class the design system
renamed — they broke on hooks that stopped existing at all.** A component
library replaces `.tw-badge-violet` with a `data-variant` a parent binds, and
`.tw-dangerzone-card` with a shape that carries no class. So prefer, in order:
a stable `id`, an ARIA role plus accessible name, then visible text. Reach for a
CSS class only when nothing else identifies the thing, and expect it to rot.

Two traps specific to that style of markup:

- **An accessible name can be scoped rather than shared.** One `c-actions-menu`
  serves every page but labels itself after what it acts on, so the single
  `"More actions"` became `"Component actions"` and `"Product actions"`. A name
  that reads like a global is worth grepping for before you trust it — and
  `aria-label` beats slot text, so a button reading "Delete account" answers to
  "Delete your account".
- **A modal's confirm may not be inside its form.** The identifier and link
  dialogs put the submit in the modal footer, bound back by `form="…-form"`, so
  `modal.locator("button[type='submit']")` matches nothing. Match on
  `button[form='…']`. Note this flipped direction once already — a previous fix
  removed a `form` attribute the plugin Save button should not have had.

Seven real examples of this rot, all found by recording:

- **A create flow can stop being a modal.** Products and components moved onto
  `/products/new/` and `/components/new/`; `open-add-*-modal` now dispatches
  into nothing and fails silently, so the failure surfaces later as a missing
  field. Drive creation from the navbar **New** menu (`open_new_from_navbar`),
  not the empty state's "Create Your First …" — that button only exists while
  the workspace is empty, and empty-vs-populated has broken an opener before.
  Submitting also lands on the *created item's page*, so a `click_into_row`
  that followed a creation now has no row to find.

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
- **Punctuation counts as a selector.** `text=Preview — nothing stored yet`
  broke when the em-dash became a colon. Match the words, not the typography.
- **A default can flip back.** Suppressed findings were hidden by default, then
  upstream reverted it because hiding them made an applied VEX look like it had
  done nothing. Two recordings told viewers to turn a toggle *on* that was
  already on, and one waited on a "N suppressed hidden" footer that no longer
  renders. Read the toggle rather than assuming its state, and remember the
  narration usually has to change with the behaviour.

The recording environment serves no websockets, so any flow that waits on a
broadcast needs a reload fallback with a short timeout.

A UI that gains steps costs you silence. Creation moving from a modal to a page
added a menu click and a full page load per component, which pushed
`product_creation` from comfortable to 10% silence with four gaps over 2s. The
copy did not change, so nothing sounds wrong — the video just got slower
underneath it. Re-measure after any flow change, and remember that closing those
gaps means new copy, which means synthesis, which means the API key.

## Music: only where it is not teaching

**Default to no music.** Mayer's *coherence principle* — learners do better
when extraneous material is left out — was tested against background music
directly by Moreno and Mayer (2000), who found it depressed both retention and
transfer; Mayer reports 11 of 11 tests favouring the concise version on each.
So the FAQ recordings, which answer a question the viewer already has, stay
dry. Music is for the marketplace walkthrough, shown to a cold audience that
has to be persuaded to care. `screencasts/score.py` exists for that one video
and is deliberately not wired into `bin/record_screencasts.sh`.

When you do score something:

- **Measure both tracks, do not eyeball.** Narration runs −16.3 to −16.7 LUFS
  integrated with a −1.1 dBFS true peak. Put the bed **8–12 LU under** it with
  a static gain. Not `loudnorm` — a second normalisation pass re-compresses a
  track whose narrow dynamic range is the whole point.
- **Duck 3–4 dB, and verify the number.** Depth is extremely sensitive to how
  dense the narration is: one `sidechaincompress` setting measured 4.9 dB
  against a sparse clip and ~12 dB against the tour, burying the bed 12 dB below
  its own target. `score.py` recovers the bed by phase-cancelling the mix
  against the original and reports the measured level, because the static gain
  says nothing about what a listener actually hears.
- **Carve 1–4 kHz.** A gentle −3 dB bell at 2 kHz buys intelligibility far more
  cheaply than pulling the whole bed down. That band is where speech lives.
- **Profile the track before assuming it loops.** Band energy over time tells
  you whether it *builds*: ours went from −40 dB to −24 dB in the vocal band
  across its length, so a crossfaded internal repeat would splice two visibly
  different textures and you would hear the seam.
- **End-align instead of looping.** Start the music late enough that its own
  composed fade-out lands on the final frame, snap the entry to a chapter
  boundary so it arrives on a scene change rather than mid-sentence, and let the
  sparse head absorb the trim. No splices, no loops, and the build runs under
  the back half where the story pays off.
- **Copy the video stream** (`-c:v copy`). Re-encoding here throws away
  everything `transcode.py` bought.

Commissioning generated music: state a LUFS target, ask for the 1–4 kHz band
kept sparse, and require mono-compatibility (embeds play mono on laptop
speakers), loopability, no risers or whooshes, and no musical resolution before
the full runtime. Ask for texture and harmony, not a melodic motif — "occasional
melodic textures" and "no distracting lead melody" in one prompt is a
contradiction the generator resolves however it likes.

## Probe the same way you record

A diagnostic probe must run in the same environment as the recording — same
browser source, same environment variables. This is not a detail: when the
recorder ran at `SCREENCAST_SLOWDOWN=3` and probes defaulted to 1, four
separate "fixes" for the same defect measured green and all shipped broken,
because the pan they depended on only works at 1.

```bash
docker compose -f docker-compose.tests.yml exec -T tests \
    uv run pytest screencasts/probe_x.py --override-ini="python_files=*.py" \
    --override-ini="python_functions=probe" -s
```

This cost four rounds of "fixed" that were not. The eased pan in
`smooth_scroll.js` does not arrive at `SLOWDOWN=3` — measured, one pixel in
eighteen seconds, while `requestAnimationFrame` ticked 62 times a second and a
direct `scrollTop` assignment in the same document worked. So **every pan in
the recording was frozen**, the trust-centre field never came into frame, and
each fix verified green at `SLOWDOWN=1` where the pan works.

Two lessons beyond the specific bug:

- **A pan that reassigns `scrollTop` every frame fights anything else that
  scrolls.** The loop is now cancellable (`window.__sbomifyCancelScroll()`) and
  every pan supersedes the last, so a correction is not undone on the next
  frame.
- **Check that it held, not that it happened.** Some pages scroll themselves
  back: the trust-centre settings panel returns to the top within 600ms of an
  HTMX save, so a check taken immediately after scrolling passes while the
  recording shows the top of the page. `smooth_scroll` now re-checks from
  Python after a wait, and raises rather than carrying on.

## Never let a missing element become a no-op

`if locator.count(): ...` around a scroll, a hover or a click turns "the thing
I am about to film is not there" into silence. One of those guards hid the
trust-centre scroll for a whole review cycle: the panel re-renders on save, the
locator resolved to nothing for an instant, the scroll was skipped, and the
recording carried on filming the wrong part of the page.

Wait for the element and let the recording fail. A failed recording costs one
run; a silently wrong one costs a review cycle and ships if nobody notices.

## Gotchas already paid for

- **The session's team cache expires mid-recording.**
  `request.session["current_team"]` is a 300s cache rebuilt from the `Team` row
  (`teams/utils.py`). `conftest` patched `has_completed_wizard` into the session
  dict but not onto the model, which held for the first five minutes and then
  did not: the tour runs longer than five minutes, so the refresh landed mid-tour and every authenticated page from that point
  redirected into the onboarding wizard — a page with no sidebar. It surfaced as
  chapter 5 timing out on a nav link that had worked all tour. Anything the
  recording depends on must be persisted to the model, never only to the
  session. The fixture above it already did this for `has_selected_billing_plan`;
  the inconsistency is what cost the time.
- **Do not diagnose by re-running.** The tour costs 18 minutes per attempt at
  N=3. A throwaway probe test that reproduces just the suspect transition and
  dumps the DOM (`locator.count()`, `is_visible()`, the relevant attributes)
  costs 30 seconds and answers the question directly. Two wrong hypotheses were
  eliminated that way; the third was settled by extracting the failed
  recording's own final frames with `ffmpeg -sseof`, which showed the wizard
  page immediately. **The video is evidence — read it before theorising.**
- **One output path, one writer.** Two pipeline runs sharing an output file and
  a status log produced a log that read as a clean 47-second run while the real
  recording was still going, and re-muxed a stale video into the output path.
  If a previous run may still be alive, confirm it is dead before starting
  another; `TaskStop` kills the host shell, not the pytest inside the container.
- **Drift correction earns its keep on long videos.** `mux_narration` scales
  offsets by the video/wall ratio. That was ~1.00 on an 80s recording but 0.985
  on a 171s one, which is 2.5s of drift. Keep it.
- **Do not let the narration teardown mask a real failure.** The "beats never
  spoken" assertion only fires when the test passed; otherwise it buries the
  actual error.
- Playwright leaves temp recordings named as 32-char hex; delete only those.
- Output files are written as root — `sudo chown -R ubuntu:ubuntu screencasts/output/`
  before copying anything off the box.
- **The seed is part of the argument.** A recording that shows one SBOM per
  component while the narration says "every artifact, versioned", or opens the
  auto-created `latest` release while the line says "not the latest of
  everything", is arguing against its own script. Both shipped. When a chapter
  sells a feature, check the fixture actually exercises it — version history,
  a tagged release, an advisory that names a product and carries a CVSS.
- **Do not let the copy overclaim the product.** "A CycloneDX VEX document"
  read as CycloneDX-only; `vex_formats.py` takes OpenVEX and CSAF 2.0 as well.
  Name what is on screen without implying it is the only option.
- **The brand mark moves.** The splash and title cards used `logo-circle.svg`
  long after the app stopped referencing it anywhere. The current mark is the
  bar emblem plus wordmark — `sbomify-white.svg`, the same artwork the app
  renders inline from `core/components/brand/logo.html.j2`.
- **A card that outlives its line, or dies before it.** `title_card` holds for
  `hold_ms` and then fades regardless of the narration. The closing card held
  3.6s against a 15.7s line, so the tour spoke its call to action over a
  product page with the URL long gone. `linger=True` keeps the card up and lets
  `settle()` end the recording on it.
