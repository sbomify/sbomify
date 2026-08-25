"""Lay a music bed under a narrated screencast.

Music under instruction is not free.  Mayer's *coherence principle* — that
learners do better when extraneous material is left out — was tested against
background music directly by Moreno and Mayer (2000), who found it depressed
both retention and transfer.  So this stage is deliberately **not** wired into
``bin/record_screencasts.sh``.  It is for the marketplace walkthrough, which is
shown to a cold audience that has to be persuaded to care.  The FAQ recordings
answer a question somebody already has, and they should stay dry.

A track shorter than the video can be fitted two ways.

**End-aligned** (the default) starts the music late enough that its own composed
fade-out lands on the final frame, and snaps the entry to a chapter boundary so
it arrives on a scene change rather than mid-sentence.  The head, the most
sparse and least missed part, absorbs the trim.  The opening runs dry.

**Looped** (``--loop``) covers the whole video by playing one passage twice,
crossfaded.  The catch is that a composed track is not homogeneous: ``Ledger
Trace`` builds, so splicing its busy stretch onto its sparse opening is audible
however long the fade.  So the loop point is *measured*, not picked from the
clock — :func:`band_energy` profiles 300-4000 Hz (where the ear tracks texture)
and :func:`choose_loop` puts the repeat where the two crossfade windows sound
most alike.  On this track that is 186s back to 34s: 2.8 dB mean mismatch,
against 5.4 dB for the obvious "loop back to the top".  The tail is never
looped through, so the composed fade-out still lands on the last frame.

Three things keep it out of the way of the voice:

* **Level.**  Both tracks are measured with ``ebur128`` and a static gain puts
  the music ``--under`` LU below the narration.  A fixed gain is used rather
  than ``loudnorm`` because a second normalisation pass would re-compress a
  track whose 3.5 LU range is already exactly what we want.
* **A carve at 2 kHz.**  Speech intelligibility lives in 1-4 kHz.  A gentle
  bell there buys clarity far more cheaply than pulling the whole bed down.
* **Ducking.**  ``sidechaincompress`` keyed off the narration leans the music
  back a few dB while anybody is talking, and lets it return in the gaps —
  which, in the tour, are the title cards between chapters.

The video stream is copied, never re-encoded, so this cannot undo the quality
won by ``transcode.py``.

Usage::

    python screencasts/score.py marketplace_walkthrough ~/"Ledger Trace.m4a"
    python screencasts/score.py marketplace_walkthrough track.m4a --under 10
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# How far under the narration the bed sits, in LU.  Broadcast practice for
# music under speech is 8-12; the upper end suits a track with content in the
# vocal band, which this one has in its back half.
DEFAULT_UNDER_LU = 12.0

# Depth of the 1-4 kHz carve.  Wide and shallow: a deep notch is audible as a
# hole in the music, a shallow bell just makes room.
VOICE_CARVE_HZ = 2000
VOICE_CARVE_Q = 1.2
VOICE_CARVE_DB = -3.0

# Ducking.  A slow release keeps the bed from pumping between sentences; the
# narration has [long-pause] gaps of well over a second and the music should
# not surge into every one of them.
#
# These were swept against a narrated recording and the depth measured by
# phase-cancelling the mix against the original, rather than guessed.  The
# first attempt here (threshold 0.03, ratio 4) put the sidechain ~20 dB over
# threshold for the whole tour and buried the bed 12 dB under its own target.
# Depth is very sensitive to how dense the narration is — the same settings
# measured 4.9 dB against a sparser clip — so re-measure rather than assume.
DUCK_THRESHOLD = 0.05
DUCK_RATIO = 2
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 600

# The most we will shave off the music's head to land the entry on a chapter
# boundary.  Beyond this we are discarding composed material rather than
# trimming an intro.
MAX_HEAD_TRIM_S = 35.0

# Looping.  Long enough that a pad has time to trade places rather than
# switch; short enough not to smear two different passages into mud.
LOOP_CROSSFADE_S = 8.0

# The last stretch of the track is never looped through — it holds the composed
# fade-out, which has to land on the final frame.
LOOP_TAIL_KEEP_S = 20.0


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stderr


def duration_of(path: Path) -> float:
    out = subprocess.run(  # nosec B607 - ffmpeg/ffprobe by name from PATH, fixed argv, shell=False
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def integrated_lufs(path: Path) -> float:
    """EBU R128 integrated loudness, in LUFS."""
    stderr = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"])
    matches = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", stderr)
    if not matches:
        raise RuntimeError(f"could not measure loudness of {path.name}")
    return float(matches[-1])


def chapter_offsets(manifest: Path) -> list[float]:
    """Seconds at which each chapter bridge is spoken, from the mux manifest.

    These are the scene changes — the title cards — and so the only places the
    music can enter without sounding like it was switched on mid-sentence.
    """
    if not manifest.exists():
        return []
    beats = json.loads(manifest.read_text())["beats"]
    return [b["offset_ms"] / 1000.0 for b in beats if b["key"].startswith("chapter_")]


def choose_start(video_s: float, music_s: float, candidates: list[float]) -> tuple[float, float]:
    """Return ``(start_s, head_trim_s)`` for an end-aligned bed.

    The natural start puts the music's last sample on the video's last frame.
    Snapping earlier to a chapter boundary buys a clean entry, and the head is
    trimmed by the same amount so the tail still lands where it should.
    """
    natural = video_s - music_s
    if natural <= 0:
        # Music outlasts the video: trim the head, start at zero.
        return 0.0, -natural

    usable = [c for c in candidates if 0 < c <= natural and natural - c <= MAX_HEAD_TRIM_S]
    if not usable:
        return natural, 0.0
    start = max(usable)
    return start, natural - start


def band_energy(path: Path, lo: int = 300, hi: int = 4000) -> list[tuple[float, float]]:
    """Per-second loudness of ``path`` between ``lo`` and ``hi`` Hz.

    Used to pick a loop point by *texture* rather than by the clock.  A track
    that builds is not interchangeable with itself: splicing its busy last
    minute back onto its sparse opening is audible however long the crossfade.
    """
    stderr = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"highpass=f={lo},lowpass=f={hi},ebur128",
            "-f",
            "null",
            "-",
        ]
    )
    values = [float(m) for m in re.findall(r"M:\s*(-?[\d.]+)", stderr)]
    # ebur128 reports momentary loudness every 100ms.
    return [(i / 10.0, v) for i, v in enumerate(values)]


def choose_loop(video_s: float, music_s: float, profile: list[tuple[float, float]]) -> tuple[float, float]:
    """Return ``(loop_out_s, loop_in_s)`` for one crossfaded internal repeat.

    The bed has to cover ``video_s`` from ``music_s`` of material, so exactly
    ``video_s - music_s + LOOP_CROSSFADE_S`` seconds have to be played twice.
    That length is fixed; the only freedom is *where* the repeat sits, so put
    it where the music sounds most alike at both ends.

    The tail is never looped: its composed fade-out is what lands on the final
    frame.
    """
    repeat = video_s - music_s + LOOP_CROSSFADE_S
    tail_starts = music_s - LOOP_TAIL_KEEP_S

    def level_at(t: float) -> float:
        return min(profile, key=lambda p: abs(p[0] - t))[1] if profile else 0.0

    best: tuple[float, float, float] | None = None
    loop_in = LOOP_CROSSFADE_S
    while loop_in + repeat <= tail_starts:
        loop_out = loop_in + repeat
        # Compare the crossfade windows, not two instants: a single frame can
        # match by luck while the passages around it do not.
        #
        # `acrossfade` fades the *end* of the head out against the *start* of
        # the tail, so the two windows are [loop_out - d, loop_out] and
        # [loop_in, loop_in + d].  Lining both up against loop_out's window was
        # an off-by-one-crossfade that scored the wrong passage.
        mismatch = sum(
            abs(level_at(loop_out - LOOP_CROSSFADE_S + d) - level_at(loop_in + d)) for d in range(int(LOOP_CROSSFADE_S))
        )
        if best is None or mismatch < best[0]:
            best = (mismatch, loop_out, loop_in)
        loop_in += 1.0

    if best is None:
        raise SystemExit(
            f"cannot loop: needs {repeat:.0f}s of repeat from a {music_s:.0f}s track — supply a longer one"
        )
    return best[1], best[2]


def build(name: str, music: Path, under_lu: float, start_override: float | None, loop: bool) -> Path:
    # The mux is kept as a sidecar and the scored mix takes the plain name.
    #
    # Scoring has to read a dry mux — running it over its own output would
    # stack a second bed — but the file anyone plays or ships must be the
    # finished one. A mix missing its bed still plays perfectly, so getting
    # this the other way round fails silently, and it has.
    #
    # mux_narration deletes the sidecar whenever it rewrites a recording, so a
    # sidecar existing means it matches the current mux rather than an older
    # one.
    video = OUTPUT_DIR / f"{name}.dry.webm"
    scored = OUTPUT_DIR / f"{name}.webm"
    if not video.exists():
        video = scored
    if not video.exists():
        raise SystemExit(f"no recording at {video}")

    video_s = duration_of(video)
    music_s = duration_of(music)
    narration_lufs = integrated_lufs(video)
    music_lufs = integrated_lufs(music)

    gain_db = (narration_lufs - under_lu) - music_lufs
    loop_note = ""

    # A track longer than the cut needs no repeat, and asking for one would ask
    # choose_loop for a negative-length passage. Callers can pass --loop for a
    # whole batch of mixed lengths and let each one decide.
    if loop and music_s < video_s:
        loop_out, loop_in = choose_loop(video_s, music_s, band_energy(music))
        start, head_trim, delay_ms = 0.0, 0.0, 0
        # Two copies of the track, the first cut at the loop-out point and the
        # second entered at the loop-in point, crossfaded into one another.
        source = (
            f"[1:a]asplit=2[la][lb];"
            f"[la]atrim=end={loop_out:.3f},asetpts=PTS-STARTPTS[lhead];"
            f"[lb]atrim=start={loop_in:.3f},asetpts=PTS-STARTPTS[ltail];"
            f"[lhead][ltail]acrossfade=d={LOOP_CROSSFADE_S:.0f}:c1=tri:c2=tri[looped];"
            f"[looped]"
        )
        loop_note = f"looped: repeat {loop_out - loop_in:.0f}s, out at {loop_out:.0f}s back to {loop_in:.0f}s"
    else:
        candidates = chapter_offsets(OUTPUT_DIR / f"{name}.narration.json")
        if start_override is None:
            start, head_trim = choose_start(video_s, music_s, candidates)
        else:
            start = start_override
            head_trim = max(0.0, music_s - (video_s - start))
        delay_ms = int(round(start * 1000))
        source = f"[1:a]atrim=start={head_trim:.3f},asetpts=PTS-STARTPTS,"

    chain = (
        f"{source}"
        f"volume={gain_db:.2f}dB,"
        f"equalizer=f={VOICE_CARVE_HZ}:t=q:w={VOICE_CARVE_Q}:g={VOICE_CARVE_DB},"
        f"adelay={delay_ms}|{delay_ms},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[bed];"
        f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[narr][key];"
        f"[bed][key]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
        f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}[ducked];"
        f"[narr][ducked]amix=inputs=2:duration=first:normalize=0[out]"
    )

    out = OUTPUT_DIR / f"{name}.scoring.webm"
    subprocess.run(  # nosec B607 - ffmpeg/ffprobe by name from PATH, fixed argv, shell=False
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-i",
            str(music),
            "-filter_complex",
            chain,
            "-map",
            "0:v",
            "-map",
            "[out]",
            "-c:v",
            "copy",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            str(out),
        ],
        check=True,
    )

    bed_lufs = measure_bed(video, out)
    nominal = narration_lufs - under_lu

    # Swap into place only now, so a failed encode above leaves the previous
    # pair untouched rather than half-renamed.
    if video != scored:
        scored.unlink(missing_ok=True)
    else:
        video.rename(OUTPUT_DIR / f"{name}.dry.webm")
    out.rename(scored)
    out = scored

    print(f"[score] {name}: video {video_s:.1f}s, music {music_s:.1f}s")
    print(f"[score]   narration {narration_lufs:.1f} LUFS, music {music_lufs:.1f} LUFS -> bed {gain_db:+.1f} dB")
    if loop_note:
        print(f"[score]   {loop_note}")
    elif head_trim:
        print(f"[score]   entry snapped to {start:.1f}s, head trimmed {head_trim:.1f}s")
    else:
        print(f"[score]   entry at {start:.1f}s (no chapter boundary in reach)")
    print(
        f"[score]   bed measured {bed_lufs:.1f} LUFS = {narration_lufs - bed_lufs:.1f} LU "
        f"under narration (target {under_lu:.0f}, ducking accounts for "
        f"{nominal - bed_lufs:+.1f})"
    )
    # Spelled out because the two files sit side by side in the same directory
    # and the dry one has the more obvious name. Shipping the mux by mistake is
    # a silent failure: it plays fine, it is just missing the bed.
    print(f"[score]   wrote {out.name} (mux kept as {name}.dry.webm)")
    return out


def measure_bed(original: Path, scored: Path) -> float:
    """Loudness of the bed alone, recovered by cancelling the narration.

    The scored mix is the narration plus the ducked bed, so inverting the
    original and summing leaves the bed — including whatever the ducker did to
    it.  This is the only honest way to report the level: the static gain is
    easy to compute and says nothing about what the listener ends up hearing.
    """
    stderr = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(scored),
            "-i",
            str(original),
            "-filter_complex",
            "[1:a]volume=-1[inv];[0:a][inv]amix=inputs=2:duration=shortest:normalize=0,ebur128",
            "-f",
            "null",
            "-",
        ]
    )
    matches = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", stderr)
    return float(matches[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording")
    parser.add_argument("music", type=Path)
    parser.add_argument("--under", type=float, default=DEFAULT_UNDER_LU, help="LU below the narration to place the bed")
    parser.add_argument("--start", type=float, default=None, help="force the music entry, in seconds")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="cover the whole video by repeating a passage, instead of end-aligning",
    )
    args = parser.parse_args()
    build(args.recording, args.music, args.under, args.start, args.loop)


if __name__ == "__main__":
    main()
