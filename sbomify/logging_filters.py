"""Logging filter helpers used by the Django LOGGING config.

Kept out of ``sbomify.settings`` so tests can import the filter without
loading the full settings module (which would bypass ``sbomify.test_settings``).
"""

from __future__ import annotations

import logging


def is_benign_shielded_future_error(record: logging.LogRecord) -> bool:
    # CancelledError comes from asgiref when clients disconnect mid-request;
    # ConnectionClosed (and its subclasses ConnectionClosedError/ConnectionClosedOK)
    # from websockets on keepalive ping timeout or normal client close.
    message = record.getMessage()
    return "exception in shielded future" in message and any(
        exc in message for exc in ("CancelledError", "ConnectionClosed")
    )
