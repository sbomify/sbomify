"""Narration synthesis for screencasts, backed by the xAI text-to-speech API.

Narration is a voiceover: every beat is synthesized to audio first, and the
Playwright script then keeps clicking and typing *underneath* the line while it
plays, pausing only so one line never runs into the next.  ``mux_narration``
later lays the clips back down at the offsets the recording captured.

Synthesis is content-addressed.  The cache key covers the spoken text, the
voice, the speed and the pronunciation map, so editing one line re-renders one
line and a re-record with unchanged copy makes no API calls at all.  Cached
audio is committed to the repository, which keeps recordings reproducible and
lets them run with no network and no API key.

Requests are issued on a background worker so the recording can synthesize the
*next* beat while the current one is playing; the API returns audio faster than
real time, so the wait never reaches the screen.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

NARRATION_DIR = Path(__file__).parent / "narration"
AUDIO_DIR = NARRATION_DIR / "audio"
INDEX_PATH = NARRATION_DIR / "index.json"
PRONUNCIATIONS_PATH = NARRATION_DIR / "pronunciations.yaml"

TTS_URL = "https://api.x.ai/v1/tts"
STT_URL = "https://api.x.ai/v1/stt"
API_KEY_ENV = "XAI_API_KEY"

DEFAULT_VOICE = "ara"
DEFAULT_SPEED = 1.0

# The API is asked for lossless WAV so the samples are exact, then transcoded
# to Opus for the committed cache — ~32 kbps mono is transparent for speech and
# keeps the repository from carrying tens of megabytes of audio.
SYNTHESIS_SAMPLE_RATE = 24000
CACHE_BITRATE = "32k"

REQUEST_TIMEOUT = 180.0
MAX_ATTEMPTS = 4
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class NarrationError(RuntimeError):
    """Raised when narration audio cannot be produced."""


@dataclass(frozen=True)
class Clip:
    """One synthesized narration beat."""

    key: str
    sha: str
    text: str
    caption: str
    duration: float
    path: Path


def _log(message: str) -> None:
    print(f"[narration] {message}", file=sys.stderr)


def load_pronunciations() -> dict[str, str]:
    """Load the shared pronunciation map passed to the API as ``replace``."""
    if not PRONUNCIATIONS_PATH.exists():
        return {}
    data = yaml.safe_load(PRONUNCIATIONS_PATH.read_text()) or {}
    return {str(k): str(v) for k, v in (data.get("replace") or {}).items()}


# Inline speech tags ("[pause]") and wrapping tags ("<whisper>…</whisper>")
# are directions for the synthesizer, not words, so they never belong on screen.
_SPEECH_TAG_RE = re.compile(r"\[[a-z-]+\]|</?[a-z-]+>")


def caption_from(text: str) -> str:
    """Strip speech tags so a spoken line can double as its own caption."""
    return re.sub(r"\s{2,}", " ", _SPEECH_TAG_RE.sub("", text)).strip()


def script_path(name: str) -> Path:
    return NARRATION_DIR / f"{name}.yaml"


def load_script(name: str, _seen: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Load ``narration/<name>.yaml``.

    Returns a dict with ``voice``, ``speed`` and an ordered ``beats`` mapping of
    beat key to ``{"text": ..., "caption": ...}``.  YAML mappings preserve their
    document order, which is what lets the narrator prefetch the *next* beat.

    A script may ``include`` other scripts.  The marketplace walkthrough plays
    the same chapter functions as the standalone chapter clips, so it includes
    their narration rather than restating it — the same reason the Python
    shares the step functions instead of copying them.
    """
    path = script_path(name)
    if not path.exists():
        raise NarrationError(f"no narration script at {path}")
    if name in _seen:
        raise NarrationError(f"circular narration include involving '{name}'")

    raw = yaml.safe_load(path.read_text()) or {}

    beats: dict[str, dict[str, str]] = {}
    for included in raw.get("include") or []:
        beats.update(load_script(str(included), _seen | {name})["beats"])

    for beat_key, value in (raw.get("beats") or {}).items():
        if isinstance(value, str):
            value = {"text": value}
        text = (value.get("text") or "").strip()
        if not text:
            raise NarrationError(f"{path}: beat '{beat_key}' has no text")
        caption = (value.get("caption") or "").strip() or caption_from(text)
        beats[str(beat_key)] = {"text": text, "caption": caption}

    if not beats:
        raise NarrationError(f"{path}: no beats defined")

    return {
        "voice": str(raw.get("voice") or DEFAULT_VOICE),
        "speed": float(raw.get("speed") or DEFAULT_SPEED),
        "beats": beats,
    }


