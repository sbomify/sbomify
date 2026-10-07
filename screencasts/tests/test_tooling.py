"""Checks for the screencast tooling: transcode, mux, capture, narration.

Not run by the main test suite, which skips ``screencasts/``. Run it inside the
tests container with ``uv run pytest screencasts/tests``.
"""

from __future__ import annotations

import re
import signal
import subprocess
from pathlib import Path

import backfill_timings
import httpx
import mux_narration
import narrator
import pytest
import transcode
import wayland_capture


def _char_times(spoken: str) -> list[tuple[str, float, float]]:
    """0.05 s a character, and 1.6 s of silence after every speech tag."""
    times, clock = [], 0.0
    for char in spoken:
        times.append((char, clock, clock + 0.05))
        clock += 0.05 + (1.6 if char == "]" else 0.0)
    return times


def test_a_custom_caption_is_cued_at_the_words_it_shares_with_the_voice(tmp_path: Path) -> None:
    """The caption leaves out a word the voice says, so caption positions and
    spoken positions part company; the second cue must still start after the pause."""
    spoken = "We start with the inventory of every component today. [long-pause] Then we look at what is vulnerable."
    caption = "We start with the inventory of every component. Then we look at what is vulnerable."
    times = _char_times(spoken)
    beat = mux_narration.Beat(key="k", offset_ms=0.0, duration=times[-1][2], sha="x", caption=caption, char_times=times)
    vtt = tmp_path / "out.vtt"

    mux_narration.write_vtt(vtt, [beat], 1.0)

    starts = re.findall(r"^(\d\d):(\d\d):(\d\d\.\d{3}) -->", vtt.read_text(), re.M)
    second = int(starts[1][1]) * 60 + float(starts[1][2])
    assert second == pytest.approx(times[spoken.index("Then")][1], abs=0.001)


def test_a_recording_made_again_is_converted_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcode, "OUTPUT_DIR", tmp_path)
    encodes: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(argv, 0, stdout=Path(argv[-1]).read_text())
        encodes.append(argv)
        Path(argv[-1]).write_text("vp9")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(transcode.subprocess, "run", fake_run)
    recording = tmp_path / "demo.webm"
    recording.write_text("vp8")

    transcode.transcode("demo")
    transcode.transcode("demo")
    assert len(encodes) == 1

    recording.write_text("vp8")
    transcode.transcode("demo")
    assert len(encodes) == 2
    assert recording.read_text() == "vp9"


class _Helper:
    """A capture helper that exits with ``exit_code``, or never when it is None."""

    def __init__(self, exit_code: int | None, *, exited_early: bool = False) -> None:
        self.exit_code = exit_code
        self.returncode: int | None = exit_code if exited_early else None
        self.signals: list[int] = []
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def wait(self, timeout: float | None = None) -> int:
        if self.exit_code is None:
            raise subprocess.TimeoutExpired("helper", timeout or 0)
        self.returncode = self.exit_code
        return self.exit_code

    def communicate(self) -> tuple[str, str]:
        return "", "could not stop screencast: Timeout was reached\n"

    def kill(self) -> None:
        self.killed = True


def test_a_capture_that_does_not_stop_fails_the_take_without_a_kill() -> None:
    """A SIGKILL leaves GNOME recording, so the helper is left to finish instead."""
    helper = _Helper(exit_code=None)

    with pytest.raises(RuntimeError, match="did not finish"):
        wayland_capture.stop(helper, timeout=0.01)

    assert helper.signals == [signal.SIGTERM]
    assert helper.killed is False


def test_a_failed_stop_call_fails_the_take() -> None:
    with pytest.raises(RuntimeError, match="Timeout was reached"):
        wayland_capture.stop(_Helper(exit_code=1))


def test_a_clean_stop_passes() -> None:
    wayland_capture.stop(_Helper(exit_code=0))


def test_a_helper_that_failed_before_the_stop_fails_the_take() -> None:
    """A failed start must not leave the caller to trust whatever file is there."""
    helper = _Helper(exit_code=1, exited_early=True)

    with pytest.raises(RuntimeError, match="Timeout was reached"):
        wayland_capture.stop(helper)

    assert helper.signals == []


def test_a_new_take_never_starts_beside_an_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale capture from an earlier take of the same name would pass for this one."""
    stale = tmp_path / "demo.capture.webm"
    stale.write_text("an earlier take")
    monkeypatch.setattr(wayland_capture, "_interpreter_with_gi", lambda: "python3")
    monkeypatch.setattr(wayland_capture.subprocess, "Popen", lambda *args, **kwargs: _Helper(exit_code=0))

    wayland_capture.start(stale, 30, (0, 0, 10, 10))

    assert not stale.exists()


def test_a_new_recording_inherits_no_scenes_and_no_open_beat(request: pytest.FixtureRequest) -> None:
    recording = next(
        plugin
        for plugin in request.config.pluginmanager.get_plugins()
        if str(getattr(plugin, "__file__", "")).endswith("screencasts/conftest.py")
    )
    state = recording._narration_state
    state["scenes"] = [{"offset_ms": 12.0, "url": "/earlier/recording/"}]
    state["open_beat"] = {"entry": {"duration": 1.0}, "started": 0.0}

    recording._reset_narration(None)

    assert state["scenes"] == []
    assert state["open_beat"] is None


@pytest.mark.parametrize("call", ["synthesize", "transcribe"])
def test_each_speech_request_sends_the_configured_key(call: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(narrator.API_KEY_ENV, "not-a-real-key")
    headers: dict[str, str] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        headers.update(kwargs["headers"])
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(narrator.httpx, "post", fake_post)

    with pytest.raises(narrator.NarrationError):
        narrator.synthesize("hello") if call == "synthesize" else narrator.transcribe(b"audio")

    assert headers["Authorization"] == "Bearer not-a-real-key"


def test_backfill_without_a_cache_says_so_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backfill_timings, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(backfill_timings.sys, "argv", ["backfill_timings.py"])

    backfill_timings.main()

    assert "no narration cache" in capsys.readouterr().out
