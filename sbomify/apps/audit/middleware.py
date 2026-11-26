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

    # A workspace-bound token names the workspace its holder is acting in.
    token_team = getattr(request, "token_team", None)
    if token_team is not None:
        return int(token_team.pk)

    # Nothing else is trusted to say. The session's current workspace is only
    # the one last switched to, not the one this request touched, so filing an
    # event under it would put activity on one tenant's resource into another
    # tenant's log. Requests like that are covered by the model events instead.
    return None


def _is_member(user: Any, workspace_id: int) -> bool:
    """Only someone in the workspace can put a request event in its log.

    Without this, anyone signed in could post to another workspace's URLs and
    fill its audit log with refusals carrying their own form values.
    """
    from sbomify.apps.teams.models import Member

    return Member.objects.filter(user=user, team_id=workspace_id).exists()


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
            # A failed request is always recorded: whatever it queued to log
            # was rolled back with it, so a non-zero count proves nothing.
            if (
                request.method not in SAFE_METHODS
                and (ctx.recorded == 0 or response.status_code >= 400)
                and not request.path.startswith(SKIPPED_PREFIXES)
            ):
                self._record_request(request, response)
        return response

    def _record_request(self, request: HttpRequest, response: HttpResponse) -> None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        workspace_id = _workspace_id(request)
        if workspace_id is None or not _is_member(user, workspace_id):
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
