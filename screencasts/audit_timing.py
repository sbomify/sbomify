"""Report where narration and picture disagree, per beat.

The pacing check in the skill measures *silence* — total spoken time against
total wall clock — and a recording can score 2% silence while every line in it
is describing the wrong screen.  That is the failure this reports instead: a
beat that starts on one surface and ends on another, or a surface that changes
with nobody saying anything about it.

It joins the two timelines the recording writes into
``<name>.narration.json``: ``beats`` (when each line was spoken, and where the
recording was standing when it started) and ``scenes`` (every surface the
recording landed on, with the offset it arrived).  Both are on the finished
timeline, so ``SCREENCAST_SLOWDOWN`` does not change the numbers.

Three findings, worst first:

**STRADDLE** — the line is split down the middle by a navigation, so the viewer
gets half a sentence about each of two pages.  Crossing a navigation is *not*
itself a defect: the house style calls ``narrate`` just before the move, so a
line properly opens on the old page for a beat and then plays over the new one.
The fix is to move the ``narrate`` call, not to pad the dwell.

**FROZEN** — the picture holds still for a long stretch inside one line,
because the visual work for that beat finished early and ``narrate`` is waiting
out the audio.  A little is fine and gives the viewer a chance to read; a lot
reads as a stuck recording.

**SLACK** — the line and the picture under it are different lengths.  This is
the root cause of most of the rest, and the only one with a direct remedy: the
report says how many seconds and roughly how many words to add or cut.  Audio
duration is fixed by the synthesizer and known before recording; visual
duration is whatever the actions take.  Nothing used to compare them.

**SILENT SCENE** — a surface nobody narrates.  Usually a transitional page the
tour passes through, which is worth cutting rather than describing.

    python screencasts/audit_timing.py                    # every manifest
    python screencasts/audit_timing.py marketplace_walkthrough
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# A line that crosses a navigation is fine as long as it is clearly *about* one
# side of it.  Only when both halves exceed this is it genuinely split, with
# the viewer getting part of a sentence over each of two pages.
STRADDLE_TOLERANCE_S = 4.0

# A surface held this long with nobody narrating it is worth cutting.
SILENT_SCENE_TOLERANCE_S = 1.5

# How far a line and its visual may differ before it is worth reporting.  Under
# this the hold reads as a natural beat rather than a stall.
SLACK_TOLERANCE_S = 2.5

# Measured delivery rate of the walkthrough family, used to turn a slack figure
# into "cut about N words" rather than leaving it as bare seconds.
WORDS_PER_SECOND = 157 / 60

# How long the picture may sit still inside a single line.  Beyond this the
# viewer has read everything on screen and is waiting for the voice.
FROZEN_TOLERANCE_S = 6.0


SAMPLE_HZ = 2

# Mean absolute luma change between consecutive samples, below which the frame
# counts as unchanged.  A still page still registers a little noise from the
# encoder, so this is not zero.
STILL_THRESHOLD = 0.35


def video_activity(video: Path) -> list[tuple[float, float]]:
    """``(offset_s, change)`` twice a second, from the finished video.

    ``tblend=difference`` leaves a frame holding only what moved between two
    samples; ``signalstats`` reduces that to one number.  This is the honest
    way to ask whether the picture is moving.  ``freezedetect`` is not: the
    recorder captures at 12-16 unique fps, so it reports the *capture rate* as
    a metronome of 1.7s freezes on footage that is visibly in motion.
    """
    if not video.exists():
        return []
    out = subprocess.run(  # nosec B607 - ffmpeg/ffprobe by name from PATH, fixed argv, shell=False
        [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"movie={video},fps={SAMPLE_HZ},tblend=all_mode=difference,signalstats",
            "-show_entries",
            "frame_tags=lavfi.signalstats.YAVG",
            "-of",
            "csv=p=0",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    values = [float(v) for v in out.split() if v.replace(".", "", 1).replace("-", "", 1).isdigit()]
    return [(i / SAMPLE_HZ, v) for i, v in enumerate(values)]


def longest_still_run(activity: list[tuple[float, float]], start: float, end: float) -> float:
    """Longest unbroken stretch inside ``[start, end]`` where nothing moves."""
    best = run = 0.0
    for t, change in activity:
        if t < start or t > end:
            continue
        if change < STILL_THRESHOLD:
            run += 1 / SAMPLE_HZ
            best = max(best, run)
        else:
            run = 0.0
    return best


@dataclass
class Finding:
    kind: str
    severity: float
    beat: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:14} {self.severity:5.1f}s  {self.beat:24} {self.detail}"


def audit(name: str) -> list[Finding]:
    manifest = OUTPUT_DIR / f"{name}.narration.json"
    if not manifest.exists():
        raise SystemExit(f"no manifest at {manifest}")
    data = json.loads(manifest.read_text())
    beats = data["beats"]
    scenes = data.get("scenes")
    if not scenes:
        raise SystemExit(
            f"{name}: manifest has no scene log — re-record with the current conftest, "
            "which records every surface the tour lands on"
        )

    activity = video_activity(OUTPUT_DIR / f"{name}.webm")

    findings: list[Finding] = []

    def scene_at(t: float) -> str:
        current: str = scenes[0]["url"]
        for s in scenes:
            if s["offset_ms"] / 1000 <= t:
                current = s["url"]
            else:
                break
        return current

    for beat in beats:
        slack_ms = beat.get("slack_ms")
        if slack_ms is not None and abs(slack_ms) / 1000 > SLACK_TOLERANCE_S:
            slack = slack_ms / 1000
            words = abs(slack) * WORDS_PER_SECOND
            if slack > 0:
                detail = (
                    f"line runs {slack:.1f}s past its visual "
                    f"(audio {beat['duration']:.1f}s vs picture {beat['visual_ms'] / 1000:.1f}s) "
                    f"— cut about {words:.0f} words, or give the beat more to show"
                )
            else:
                detail = (
                    f"visual runs {-slack:.1f}s past its line "
                    f"(audio {beat['duration']:.1f}s vs picture {beat['visual_ms'] / 1000:.1f}s) "
                    f"— add about {words:.0f} words, or shorten the dwell"
                )
            findings.append(Finding("SLACK", abs(slack), beat["key"], detail))

        start = beat["offset_ms"] / 1000
        end = start + beat["duration"]
        opened_on = scene_at(start)
        closed_on = scene_at(end)

        if opened_on != closed_on:
            # A line crossing a navigation is normal and is in fact the house
            # style: `narrate` is called just *before* the move, so the line
            # opens on the old page for a moment and then plays over the new
            # one as it paints.  A short lead-in is therefore correct, and an
            # earlier version of this check reported exactly that as the
            # defect — every transition in a correctly ordered recording.
            #
            # The real defect is a line split down the middle, where the viewer
            # gets half a sentence about each of two pages.
            nav_at = next((s["offset_ms"] / 1000 for s in scenes if start < s["offset_ms"] / 1000 < end), end)
            lead_in = nav_at - start
            after = end - nav_at
            if lead_in > STRADDLE_TOLERANCE_S and after > STRADDLE_TOLERANCE_S:
                findings.append(
                    Finding(
                        "STRADDLE",
                        min(lead_in, after),
                        beat["key"],
                        f"{lead_in:.1f}s on {opened_on} then {after:.1f}s on {closed_on} — split across both",
                    )
                )

        # Is the picture actually still?  Measured from the video, not from the
        # URL: a page can scroll, hover and type without navigating, and an
        # earlier version of this check called all of that "frozen".
        if activity:
            still = longest_still_run(activity, start, end)
            if still > FROZEN_TOLERANCE_S:
                findings.append(
                    Finding("FROZEN", still, beat["key"], f"picture is still for {still:.1f}s while the line runs")
                )

    # Surfaces nobody talks about.
    spoken_windows = [(b["offset_ms"] / 1000, b["offset_ms"] / 1000 + b["duration"]) for b in beats]
    for i, scene in enumerate(scenes):
        s_start = scene["offset_ms"] / 1000
        s_end = scenes[i + 1]["offset_ms"] / 1000 if i + 1 < len(scenes) else data["wall_duration_ms"] / 1000
        # Does any beat *begin* while this scene is up?
        if not any(s_start <= b_start < s_end for b_start, _ in spoken_windows):
            held = s_end - s_start
            if held > SILENT_SCENE_TOLERANCE_S:
                findings.append(
                    Finding("SILENT SCENE", held, "-", f"{scene['url']} held {held:.1f}s, no line opens on it")
                )

    findings.sort(key=lambda f: -f.severity)
    return findings


def main() -> None:
    names = sys.argv[1:] or sorted(p.stem.removesuffix(".narration") for p in OUTPUT_DIR.glob("*.narration.json"))
    total = 0
    for name in names:
        findings = audit(name)
        total += len(findings)
        print(f"\n=== {name} ===")
        if not findings:
            print("  picture and narration agree everywhere")
        for f in findings:
            print(f"  {f}")
    print(f"\n{total} finding(s)")


if __name__ == "__main__":
    main()
