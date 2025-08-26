"""
Reusable service functions for teams/workspaces.

This module provides service functions that can be used by both views and API endpoints,
ensuring consistent security boundaries and data handling across the application.
"""

from typing import Any, Dict, Tuple

from django.contrib.auth.models import User
from django.http import HttpRequest

from .apis import get_teams_dashboard_data as _api_get_teams_dashboard_data


def get_teams_dashboard_data_for_user(
    user: User, page: int = 1, page_size: int = 15, search: str = ""
) -> Dict[str, Any]:
    """
    Get serializable teams dashboard data for a user with pagination and search.

    This function provides a reusable way to get teams data that can be used
    in both Django templates and API endpoints, ensuring consistent security
    boundaries and data format.

    Args:
        user: The Django user object
        page: Page number for pagination
        page_size: Number of items per page
        search: Search query for filtering teams

    Returns:
        Dictionary with 'items' (list of teams) and 'pagination' (metadata)
    """
    # Create a mock request object with the user to leverage the API function
    mock_request = HttpRequest()
    mock_request.user = user

    # Create mock query parameters
    from unittest.mock import Mock

    mock_request.GET = Mock()
    mock_request.GET.get = Mock(
        side_effect=lambda key, default: {"page": str(page), "page_size": str(page_size), "search": search}.get(
            key, default
        )
    )

    # Call the API function directly to ensure consistent security boundaries
    status_code, data = _api_get_teams_dashboard_data(mock_request, page=page, page_size=page_size, search=search)

    if status_code == 200:
        # Convert Pydantic models to dicts for template usage
        return {
            "items": [team.dict() if hasattr(team, "dict") else team for team in data.items],
            "pagination": data.pagination.dict() if hasattr(data.pagination, "dict") else data.pagination,
        }

    return {"items": [], "pagination": None}


def get_teams_dashboard_data_with_status(
    user: User, page: int = 1, page_size: int = 15, search: str = ""
) -> Tuple[bool, Dict[str, Any]]:
    """
    Get teams dashboard data with success status and pagination.

    This variant returns both success status and data, useful for views
    that need to handle error cases explicitly.

    Args:
        user: The Django user object
        page: Page number for pagination
        page_size: Number of items per page
        search: Search query for filtering teams

    Returns:
        Tuple of (success: bool, data: Dict with items and pagination)
    """
    # Create a mock request object with the user
    mock_request = HttpRequest()
    mock_request.user = user

    # Call the API function directly
    status_code, data = _api_get_teams_dashboard_data(mock_request, page=page, page_size=page_size, search=search)

    success = status_code == 200
    result_data = {"items": [], "pagination": None}

    if success:
        # Convert Pydantic models to dicts for template usage and add template-compatible fields
        pagination_dict = data.pagination.dict() if hasattr(data.pagination, "dict") else data.pagination

        # Add template-compatible pagination fields
        start_index = (
            (pagination_dict["page"] - 1) * pagination_dict["page_size"] + 1 if pagination_dict["total"] > 0 else 0
        )
        end_index = min(pagination_dict["page"] * pagination_dict["page_size"], pagination_dict["total"])
        page_range = list(range(1, pagination_dict["total_pages"] + 1))

        pagination_dict.update({"start_index": start_index, "end_index": end_index, "page_range": page_range})

        result_data = {
            "items": [team.dict() if hasattr(team, "dict") else team for team in data.items],
            "pagination": pagination_dict,
        }

    return success, result_data
