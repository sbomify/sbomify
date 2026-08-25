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

Recordings are encoded several at a time. libvpx-vp9 stops scaling long before
it saturates a modern desktop — one encode here sat at a load of 3 on 12
threads — so the batch finishes far sooner running four encodes of four threads
than one encode allowed to sprawl.

    python screencasts/transcode.py                    # every recording
    python screencasts/transcode.py marketplace_walkthrough
    SCREENCAST_TRANSCODE_JOBS=1 python screencasts/transcode.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# Playwright names a recording in progress with a 32-char hex string.
_PLAYWRIGHT_TEMP = re.compile(r"[0-9a-f]{32}")

# Intermediates the other steps leave beside a recording. They are already VP9,
# and the dry mux in particular would be re-encoded on every run.
_SIDECARS = (".dry", ".scored", ".scoring", ".narrated")

CRF = 24
# Idempotence marker, so a re-run after a partial failure does not re-encode
# something already converted (which would compound generation loss).
MARKER_SUFFIX = ".transcoded.json"

# Pinned rather than left to libvpx, which sizes its pool from the whole
# machine and would then have every concurrent encode contending for it.
# Four is about where a single VP9 encode stops going faster.
THREADS_PER_JOB = 4


def _jobs() -> int:
    override = os.environ.get("SCREENCAST_TRANSCODE_JOBS")
    if override:
        return max(1, int(override))
    return max(1, (os.cpu_count() or THREADS_PER_JOB) // THREADS_PER_JOB)


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
            "-threads",
            str(THREADS_PER_JOB),
            "-cpu-used",
            "4",
            str(destination),
        ],
        check=True,
    )
    destination.replace(source)
    marker.write_text(json.dumps({"codec": "vp9", "crf": CRF}) + "\n")
    print(f"[transcode] {name}: VP9 crf {CRF}, timestamps untouched", flush=True)


def main() -> None:
    # Playwright writes its in-progress recordings as 32-character hex names
    # and only renames them at save time, so a run that skipped them spent its
    # first minutes re-encoding files nothing would ever play.
    #
    # Sidecars are matched by name rather than by "has a dot in the stem",
    # which is what this did first: a recording is free to have a dot of its
    # own, and `plugin_enablement_bsi-tr03183-v2.1-compliance` does. It was the
    # one clip that shipped as raw VP8, silently, because the filter read the
    # version number as a sidecar suffix.
    names = sys.argv[1:] or sorted(
        p.stem
        for p in OUTPUT_DIR.glob("*.webm")
        if not _PLAYWRIGHT_TEMP.fullmatch(p.stem) and not p.stem.endswith(_SIDECARS)
    )
    jobs = min(_jobs(), len(names)) or 1
    if jobs == 1:
        for name in names:
            transcode(name)
        return

    print(f"[transcode] {len(names)} recording(s), {jobs} at a time", flush=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        # list() so an exception in any encode surfaces here rather than being
        # swallowed with the future that carried it.
        list(pool.map(transcode, names))


if __name__ == "__main__":
    main()
