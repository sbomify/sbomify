#!/usr/bin/env python3
"""Lay each screencast's voice-over onto its video, and write its captions.

A recording is captured silently by Playwright inside the test container, and
leaves a ``<name>.narration.json`` beside its ``<name>.webm``: every line it
spoke, when, and which cached clip holds it (see ``screencasts/conftest.py``).
This runs on the host, where ffmpeg is, and for each cue file:

- mixes the clips into one track, each delayed to the moment its caption
  appeared, and muxes it into the ``.webm`` as Opus (the video is copied, not
  re-encoded);
- writes ``<name>.vtt``, the same lines as WebVTT, so a page embedding the
  video can offer captions and search engines can read what it says.

The cue file is removed once its video has been muxed, so running this twice
does not stack a second track on the first. Standard library only.

Usage: bin/mux_screencast_narration.py [screencasts/output]
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "screencasts" / "output"


def _timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def write_vtt(cues: list[dict[str, Any]], path: Path) -> None:
    lines = ["WEBVTT", ""]
    for index, cue in enumerate(cues, start=1):
        start = cue["at"]
        end = start + cue["duration"]
        # A caption stays up until the next line replaces it; never overlap.
        if index < len(cues):
            end = min(end + 0.5, cues[index]["at"])
        lines += [str(index), f"{_timestamp(start)} --> {_timestamp(end)}", cue["text"], ""]
    path.write_text("\n".join(lines))


def mux(cue_file: Path, output_dir: Path) -> None:
    spec = json.loads(cue_file.read_text())
    video = output_dir / spec["video"]
    cues = spec["cues"]
    if not video.exists():
        sys.stderr.write(f"skip {cue_file.name}: {video.name} is missing\n")
        return

    inputs: list[str] = ["-i", str(video)]
    filters: list[str] = []
    for index, cue in enumerate(cues, start=1):
        inputs += ["-i", str(output_dir / cue["audio"])]
        delay = max(0, round(cue["at"] * 1000))
        filters.append(f"[{index}:a]adelay={delay}:all=1[a{index}]")
    mix_inputs = "".join(f"[a{index}]" for index in range(1, len(cues) + 1))
    # normalize=0: lines never overlap, so amix must not scale each one down by
    # the number of inputs. apad + shortest keeps the audio exactly as long as
    # the video, however the last line falls.
    filters.append(f"{mix_inputs}amix=inputs={len(cues)}:normalize=0,apad[voice]")

    muxed = video.with_suffix(".muxed.webm")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v",
        "-map",
        "[voice]",
        "-c:v",
        "copy",
        "-c:a",
        "libopus",
        "-b:a",
        "96k",
        "-shortest",
        str(muxed),
    ]
    subprocess.run(command, check=True)  # nosec B603
    muxed.replace(video)
    write_vtt(cues, video.with_suffix(".vtt"))
    cue_file.unlink()
    sys.stdout.write(f"narrated {video.name} ({len(cues)} lines)\n")


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    cue_files = sorted(output_dir.glob("*.narration.json"))
    if not cue_files:
        return 0
    if shutil.which("ffmpeg") is None:
        sys.stderr.write("ffmpeg not found; videos left silent\n")
        return 1
    for cue_file in cue_files:
        mux(cue_file, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
