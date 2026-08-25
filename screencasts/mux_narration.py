"""Lay narration clips back onto a recorded screencast, and cut its subtitles.

``conftest.narrate`` records, for every spoken beat, the offset from the start
of the recording at which it was heard.  This module rebuilds that timeline: it
decodes each cached clip, writes it into a silent buffer at its offset, and
muxes the result into the WebM alongside the untouched video stream.

Every narrated recording also gets a **WebVTT subtitle file** cut from those
same offsets, so the words are never re-timed by hand and cannot drift from the
audio.  Subtitles are not optional decoration here: a narrated recording
suppresses the on-screen lower-third captions (``conftest.caption``) because the
voice carries the explanation, which makes the ``.vtt`` the only path for a
viewer watching muted, deaf or hard of hearing, or scanning for a phrase.  It is
also what search engines index.

Publish the ``.vtt`` next to the ``.webm`` and reference it from a
``<track kind="subtitles" srclang="en" default>`` inside the player.

Run after recording::

    python screencasts/mux_narration.py             # every recording with a manifest
    python screencasts/mux_narration.py release_creation
"""

from __future__ import annotations

import array
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from narrator import INDEX_PATH, caption_from

OUTPUT_DIR = Path(__file__).parent / "output"
AUDIO_DIR = Path(__file__).parent / "narration" / "audio"

# Opus is natively 48 kHz, so assembling at that rate avoids a resample.
TRACK_SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2

# Playwright records variable-frame-rate VP8, so the file's own duration need
# not match wall-clock.  Correct for that only when the mismatch is plausible;
# anything outside this range means something else went wrong and silently
# stretching the narration would make it worse.
MIN_DRIFT_RATIO = 0.8
MAX_DRIFT_RATIO = 1.25

# Tail silence so a final line is never clipped by -shortest.
TAIL_PADDING_SEC = 0.5

LOUDNESS_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"

# Subtitle shape. Two lines of ~42 characters is the long-standing broadcast
# convention and what players lay out comfortably at 1080p.
MAX_LINE_CHARS = 42
MAX_CUE_CHARS = MAX_LINE_CHARS * 2


class MuxError(RuntimeError):
    """Raised when a narrated recording cannot be produced."""


@dataclass(frozen=True)
class Beat:
    key: str
    offset_ms: float
    duration: float
    sha: str
    caption: str
    # ``(char, start_s, end_s)`` for every character of the *spoken* text, tags
    # included, straight from the API.  None for a beat recorded before the
    # cache stored it, which falls the VTT back to a proportional split.
    char_times: list[tuple[str, float, float]] | None = None


def _log(message: str) -> None:
    print(f"[narration] {message}", file=sys.stderr)


def _run(command: list[str], stdin: bytes | None = None) -> bytes:
    result = subprocess.run(command, input=stdin, capture_output=True)
    if result.returncode != 0:
        raise MuxError(f"{command[0]} failed: {result.stderr.decode()[:400]}")
    return result.stdout


def probe_duration(path: Path) -> float:
    """Duration of a media file in seconds, via ffprobe."""
    out = _run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )  # fmt: skip
    return float(out.decode().strip())


def decode_pcm(path: Path) -> array.array:
    """Decode an audio file to mono signed-16 PCM at the track sample rate."""
    raw = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(TRACK_SAMPLE_RATE),
            "pipe:1",
        ]
    )  # fmt: skip
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % SAMPLE_WIDTH)])
    return samples


def _cached_timings() -> dict[str, list[tuple[str, float, float]]]:
    """Per-character timings from the audio cache, keyed by clip sha.

    A manifest written before the recorder stored timings has ``char_times``
    of None on every beat, and re-recording purely to obtain them would be
    absurd — the audio is identical, only the metadata is missing.  The cache
    is keyed by the same sha the manifest carries, so the two join.
    """
    if not INDEX_PATH.exists():
        return {}
    index = json.loads(INDEX_PATH.read_text())
    return {
        sha: [(c, float(a), float(b)) for c, a, b in entry["char_times"]]
        for sha, entry in index.items()
        if entry.get("char_times")
    }


