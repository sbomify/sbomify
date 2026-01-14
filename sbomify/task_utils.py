"""
Shared utilities for Dramatiq tasks.

This module provides common decorators and utilities for SBOM processing tasks
to reduce duplication and ensure consistent error handling patterns.
"""

import logging
from functools import wraps
from typing import Any, Callable, Dict

import dramatiq
from django.db import DatabaseError, OperationalError, connection, transaction
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

logger = logging.getLogger(__name__)

try:  # Optional Sentry integration
    import sentry_sdk
except Exception:  # pragma: no cover - optional dependency
    sentry_sdk = None


def record_task_breadcrumb(
    task_name: str, message: str, level: str = "info", data: Dict[str, Any] | None = None
) -> None:
    """Add a Sentry breadcrumb for task execution when Sentry is configured."""
    if sentry_sdk is None:
        return
    try:
        sentry_sdk.add_breadcrumb(
            category="tasks",
            message=f"{task_name}: {message}",
            level=level,
            data=data or {},
        )
    except Exception:
        # Breadcrumbs should never break task execution
        return


def sbom_processing_task(
    queue_name: str = "sbom_processing",
    max_retries: int = 3,
    time_limit: int = 300000,
    store_results: bool = True,
):
    """
    Decorator for SBOM processing tasks with common retry and error handling patterns.

    This decorator provides:
    - Consistent Dramatiq actor configuration
    - Database error retry logic with exponential backoff
    - Transaction management with connection ensuring
    - Standardized error response format

    Args:
        queue_name: Dramatiq queue name (default: "sbom_processing")
        max_retries: Maximum retry attempts (default: 3)
        time_limit: Task timeout in milliseconds (default: 300000 = 5 minutes)
        store_results: Whether to store task results (default: True)
    """

    def decorator(func: Callable) -> Callable:
        # Apply Dramatiq decorators
        @dramatiq.actor(
            queue_name=queue_name,
            max_retries=max_retries,
            time_limit=time_limit,
            store_results=store_results,
        )
        @retry(
            retry=retry_if_exception_type((OperationalError, DatabaseError)),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            stop=stop_after_delay(60),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        @wraps(func)
        def wrapper(*args, **kwargs) -> Dict[str, Any]:
            # Ensure database connection
            with transaction.atomic():
                connection.ensure_connection()
                try:
                    record_task_breadcrumb(func.__name__, "start", data={"args_count": len(args)})
                    return func(*args, **kwargs)
                except Exception as e:
                    # Log the error with task context
                    task_name = func.__name__
                    logger.error(f"[TASK_{task_name}] Task failed with error: {e}", exc_info=True)
                    record_task_breadcrumb(task_name, "error", level="error", data={"error": str(e)})
                    # Re-raise to allow Dramatiq retry logic to handle it
                    raise

        return wrapper

    return decorator


def format_task_error(task_name: str, sbom_id: str, error_msg: str) -> Dict[str, Any]:
    """
    Format a standardized error response for SBOM processing tasks.

    Args:
        task_name: Name of the task that failed
        sbom_id: SBOM ID being processed
        error_msg: Error message

    Returns:
        Standardized error response dictionary
    """
    logger.error(f"[TASK_{task_name}] {error_msg}")
    return {"error": error_msg, "status": "failed", "sbom_id": sbom_id, "task": task_name}
