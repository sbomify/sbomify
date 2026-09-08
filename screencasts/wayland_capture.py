"""Record the screen through GNOME's own recorder, on Wayland.

Playwright's ``record_video`` goes through a CDP screencast, and that screencast
throttles frame *delivery*: measured at ~6 distinct frames a second sustained,
with duplicates padding the rest, on both a GPU-less VM and a machine with a
working GPU. Faster drawing does not help, because drawing was never the limit.

GNOME's shell recorder — the one behind Ctrl+Alt+Shift+R — reads the composited
output directly. Measured on the same machine and the same page: **19.4 distinct
frames a second, 205 of 206 frames unique.** Roughly three times the sustained
rate, and no duplicates.

Two things make this awkward enough to need its own module:

* **The recording is bound to the D-Bus connection that started it.** A
  ``busctl call`` returns immediately and takes the recording with it — the
  first attempt produced exactly one frame. So the caller has to stay connected
  for the whole take, which is why this runs as a subprocess that idles until
  it is asked to stop.
* **X11 capture is not an alternative here.** On a Wayland session
  ``ffmpeg -f x11grab`` returns black frames: Xwayland's root window does not
  hold the composited image.

Run directly as a helper (this is how ``conftest`` uses it)::

    python screencasts/wayland_capture.py <out.webm> <fps> <x> <y> <w> <h>

It records until it receives SIGTERM or SIGINT, then stops the screencast
cleanly and exits. Killing it with SIGKILL leaves GNOME recording, so always
terminate it politely.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

# Where GNOME publishes the recorder.
BUS_NAME = "org.gnome.Shell.Screencast"
BUS_PATH = "/org/gnome/Shell/Screencast"


# The session bus of the logged-in user. Over SSH there is no ambient
# DBUS_SESSION_BUS_ADDRESS, so it is derived from the uid unless one is set.
def session_bus_address() -> str:
    existing = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if existing:
        return existing
    return f"unix:path=/run/user/{os.getuid()}/bus"


def available() -> bool:
    """Is GNOME's recorder present and willing on this session?"""
    if not sys.platform.startswith("linux"):
        return False
    env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": session_bus_address()}
    probe = subprocess.run(
        ["busctl", "--user", "get-property", BUS_NAME, BUS_PATH, BUS_NAME, "ScreencastSupported"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )  # nosec B607 - busctl by name from PATH, fixed argv, shell=False
    return probe.returncode == 0 and "true" in probe.stdout


def _interpreter_with_gi() -> str:
    """An interpreter that can import PyGObject.

    ``sys.executable`` is the project's virtualenv, and PyGObject is a *system*
    package that is not in it — installing it there means building against the
    distro's glib headers, which is not worth doing for a helper this small. So
    prefer the interpreter the distro ships, and fall back to whatever is
    running us.

    Getting this wrong is silent from the outside: the helper exits with
    ModuleNotFoundError and the recording simply ends up with no file.
    """
    candidates = [os.environ.get("SCREENCAST_GI_PYTHON"), "/usr/bin/python3", sys.executable]
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        probe = subprocess.run(  # nosec B607 - fixed argv, shell=False
            [candidate, "-c", "import gi"], capture_output=True, check=False
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError(
        "no interpreter with PyGObject available for the Wayland capture helper; "
        "install python3-gi, or point SCREENCAST_GI_PYTHON at one that has it"
    )


def start(destination: Path, fps: int, area: tuple[int, int, int, int]) -> subprocess.Popen:
    """Begin recording ``area`` (logical pixels) into ``destination``.

    Returns the helper process. Call :func:`stop` on it; do not kill it.
    """
    x, y, width, height = area
    env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": session_bus_address()}
    return subprocess.Popen(  # nosec B607 - fixed argv, shell=False
        [
            _interpreter_with_gi(),
            str(Path(__file__).resolve()),
            str(destination),
            str(fps),
            str(x),
            str(y),
            str(width),
            str(height),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop(process: subprocess.Popen, timeout: float = 20.0) -> None:
    """Ask the helper to stop, and wait for GNOME to finish writing the file."""
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _record(destination: str, fps: int, x: int, y: int, width: int, height: int) -> int:
    import gi  # type: ignore[import-untyped]

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib  # type: ignore[import-untyped]

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, BUS_NAME, BUS_PATH, BUS_NAME, None)

    # A plain dict of Variants. Wrapping it in a Variant first makes the tuple
    # builder try to re-create it, and it raises KeyError(0).
    options = {
        "framerate": GLib.Variant("i", fps),
        # The recording draws its own cursor via click_indicator.js, and GNOME's
        # would sit on top of it.
        "draw-cursor": GLib.Variant("b", False),
    }
    args = GLib.Variant("(iiiisa{sv})", (x, y, width, height, destination, options))
    started, path = proxy.call_sync("ScreencastArea", args, Gio.DBusCallFlags.NONE, 10_000, None).unpack()
    if not started:
        print("could not start screencast", file=sys.stderr)
        return 1
    print(path, flush=True)

    loop = GLib.MainLoop()

    def finish(*_: object) -> bool:
        proxy.call_sync("StopScreencast", None, Gio.DBusCallFlags.NONE, 10_000, None)
        loop.quit()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, finish)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, finish)
    loop.run()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(_record(sys.argv[1], int(sys.argv[2]), *(int(v) for v in sys.argv[3:7])))