def load_manifest(path: Path) -> tuple[str, float, list[Beat]]:
    data = json.loads(path.read_text())
    from_cache = _cached_timings()
    beats = [
        Beat(
            key=beat["key"],
            offset_ms=float(beat["offset_ms"]),
            duration=float(beat["duration"]),
            sha=beat["sha"],
            # Sanitized again here so a manifest written before speech tags
            # were stripped still produces clean captions.
            caption=caption_from(beat.get("caption", "")),
            char_times=(
                [(c, float(a), float(b)) for c, a, b in beat["char_times"]]
                if beat.get("char_times")
                else from_cache.get(beat["sha"])
            ),
        )
        for beat in data["beats"]
    ]
    return data["recording"], float(data["wall_duration_ms"]), beats


def drift_ratio(video_duration: float, wall_duration_ms: float) -> float:
    """How much the recorded video's timeline is stretched vs. wall-clock."""
    if wall_duration_ms <= 0:
        return 1.0
    return video_duration * 1000 / wall_duration_ms


def build_track(beats: list[Beat], scale: float, video_duration: float) -> bytes:
    """Render the narration timeline as a single mono WAV-ready PCM buffer."""
    scaled = [(beat, beat.offset_ms * scale / 1000) for beat in beats]

    end_sec = max([video_duration] + [offset + beat.duration + TAIL_PADDING_SEC for beat, offset in scaled])
    track = array.array("h", bytes(int(end_sec * TRACK_SAMPLE_RATE) * SAMPLE_WIDTH))

    previous_end = 0.0
    for beat, offset in scaled:
        if offset < previous_end - 0.05:
            _log(f"beat '{beat.key}' starts {previous_end - offset:.2f}s before the previous line ends")
        previous_end = offset + beat.duration

        samples = decode_pcm(AUDIO_DIR / f"{beat.sha}.opus")
        start = int(offset * TRACK_SAMPLE_RATE)
        if start + len(samples) > len(track):
            track.extend(array.array("h", bytes((start + len(samples) - len(track)) * SAMPLE_WIDTH)))

        for i, sample in enumerate(samples):
            # Additive so an accidental overlap blends instead of truncating.
            mixed = track[start + i] + sample
            track[start + i] = max(-32768, min(32767, mixed))

    return track.tobytes()


def _timestamp(seconds: float) -> str:
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def _split_into_cues(text: str) -> list[str]:
    """Break one spoken line into readable subtitle-sized chunks.

    A narration beat runs up to ten seconds, which is far too much text to put
    on screen at once.  Chunks break at sentence ends where possible and on
    word boundaries otherwise.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > MAX_CUE_CHARS:
            chunks.append(" ".join(current))
            current = [word]
            continue
        current.append(word)
        # A sentence boundary is the most natural place to cut, but only once
        # the cue is long enough to be worth its own slot.
        if word.endswith((".", "?", "!")) and len(" ".join(current)) >= MAX_CUE_CHARS // 2:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


def _wrap(text: str) -> str:
    """Fold a cue onto at most two lines, the convention for readable subtitles."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join([*current, word])) > MAX_LINE_CHARS:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    if len(lines) <= 2:
        return "\n".join(lines)
    # Rebalance an over-long cue rather than emitting three cramped lines.
    midpoint = len(words) // 2
    return "\n".join([" ".join(words[:midpoint]), " ".join(words[midpoint:])])


def _caption_char_times(char_times: list[tuple[str, float, float]]) -> list[float]:
    """Start time for each character of the *caption*, from the raw timings.

    The API times the string it was given, tags and all; the caption is that
    string with tags stripped and whitespace collapsed.  Walking the raw
    characters and keeping only the ones that survive into the caption lines
    the two up exactly, which is what lets a cue boundary be placed at the
    moment the word is actually spoken.
    """
    out: list[float] = []
    depth_sq = depth_lt = 0
    last_was_space = True
    for char, start, _ in char_times:
        if char == "[":
            depth_sq += 1
            continue
        if char == "]":
            depth_sq = max(0, depth_sq - 1)
            continue
        if char == "<":
            depth_lt += 1
            continue
        if char == ">":
            depth_lt = max(0, depth_lt - 1)
            continue
        if depth_sq or depth_lt:
            continue
        if char.isspace():
            # Collapsed runs, and no leading space, to match caption_from.
            if last_was_space:
                continue
            last_was_space = True
            out.append(start)
            continue
        last_was_space = False
        out.append(start)
    return out


