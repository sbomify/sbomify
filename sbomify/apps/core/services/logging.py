from __future__ import annotations

import logging
from typing import Any


def build_log_context(**context: Any) -> dict[str, Any]:
    return {key: value for key, value in context.items() if value is not None}


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **context: Any,
) -> None:
    safe_context = build_log_context(**context)
    suffix = " ".join(f"{key}={value}" for key, value in safe_context.items())
    message = f"{event} {suffix}".strip()
    logger.log(level, message, extra={"context": safe_context})


def log_info(logger: logging.Logger, event: str, **context: Any) -> None:
    log_event(logger, logging.INFO, event, **context)


def log_warning(logger: logging.Logger, event: str, **context: Any) -> None:
    log_event(logger, logging.WARNING, event, **context)


def log_error(logger: logging.Logger, event: str, **context: Any) -> None:
    log_event(logger, logging.ERROR, event, **context)
