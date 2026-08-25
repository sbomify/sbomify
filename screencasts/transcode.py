"""Re-encode a finished recording from VP8 to VP9.

Playwright writes its video as **VP8**, and VP8 bands visibly on this app's
flat background gradients — the artefact reads as faint horizontal steps across
the dark surfaces. VP9 at crf 24 removes it at a similar file size.

This used to be bundled into ``retime.py`` alongside the shoot-slow-play-fast
speed change. That mechanism is gone (it existed to work around a
software-rendering capture ceiling on a GPU-less Linux VM, and recording on a
machine with a real GPU removes the reason for it), but the quality pass is
worth keeping on its own.

Timestamps are passed through untouched, so this cannot shift the narration
timeline: run it **before** ``mux_narration.py``, which reads the manifest and
lays the audio on afterwards.

    python screencasts/transcode.py                    # every recording
    python screencasts/transcode.py marketplace_walkthrough
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# Playwright names a recording in progress with a 32-char hex string.
_PLAYWRIGHT_TEMP = re.compile(r"[0-9a-f]{32}")

CRF = 24
# Idempotence marker, so a re-run after a partial failure does not re-encode
# something already converted (which would compound generation loss).
MARKER_SUFFIX = ".transcoded.json"


def transcode(name: str) -> None:
    source = OUTPUT_DIR / f"{name}.webm"
    marker = OUTPUT_DIR / f"{name}{MARKER_SUFFIX}"
    if not source.exists():
        print(f"[transcode] {name}: no recording, skipped")
        return
    if marker.exists():
        print(f"[transcode] {name}: already VP9, skipped")
        return

    destination = OUTPUT_DIR / f"{name}.vp9.webm"
    subprocess.run(  # nosec B607 - ffmpeg/ffprobe by name from PATH, fixed argv, shell=False
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            # No audio here: narration is muxed on afterwards from the manifest.
            "-an",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(CRF),
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "4",
            str(destination),
        ],
        check=True,
    )
    destination.replace(source)
    marker.write_text(json.dumps({"codec": "vp9", "crf": CRF}) + "\n")
    print(f"[transcode] {name}: VP9 crf {CRF}, timestamps untouched")


def main() -> None:
    # Playwright writes its in-progress recordings as 32-character hex names
    # and only renames them at save time. Those leftovers have no dot in their
    # stem either, so the previous filter took them too — a full run spent its
    # first minutes re-encoding files nothing would ever play.
    names = sys.argv[1:] or sorted(
        p.stem for p in OUTPUT_DIR.glob("*.webm") if "." not in p.stem and not _PLAYWRIGHT_TEMP.fullmatch(p.stem)
    )
    for name in names:
        transcode(name)


if __name__ == "__main__":
    main()