def write_vtt(destination: Path, beats: list[Beat], scale: float) -> None:
    """Cut WebVTT subtitles from the narration timeline.

    Cue times come from the same offsets and durations that placed the audio,
    so the words cannot drift from the voice.  *Within* a beat, cue boundaries
    come from the API's own per-character timings.

    They used to be a proportional split of the beat duration by cue length,
    which is wrong wherever speech is not uniform, and this script is full of
    places where it is not: a ``[long-pause]`` contributes 1.6 seconds of audio
    and no characters at all, so every cue after one ran ahead of the voice.
    """
    lines = ["WEBVTT", ""]
    index = 0

    for beat in beats:
        cues = _split_into_cues(beat.caption or beat.key)
        if not cues:
            continue

        start = beat.offset_ms * scale / 1000
        caption = beat.caption or beat.key
        stamps = _caption_char_times(beat.char_times) if beat.char_times else []
        # Only trust the timings if they line up with the caption we are about
        # to cut; a mismatch means the two came from different text.
        usable = len(stamps) >= len(caption)

        cursor = 0
        elapsed = 0.0
        total_chars = sum(len(cue) for cue in cues)

        for position, cue in enumerate(cues):
            if usable:
                cue_start = start + stamps[min(cursor, len(stamps) - 1)]
                # +1 for the space the split consumed between cues.
                cursor += len(cue) + 1
                if position == len(cues) - 1:
                    cue_end = start + beat.duration
                else:
                    cue_end = start + stamps[min(cursor, len(stamps) - 1)]
            else:
                share = beat.duration * (len(cue) / total_chars) if total_chars else beat.duration
                cue_start = start + elapsed
                elapsed += share
                cue_end = start + elapsed
            index += 1
            lines += [
                str(index),
                f"{_timestamp(cue_start)} --> {_timestamp(cue_end)}",
                _wrap(cue),
                "",
            ]

    destination.write_text("\n".join(lines))


def mux(video: Path, manifest_path: Path) -> None:
    recording, wall_duration_ms, beats = load_manifest(manifest_path)
    if not beats:
        _log(f"{recording}: manifest has no beats, skipping")
        return

    video_duration = probe_duration(video)
    ratio = drift_ratio(video_duration, wall_duration_ms)
    if MIN_DRIFT_RATIO <= ratio <= MAX_DRIFT_RATIO:
        scale = ratio
        _log(f"{recording}: video/wall ratio {ratio:.4f} — scaling narration offsets")
    else:
        scale = 1.0
        _log(
            f"{recording}: video/wall ratio {ratio:.4f} is outside "
            f"[{MIN_DRIFT_RATIO}, {MAX_DRIFT_RATIO}] — using unscaled offsets"
        )

    pcm = build_track(beats, scale, video_duration)
    track = video.with_suffix(".narration.wav")
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "s16le", "-ar", str(TRACK_SAMPLE_RATE), "-ac", "1",
            "-i", "pipe:0", str(track),
        ],
        stdin=pcm,
    )  # fmt: skip

    narrated = video.with_suffix(".narrated.webm")
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video), "-i", str(track),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-af", LOUDNESS_FILTER,
            "-c:a", "libopus", "-b:a", "48k",
            str(narrated),
        ]
    )  # fmt: skip

    narrated.replace(video)
    track.unlink(missing_ok=True)

    subtitles = video.with_suffix(".vtt")
    write_vtt(subtitles, beats, scale)

    spoken = sum(beat.duration for beat in beats)
    cues = sum(len(_split_into_cues(beat.caption or beat.key)) for beat in beats)
    _log(
        f"{recording}: muxed {len(beats)} beats ({spoken:.1f}s of narration) into "
        f"{video.name}, and wrote {cues} subtitle cues to {subtitles.name}"
    )


def main(argv: list[str]) -> int:
    names = argv[1:]
    if names:
        manifests = [OUTPUT_DIR / f"{name.removesuffix('.py')}.narration.json" for name in names]
    else:
        manifests = sorted(OUTPUT_DIR.glob("*.narration.json"))

    if not manifests:
        _log("no narration manifests found — nothing to mux")
        return 0

    failures = 0
    for manifest_path in manifests:
        if not manifest_path.exists():
            _log(f"no manifest at {manifest_path}")
            failures += 1
            continue
        video = manifest_path.with_name(manifest_path.name.replace(".narration.json", ".webm"))
        if not video.exists():
            _log(f"no recording at {video}")
            failures += 1
            continue
        try:
            mux(video, manifest_path)
        except MuxError as exc:
            _log(f"{video.stem}: {exc}")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