def _api_key() -> str:
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise NarrationError(f"{API_KEY_ENV} is not set")
    return api_key


def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = DEFAULT_SPEED,
    replace: dict[str, str] | None = None,
) -> tuple[bytes, float]:
    """Speak ``text`` and return ``(wav_bytes, duration_seconds)``.

    Uncached — the caching layer lives in :class:`Narrator`, so probes and
    auditions can call this without polluting the committed audio cache.
    """
    payload: dict[str, Any] = {
        "text": text,
        "voice_id": voice,
        "language": "en",
        "speed": speed,
        "with_timestamps": True,
        "output_format": {"codec": "wav", "sample_rate": SYNTHESIS_SAMPLE_RATE},
    }
    if replace:
        payload["replace"] = replace

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(
                TTS_URL,
                json=payload,
                headers={"Authorization": f"Bearer {_api_key()}"},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            if response.status_code == 200:
                body = response.json()
                duration = float(body["duration"])
                if duration <= 0:
                    raise NarrationError(f"API returned a zero-length clip for: {text!r}")
                return base64.b64decode(body["audio"]), duration
            if response.status_code not in RETRY_STATUS:
                raise NarrationError(f"TTS request failed ({response.status_code}): {response.text[:300]}")
            last_error = NarrationError(f"TTS request failed ({response.status_code})")

        if attempt < MAX_ATTEMPTS:
            backoff = 2.0**attempt
            _log(f"retrying in {backoff:.0f}s after {last_error}")
            threading.Event().wait(backoff)

    raise NarrationError(f"TTS request failed after {MAX_ATTEMPTS} attempts: {last_error}")


def transcribe(audio: bytes, filename: str = "probe.wav") -> str:
    """Send audio to the speech-to-text endpoint and return what was heard.

    This is what makes pronunciation checkable rather than guessable: the
    synthesizer speaks a term, and the transcript reports the sounds it
    actually produced.
    """
    response = httpx.post(
        STT_URL,
        headers={"Authorization": f"Bearer {_api_key()}"},
        files={"file": (filename, audio, "audio/wav")},
        data={"language": "en"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise NarrationError(f"STT request failed ({response.status_code}): {response.text[:300]}")
    return str(response.json()["text"]).strip()


class _Index:
    """The on-disk manifest of synthesized clips, keyed by content hash."""

    def __init__(self, path: Path = INDEX_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def get(self, sha: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._data.get(sha)
        if entry is None:
            return None
        # A stale index entry whose audio was deleted must re-synthesize rather
        # than pace the recording against a file that is not there.
        if not (AUDIO_DIR / entry["file"]).exists():
            return None
        return entry

    def put(self, sha: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._data[sha] = entry
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(dict(sorted(self._data.items())), indent=2) + "\n")


class Narrator:
    """Synthesizes and caches the narration beats for one screencast."""

    def __init__(
        self,
        beats: dict[str, dict[str, str]],
        voice: str = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        replace: dict[str, str] | None = None,
    ) -> None:
        self._beats = beats
        self._order = list(beats)
        self._voice = voice
        self._speed = speed
        self._replace = replace if replace is not None else load_pronunciations()
        self._index = _Index()
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Thread] = {}
        self._results: dict[str, Clip | BaseException] = {}
        self.blocked_beats: list[str] = []

    @classmethod
    def for_recording(cls, name: str) -> "Narrator | None":
        """Build a narrator for ``name``, or ``None`` if it has no script yet."""
        if not script_path(name).exists():
            return None
        script = load_script(name)
        return cls(beats=script["beats"], voice=script["voice"], speed=script["speed"])

    @property
    def beat_keys(self) -> list[str]:
        return list(self._order)

    def next_key(self, key: str) -> str | None:
        index = self._order.index(key)
        return self._order[index + 1] if index + 1 < len(self._order) else None

    def _sha(self, text: str) -> str:
        payload = json.dumps(
            {
                "text": text,
                "voice": self._voice,
                "speed": self._speed,
                "replace": dict(sorted(self._replace.items())),
                "sample_rate": SYNTHESIS_SAMPLE_RATE,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def prefetch(self, key: str | None) -> None:
        """Start synthesizing ``key`` in the background, if not already done."""
        if key is None:
            return
        with self._lock:
            if key in self._pending or key in self._results:
                return
            thread = threading.Thread(target=self._run, args=(key,), daemon=True)
            self._pending[key] = thread
        thread.start()

    def get(self, key: str) -> Clip:
        """Return the clip for ``key``, waiting on an in-flight prefetch."""
        if key not in self._beats:
            known = ", ".join(self._order)
            raise NarrationError(f"unknown narration beat '{key}' (have: {known})")

        with self._lock:
            thread = self._pending.get(key)
            result = self._results.get(key)

        if result is None and thread is None:
            # Never prefetched — synthesize inline.  This blocks the recording,
            # so it is reported the same way a slow prefetch is.
            self.blocked_beats.append(key)
            self._run(key)
        elif result is None and thread is not None:
            if thread.is_alive():
                self.blocked_beats.append(key)
                _log(f"waiting on synthesis for '{key}' — the recording is paused")
            thread.join()

        with self._lock:
            outcome = self._results.get(key)
        if outcome is None:
            raise NarrationError(f"narration beat '{key}' produced no audio")
        if isinstance(outcome, BaseException):
            raise NarrationError(f"narration beat '{key}' failed: {outcome}") from outcome
        return outcome

    def _run(self, key: str) -> None:
        try:
            clip = self._synthesize(key)
            outcome: Clip | BaseException = clip
        except BaseException as exc:  # noqa: BLE001 - re-raised in get()
            outcome = exc
        with self._lock:
            self._results[key] = outcome
            self._pending.pop(key, None)

    def _synthesize(self, key: str) -> Clip:
        beat = self._beats[key]
        text = beat["text"]
        sha = self._sha(text)

        cached = self._index.get(sha)
        if cached is not None:
            return Clip(
                key=key,
                sha=sha,
                text=text,
                caption=beat["caption"],
                duration=float(cached["duration"]),
                path=AUDIO_DIR / cached["file"],
            )

        wav, duration = self._request(text)
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIO_DIR / f"{sha}.opus"
        _to_opus(wav, path)
        self._index.put(
            sha,
            {"file": path.name, "duration": duration, "voice": self._voice, "speed": self._speed, "text": text},
        )
        _log(f"synthesized '{key}' ({duration:.2f}s) -> {path.name}")
        return Clip(key=key, sha=sha, text=text, caption=beat["caption"], duration=duration, path=path)

    def _request(self, text: str) -> tuple[bytes, float]:
        if not os.environ.get(API_KEY_ENV):
            raise NarrationError(
                f"{API_KEY_ENV} is not set and this line is not in the narration cache. "
                "Export the key to synthesize it, or restore screencasts/narration/audio/."
            )
        return synthesize(text, voice=self._voice, speed=self._speed, replace=self._replace)


def _to_opus(wav: bytes, destination: Path) -> None:
    """Transcode WAV bytes to a mono Opus file for the committed cache."""
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "wav", "-i", "pipe:0",
            "-ac", "1", "-c:a", "libopus", "-b:a", CACHE_BITRATE,
            str(destination),
        ],
        input=wav,
        capture_output=True,
    )  # fmt: skip
    if result.returncode != 0:
        raise NarrationError(f"ffmpeg could not encode narration audio: {result.stderr.decode()[:300]}")


def warm(name: str) -> list[Clip]:
    """Synthesize every beat of a screencast without recording it."""
    narrator = Narrator.for_recording(name)
    if narrator is None:
        raise NarrationError(f"no narration script for '{name}' (expected {script_path(name)})")

    clips = [narrator.get(key) for key in narrator.beat_keys]
    total = sum(clip.duration for clip in clips)
    _log(f"{name}: {len(clips)} beats, {total:.1f}s of narration")
    for clip in clips:
        _log(f"  {clip.duration:6.2f}s  {clip.key}: {clip.text}")
    return clips


# Probes are spoken inside a carrier sentence: an acronym read in isolation
# gets a different, more careful delivery than one buried mid-sentence, and
# mid-sentence is how it will actually be heard.
_PROBE_CARRIER = "The report mentions {term} twice."

# Sounds that mean a respelling leaked through as literal words.
_LEAKED_TOKENS = frozenset({"dash", "hyphen", "slash", "underscore"})


def _probe(term: str, replace: dict[str, str] | None, voice: str) -> tuple[str, float]:
    """Speak ``term`` in a carrier sentence; return what was heard and how long it took.

    Duration matters because the transcript alone is ambiguous: speech-to-text
    normalises "ess dash bom" and "ess bom" to similar text, but the spoken
    separator makes the clip measurably longer.
    """
    carrier = _PROBE_CARRIER.format(term=term)
    wav, duration = synthesize(carrier, voice=voice, replace=replace)
    heard = transcribe(wav)
    # Return just the substituted span, not the carrier around it.
    before, _, rest = heard.partition("mentions")
    middle, _, _ = (rest or before).rpartition("twice")
    return (middle or heard).strip(" .,"), duration


def try_candidates(term: str, candidates: list[str], voice: str = DEFAULT_VOICE) -> None:
    """Probe several spellings of one term side by side, to pick by evidence.

    The baseline row is the bare term with no substitution — often already
    correct, in which case the term needs no map entry at all.
    """
    heard, duration = _probe(term, None, voice)
    print(f"{'candidate':<22} {'heard':<30} {'seconds':>8}")
    print("-" * 62)
    print(f"{'(bare, no mapping)':<22} {heard:<30} {duration:>8.2f}")
    for candidate in candidates:
        heard, duration = _probe(term, {term: candidate}, voice)
        print(f"{candidate:<22} {heard:<30} {duration:>8.2f}")


def verify(voice: str = DEFAULT_VOICE) -> int:
    """Speak every mapped term and transcribe it back, bare and mapped.

    Prints what the synthesizer actually says so a pronunciation can be judged
    from evidence.  Returns the number of terms whose mapped rendering leaked a
    literal "dash"/"slash" — the failure mode that shipped in the first cut.
    """
    replace = load_pronunciations()
    if not replace:
        _log("no pronunciation map to verify")
        return 0

    problems = 0
    _log(f"probing {len(replace)} terms with voice '{voice}'")
    print(f"{'term':<12} {'bare':<26} {'secs':>5}  {'mapped':<26} {'secs':>5}  {'value'}")
    print("-" * 110)

    for term, value in replace.items():
        bare, bare_seconds = _probe(term, None, voice)
        mapped, mapped_seconds = _probe(term, {term: value}, voice)
        leaked = any(token in mapped.lower().split() for token in _LEAKED_TOKENS)
        if leaked:
            problems += 1
        flag = "  <-- leaked" if leaked else ""
        print(f"{term:<12} {bare:<26} {bare_seconds:>5.2f}  {mapped:<26} {mapped_seconds:>5.2f}  {value!r}{flag}")

    if problems:
        _log(f"{problems} mapped term(s) spoke a separator out loud — fix those values")
    return problems


_NARRATE_CALL_RE = re.compile(r'narrate\(page,\s*"([^"]+)"\)')

# Loops narrate by variable — ``narrate(page, beat)`` where beat came from a
# dict of index to key — so a key counts as used if it appears as any string
# literal in the script, not only inside a narrate() call.
_STRING_LITERAL_RE = re.compile(r'"([^"\n]+)"')


def lint() -> int:
    """Check every screencast's ``narrate()`` calls against its narration file.

    A mistyped beat key otherwise costs a full recording run to discover, and a
    beat defined but never spoken is copy that silently never ships.  Returns
    the number of screencasts with a problem.
    """
    screencasts_dir = Path(__file__).parent
    problems = 0

    for script in sorted(screencasts_dir.glob("*.py")):
        if script.name in {"conftest.py", "narrator.py", "mux_narration.py"}:
            continue

        source = script.read_text()
        called = _NARRATE_CALL_RE.findall(source)
        if not called:
            continue
        referenced = set(_STRING_LITERAL_RE.findall(source))

        # Parametrized recordings read narration/<stem>_<param-id>.yaml.
        scripts = sorted(NARRATION_DIR.glob(f"{script.stem}.yaml")) or sorted(
            NARRATION_DIR.glob(f"{script.stem}_*.yaml")
        )
        if not scripts:
            print(f"{script.name}: {len(called)} narrate() calls but no narration file")
            problems += 1
            continue

        # A parametrized recording renders one clip per param, each speaking
        # only its own subset of the script's beats, so "missing" is only
        # meaningful when a single narration file covers the whole script.
        parametrized = len(scripts) > 1

        for path in scripts:
            defined = set(load_script(path.stem)["beats"])
            missing = [] if parametrized else [key for key in called if key not in defined]
            # Only the file's *own* beats can be orphaned by this script —
            # included beats belong to whichever script speaks them.
            own = set((yaml.safe_load(path.read_text()) or {}).get("beats") or {})
            unused = [key for key in own if key not in referenced]
            if missing or unused:
                problems += 1
                detail = []
                if missing:
                    detail.append(f"missing from yaml: {', '.join(missing)}")
                if unused:
                    detail.append(f"never spoken: {', '.join(unused)}")
                print(f"{path.name}: {'; '.join(detail)}")
            else:
                print(f"{path.name}: ok ({len(called)} beats)")

    print(f"\n{problems} problem(s)")
    return problems


def proof(name: str) -> int:
    """Transcribe every synthesized line of a screencast and show what was said.

    Probing a term in isolation is not enough — "essbomify" passed a one-word
    probe and was then spelled out letter by letter inside a real sentence.
    This reads back the actual delivered audio, which is the only check that
    reflects what a viewer hears.  Returns the number of suspect lines.
    """
    narrator = Narrator.for_recording(name)
    if narrator is None:
        raise NarrationError(f"no narration script for '{name}'")

    suspect = 0
    for key in narrator.beat_keys:
        clip = narrator.get(key)
        heard = transcribe(clip.path.read_bytes(), filename=clip.path.name)

        # A run of single letters means something was spelled out.  That is
        # correct for API or URL and wrong for SBOM, so this is a prompt to
        # look rather than a verdict.
        spelled = re.search(r"\b(?:[a-z] ){2,}[a-z]\b", heard.lower())
        leaked = any(token in heard.lower().split() for token in _LEAKED_TOKENS)
        flag = "  <-- SEPARATOR SPOKEN" if leaked else ("  <-- spelled out, check" if spelled else "")
        if flag:
            suspect += 1

        print(f"\n{key} ({clip.duration:.2f}s){flag}")
        print(f"  wrote: {clip.text}")
        print(f"  heard: {heard}")

    if suspect:
        _log(f"{suspect} line(s) worth a listen — a spelled-out acronym may be right or wrong")
    return suspect


def warm_all() -> None:
    """Synthesize every narration script, so no recording waits on the API.

    Worth running once after editing copy: a recording with a cold cache still
    works, but the first use of each line blocks the run while it synthesizes.
    """
    names = sorted(p.stem for p in NARRATION_DIR.glob("*.yaml") if p.stem != "pronunciations")
    total = 0.0
    for name in names:
        clips = warm(name)
        total += sum(clip.duration for clip in clips)
    _log(f"{len(names)} scripts, {total / 60:.1f} minutes of narration cached")


def prune(dry_run: bool = False) -> int:
    """Delete cached audio no current narration script refers to.

    Every edit to a line — or to the pronunciation map — re-keys that clip, so
    the cache accumulates the audio of superseded copy. Since it is committed,
    prune before opening a pull request. Returns the number of files removed.
    """
    live: set[str] = set()
    for path in sorted(NARRATION_DIR.glob("*.yaml")):
        if path.stem == "pronunciations":
            continue
        script = load_script(path.stem)
        narrator = Narrator(beats=script["beats"], voice=script["voice"], speed=script["speed"])
        live.update(narrator._sha(beat["text"]) for beat in script["beats"].values())

    removed = 0
    freed = 0
    for clip in sorted(AUDIO_DIR.glob("*.opus")):
        if clip.stem in live:
            continue
        freed += clip.stat().st_size
        removed += 1
        if not dry_run:
            clip.unlink()

    verb = "would remove" if dry_run else "removed"
    _log(f"{verb} {removed} orphaned clip(s), {freed / 1024:.0f} KB; {len(live)} still in use")

    if not dry_run and removed:
        index = _Index()
        index._data = {sha: entry for sha, entry in index._data.items() if sha in live}
        INDEX_PATH.write_text(json.dumps(dict(sorted(index._data.items())), indent=2) + "\n")

    return removed


# Every built-in voice, so a choice is made by ear rather than by name.
AUDITION_VOICES = [
    "ara", "eve", "leo", "rex", "sal", "carina", "zagan", "helix", "orion",
    "luna", "iris", "altair", "zenith", "perseus", "helios", "lux", "kepler",
    "rigel", "cosmo", "celeste", "ursa", "sirius", "lumen", "castor", "naksh",
    "atlas",
]  # fmt: skip


def audition(text: str, voices: list[str] | None = None) -> None:
    """Render one line across the voices so a voice can be picked by ear.

    Auditions are written outside the content-addressed cache (and the
    directory is git-ignored), so trying voices never pollutes the committed
    narration audio.
    """
    out_dir = NARRATION_DIR / "audition"
    out_dir.mkdir(parents=True, exist_ok=True)
    replace = load_pronunciations()

    for voice in voices or AUDITION_VOICES:
        try:
            wav, duration = synthesize(text, voice=voice, replace=replace)
        except NarrationError as exc:
            _log(f"{voice}: unavailable ({exc})")
            continue
        destination = out_dir / f"{voice}.opus"
        _to_opus(wav, destination)
        _log(f"{voice}: {duration:.2f}s -> {destination.name}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: narrator.py warm <screencast> | audition <line> | verify", file=sys.stderr)
        return 2

    command, *rest = argv[1:]
    try:
        if command == "warm":
            if not rest:
                print("usage: narrator.py warm <screencast>", file=sys.stderr)
                return 2
            warm(rest[0])
        elif command == "warm-all":
            warm_all()
        elif command == "prune":
            prune(dry_run="--dry-run" in rest)
        elif command == "audition":
            if not rest:
                print("usage: narrator.py audition <line>", file=sys.stderr)
                return 2
            audition(" ".join(rest))
        elif command == "lint":
            return 1 if lint() else 0
        elif command == "proof":
            if not rest:
                print("usage: narrator.py proof <screencast>", file=sys.stderr)
                return 2
            return 1 if proof(rest[0]) else 0
        elif command == "verify":
            return 1 if verify(rest[0] if rest else DEFAULT_VOICE) else 0
        elif command == "try":
            if len(rest) < 2:
                print('usage: narrator.py try <term> "<candidate>" ...', file=sys.stderr)
                return 2
            try_candidates(rest[0], rest[1:])
        else:
            print(f"unknown command '{command}'", file=sys.stderr)
            return 2
    except NarrationError as exc:
        print(f"[narration] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
