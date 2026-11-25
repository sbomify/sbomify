"""Opens an audit context per request, and records what nothing else did.

The model signals describe most changes precisely (``product.updated``, with
the fields that moved). Not every change is a tracked model, and a refused
request changes nothing at all, so a state-changing request (any method but
GET, HEAD and OPTIONS) that ends with nothing more specific recorded becomes
one ``request.<method>`` event carrying its route and status. Coverage does not
depend on every new endpoint remembering to log.

Request bodies are never recorded. The only form values kept are the
``*_action`` discriminators the settings forms post, which are fixed words that
say which form was submitted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse

from .context import audit_context, from_request
from .models import Outcome
from .recorder import Target, record

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Paths whose state changes are recorded by something more specific, or are
# not a person's action in a workspace.
SKIPPED_PREFIXES: tuple[str, ...] = (
    "/accounts/",  # sign-in and sign-out, recorded from the auth signals
    "/static/",
    "/mcp",  # served outside Django; the tool wrapper records each call
    "/api/v1/internal/",
)

# Route kwargs that name the workspace a request acts in.
WORKSPACE_KWARGS: tuple[str, ...] = ("workspace_key", "team_key")


def _workspace_id(request: HttpRequest) -> int | None:
    from sbomify.apps.core.utils import token_to_number

    match = getattr(request, "resolver_match", None)
    kwargs = match.kwargs if match is not None else {}
    for name in WORKSPACE_KWARGS:
        if key := kwargs.get(name):
            try:
                return int(token_to_number(str(key)))
            except (TypeError, ValueError):
                return None

    token_team = getattr(request, "token_team", None)
    if token_team is not None:
        return int(token_team.pk)

    session = getattr(request, "session", None)
    current_workspace = session.get("current_workspace") if session is not None else None
    if isinstance(current_workspace, dict) and current_workspace.get("id"):
        try:
            return int(current_workspace["id"])
        except (TypeError, ValueError):
            return None
    return None


def _outcome(status: int) -> str:
    if status in (401, 403):
        return Outcome.DENIED
    if status >= 400:
        return Outcome.FAILURE
    return Outcome.SUCCESS


def _form_actions(request: HttpRequest) -> dict[str, str]:
    if request.content_type not in ("application/x-www-form-urlencoded", "multipart/form-data"):
        return {}
    try:
        post = request.POST
    except Exception:
        return {}
    return {key: str(post.get(key, ""))[:64] for key in post if key.endswith("_action") or key == "_method"}


class AuditMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with audit_context(from_request(request)) as ctx:
            response = self.get_response(request)
            if (
                request.method not in SAFE_METHODS
                and ctx.recorded == 0
                and not request.path.startswith(SKIPPED_PREFIXES)
            ):
                self._record_request(request, response)
        return response

    def _record_request(self, request: HttpRequest, response: HttpResponse) -> None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        workspace_id = _workspace_id(request)
        if workspace_id is None:
            return
        match = getattr(request, "resolver_match", None)
        metadata: dict[str, Any] = {"route": match.view_name if match is not None else ""}
        if form_actions := _form_actions(request):
            metadata["form"] = form_actions
        record(
            f"request.{(request.method or '').lower()}",
            workspace=workspace_id,
            target=Target("route", "", (match.view_name if match is not None else request.path)[:255]),
            outcome=_outcome(response.status_code),
            status_code=response.status_code,
            metadata=metadata,
        )
