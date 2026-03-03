"Authentication middleware and related code."

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest
from ninja.security import HttpBearer, django_auth

from .utils import get_user_and_token_record


class PersonalAccessTokenAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> Any | None:
        user, access_token_record = get_user_and_token_record(token)
        if user is None or access_token_record is None:
            return None

        setattr(request, "user", user)
        setattr(request, "access_token_record", access_token_record)
        setattr(request, "token_team", access_token_record.team)

        return user, token


class OptionalAuthBase(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str | None = None) -> bool:
        # If there's a token, try Personal Access Token auth
        if token:
            auth_result = PersonalAccessTokenAuth().authenticate(request, token)
            if auth_result:
                return True

        # Try Django auth
        if django_auth.authenticate(request, None):
            return True

        # Always return True for optional auth
        return True


def optional_auth(func: Callable[..., Any]) -> Callable[..., Any]:
    auth_instance = OptionalAuthBase()

    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        auth_instance.authenticate(request, token)
        return func(request, *args, **kwargs)

    return wrapper


def optional_token_auth(func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            PersonalAccessTokenAuth().authenticate(request, token)
        return func(request, *args, **kwargs)

    return wrapper
