"""Assessment plugin SDK.

This module provides the base classes and data structures for implementing
assessment plugins in sbomify.
"""

from .base import AssessmentPlugin
from .enums import AssessmentCategory, RunReason, RunStatus
from .results import AssessmentResult, AssessmentSummary, Finding, PluginMetadata

__all__ = [
    "AssessmentCategory",
    "AssessmentPlugin",
    "AssessmentResult",
    "AssessmentSummary",
    "Finding",
    "PluginMetadata",
    "RunReason",
    "RunStatus",
]
