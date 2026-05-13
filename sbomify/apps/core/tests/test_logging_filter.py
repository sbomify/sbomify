"""Tests for the asyncio shielded-future log filter."""

import logging

import pytest

from sbomify.logging_filters import is_benign_shielded_future_error


def _make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg=message,
        args=None,
        exc_info=None,
    )


@pytest.mark.parametrize(
    "message,expected_benign",
    [
        ("CancelledError exception in shielded future", True),
        ("ConnectionClosedError: sent 1011 (internal error) exception in shielded future", True),
        ("ConnectionClosedOK exception in shielded future", True),
        ("ValueError exception in shielded future", False),
        ("CancelledError raised in handler", False),
        ("ConnectionClosedError while reading", False),
        ("unrelated log line", False),
    ],
)
def test_is_benign_shielded_future_error(message: str, expected_benign: bool) -> None:
    record = _make_record(message)
    assert is_benign_shielded_future_error(record) is expected_benign
