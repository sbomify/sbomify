"""
Shared utilities for Dramatiq tasks.
"""

from __future__ import annotations

import logging
from typing import Any

import sentry_sdk

logger = logging.getLogger(__name__)


def record_task_breadcrumb(
    task_name: str, message: str, level: str = "info", data: dict[str, Any] | None = None
) -> None:
    """Add a Sentry breadcrumb for task execution when Sentry is configured."""
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


def format_task_error(task_name: str, sbom_id: str, error_msg: str) -> dict[str, Any]:
    """
    Format a standardized error response for SBOM processing tasks.

    Args:
        task_name: Name of the task that failed
        sbom_id: SBOM ID being processed
        error_msg: Error message

    Returns:
        Standardized error response dictionary
    """
    logger.error(
        f"task_error task={task_name} sbom_id={sbom_id} error={error_msg}",
        extra={"context": {"task": task_name, "sbom_id": sbom_id, "error": error_msg}},
    )
    return {"error": error_msg, "status": "failed", "sbom_id": sbom_id, "task": task_name}
