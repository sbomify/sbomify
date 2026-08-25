"""Add per-character speech timings to cache entries recorded before they existed.

The cache key is (text, voice, speed, pronunciations), so a clip synthesized
before ``char_times`` was stored stays a cache hit forever and never acquires
them — which meant the subtitle fix silently applied to exactly the one beat
whose copy had changed, while the other thirty-two kept the old proportional
split.  Re-requesting produces the same audio from the same inputs; only the
timings are new, so the committed ``.opus`` files are left untouched.

    python screencasts/backfill_timings.py                     # every entry
    python screencasts/backfill_timings.py marketplace_walkthrough
"""

from __future__ import annotations

import json
import sys

from narrator import INDEX_PATH, load_pronunciations, load_script, synthesize


def wanted_texts(names: list[str]) -> set[tuple[str, str, float]] | None:
    """``(text, voice, speed)`` for the named recordings, or None for all."""
    if not names:
        return None
    wanted: set[tuple[str, str, float]] = set()
    for name in names:
        script = load_script(name)
        for beat in script["beats"].values():
            wanted.add((beat["text"], script["voice"], float(script["speed"])))
    return wanted


def main() -> None:
    index = json.loads(INDEX_PATH.read_text())
    replace = load_pronunciations()
    targets = wanted_texts(sys.argv[1:])

    pending = [
        (sha, entry)
        for sha, entry in index.items()
        if not entry.get("char_times")
        and (targets is None or (entry["text"], entry["voice"], float(entry["speed"])) in targets)
    ]
    if not pending:
        print("[backfill] every entry already carries timings")
        return

    print(f"[backfill] {len(pending)} entr{'y' if len(pending) == 1 else 'ies'} to refresh")
    for number, (sha, entry) in enumerate(pending, start=1):
        _, duration, char_times = synthesize(
            entry["text"], voice=entry["voice"], speed=float(entry["speed"]), replace=replace
        )
        if not char_times:
            print(f"[backfill] {number}/{len(pending)} {sha[:12]} — API returned no timings, left alone")
            continue
        # The audio file is not rewritten: same inputs, same speech.  The
        # duration is left alone too, so a manifest recorded against the old
        # value stays consistent with the audio already on disk.
        entry["char_times"] = [[c, a, b] for c, a, b in char_times]
        print(f"[backfill] {number}/{len(pending)} {sha[:12]} — {len(char_times)} chars timed")

    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"[backfill] wrote {INDEX_PATH.name}")


if __name__ == "__main__":
    main()
