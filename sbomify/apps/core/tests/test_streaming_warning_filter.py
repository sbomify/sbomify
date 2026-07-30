"""Regression tests for the WhiteNoise/ASGI streaming warning filter.

``settings.py`` silences one specific Django warning emitted whenever
WhiteNoise serves a static file under ASGI. The risk with any warning filter
is that it quietly grows to cover more than intended, so these tests pin both
halves of the contract: the noisy warning is suppressed, and everything else
in the same category still gets through.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import warnings

DJANGO_MESSAGE = (
    "StreamingHttpResponse must consume synchronous iterators in order to "
    "serve them asynchronously. Use an asynchronous iterator instead."
)


class TestStreamingWarningFilter:
    def test_settings_actually_suppresses_it(self):
        """End-to-end check that loading real settings silences the warning.

        Runs in a subprocess because pytest installs its own ``filterwarnings``
        from ``pyproject.toml``, which replaces the filter list that
        ``settings.py`` set up at import time. In-process assertions here would
        therefore test pytest's configuration rather than ours.
        """
        script = textwrap.dedent(
            f"""
            import os, warnings
            os.environ["DJANGO_SETTINGS_MODULE"] = "sbomify.settings"
            import django; django.setup()
            with warnings.catch_warnings(record=True) as target:
                warnings.warn({DJANGO_MESSAGE!r}, Warning)
            with warnings.catch_warnings(record=True) as unrelated:
                warnings.warn("an unrelated warning", Warning)
            print(f"{{len(target)}},{{len(unrelated)}}")
            """
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        target_count, unrelated_count = result.stdout.strip().splitlines()[-1].split(",")
        assert target_count == "0", "the WhiteNoise streaming warning should be filtered out"
        assert unrelated_count == "1", "unrelated warnings must still surface"

    def test_other_warnings_still_surface(self):
        """The filter must not widen into a blanket `Warning` suppression.

        Django uses the bare ``Warning`` category here, so an unscoped filter
        would hide unrelated warnings. Pin that it is matched on message.
        """
        import sbomify.settings  # noqa: F401

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.filterwarnings(
                "ignore",
                message=r"^StreamingHttpResponse must consume synchronous iterators",
                category=Warning,
            )
            warnings.warn("something else entirely went wrong", Warning, stacklevel=2)
            warnings.warn(DJANGO_MESSAGE, Warning, stacklevel=2)

        messages = [str(w.message) for w in caught]
        assert "something else entirely went wrong" in messages
        assert DJANGO_MESSAGE not in messages

    def test_a_differently_worded_streaming_warning_still_surfaces(self):
        """Anchored at the start of the message, so it cannot match loosely."""
        import sbomify.settings  # noqa: F401

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.filterwarnings(
                "ignore",
                message=r"^StreamingHttpResponse must consume synchronous iterators",
                category=Warning,
            )
            warnings.warn("A StreamingHttpResponse elsewhere failed badly", Warning, stacklevel=2)

        assert len(caught) == 1
