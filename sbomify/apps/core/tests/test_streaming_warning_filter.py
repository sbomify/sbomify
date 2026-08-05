"""Regression tests for the WhiteNoise/ASGI streaming warning filter.

``settings.py`` silences one specific Django warning emitted whenever
WhiteNoise serves a static file under ASGI. The risk with any warning filter
is that it quietly grows to cover more than intended, so these tests pin both
halves of the contract: the noisy warning is suppressed, and everything else
in the same category still gets through.

Every case runs in a subprocess. Not for isolation -- pytest's
``filterwarnings`` setting in ``pyproject.toml`` *replaces* the filter list,
so by the time a test body runs, the filter ``settings.py`` installed is gone:

    settings filter visible under pytest: False
    suppressed without re-declaring:      False

An in-process test could therefore only verify a filter it had declared
itself. Earlier versions of this file did exactly that, and would have passed
unchanged if ``settings.py`` had stopped installing the filter altogether.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

#: The message Django emits from ``StreamingHttpResponse.__aiter__`` when
#: WhiteNoise hands it a synchronous iterator under ASGI.
DJANGO_MESSAGE = (
    "StreamingHttpResponse must consume synchronous iterators in order to "
    "serve them asynchronously. Use an asynchronous iterator instead."
)

#: Django's warning for the reverse mistake: same category, nearly identical
#: wording, entirely different meaning. It must keep surfacing.
SIBLING_MESSAGE = (
    "StreamingHttpResponse must consume asynchronous iterators in order to "
    "serve them synchronously. Use a synchronous iterator instead."
)


def surfaces(message: str) -> bool:
    """Whether ``message`` still reaches the user once real settings load.

    Loads ``sbomify.settings`` for real and declares no filters of its own, so
    the answer reflects what we actually ship rather than what the test set up.
    """
    script = textwrap.dedent(
        f"""
        import os, warnings
        os.environ["DJANGO_SETTINGS_MODULE"] = "sbomify.settings"
        import django; django.setup()
        with warnings.catch_warnings(record=True) as caught:
            warnings.warn({message!r}, Warning)
        print(f"SURFACED={{len(caught)}}")
        """
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("SURFACED="))
    return int(line.removeprefix("SURFACED=")) > 0


class TestStreamingWarningFilter:
    def test_the_noisy_warning_is_suppressed(self):
        """The whole point of the filter."""
        assert not surfaces(DJANGO_MESSAGE)

    def test_unrelated_warnings_still_surface(self):
        """Django raises this under the bare ``Warning`` category, so a filter
        scoped by category alone would hide everything. It matches on message."""
        assert surfaces("an unrelated warning that must not be swallowed")

    def test_the_reverse_django_warning_still_surfaces(self):
        assert surfaces(SIBLING_MESSAGE)

    def test_a_message_merely_starting_with_it_still_surfaces(self):
        """The pattern is anchored at both ends, not just the start.

        Without the trailing anchor anything prefixed with Django's wording
        would be silenced too, which is wider than intended.
        """
        assert surfaces(f"{DJANGO_MESSAGE} And then something else went wrong.")

    def test_a_differently_worded_streaming_warning_still_surfaces(self):
        assert surfaces("A StreamingHttpResponse elsewhere failed badly")
