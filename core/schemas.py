from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Structured error codes for API responses"""

    # Authentication errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NO_CURRENT_TEAM = "NO_CURRENT_TEAM"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_NAME = "DUPLICATE_NAME"
    INVALID_DATA = "INVALID_DATA"

    # Billing errors
    BILLING_LIMIT_EXCEEDED = "BILLING_LIMIT_EXCEEDED"
    NO_BILLING_PLAN = "NO_BILLING_PLAN"
    INVALID_BILLING_PLAN = "INVALID_BILLING_PLAN"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"

    # General errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[ErrorCode] = None

    class Config:
        use_enum_values = True
