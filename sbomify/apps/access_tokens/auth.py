"Authentication middleware and related code."

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, JsonResponse
from ninja.security import HttpBearer

from sbomify.apps.core.utils import get_client_ip

from .utils import get_user_and_token_record


class PersonalAccessTokenAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> Any | None:
        user, access_token_record = get_user_and_token_record(
            token, source_ip=get_client_ip(request), attempted_action=f"{request.method} {request.path}"
        )
        if user is None or access_token_record is None:
            return None

        setattr(request, "user", user)
        setattr(request, "access_token_record", access_token_record)
        setattr(request, "token_team", access_token_record.team)

        return user, token


# Applied via ninja's `decorate_view`, which wraps `Operation.run` outside ninja's
# exception handler — so we can't raise `ninja.errors.HttpError` here; the
# wrapper has to return an `HttpResponse` directly. `JsonResponse({"detail":
# "Unauthorized"}, status=401)` matches the shape ninja produces when its own
# router-level auth rejects a request.
def _reject_invalid_bearer(func: Callable[..., Any]) -> Callable[..., Any]:
    """Allow anonymous access, but reject a presented-but-invalid bearer token with 401."""

    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        scheme, _, raw_token = request.headers.get("Authorization", "").partition(" ")
        # RFC 7235: auth scheme is case-insensitive. Treat `bearer`, `BEARER`, etc.
        # as Bearer so that a bad-token request can't bypass the 401 by lowercasing.
        if scheme.casefold() == "bearer":
            token = raw_token.strip()
            if not token or not PersonalAccessTokenAuth().authenticate(request, token):
                return JsonResponse({"detail": "Unauthorized"}, status=401)
        return func(request, *args, **kwargs)

    return wrapper


# Two names are kept for call-site documentation of intent. Behaviour is identical:
# anonymous access is permitted, a bad bearer token returns 401.
optional_auth = _reject_invalid_bearer
optional_token_auth = _reject_invalid_bearer
