"""The error body: a code on every error, and a code that matches the status.

Two failures used to be possible and both were invisible to the caller. An
endpoint could return ``detail`` with no ``error_code``, leaving a client to
match on prose, and an endpoint could pair a code with a status that
contradicts it, which is how thirty six unhandled exceptions came back as 400
with the message "Internal server error".

The first is fixed in one place, by ``UTCZRenderer``. The second cannot be
fixed in one place, so it is gated here instead.
"""

from __future__ import annotations

import ast
import collections
import json
import pathlib
from functools import lru_cache

import pytest
from django.http import HttpRequest

from sbomify.apis import UTCZRenderer
from sbomify.apps.core.schemas import DEFAULT_ERROR_CODE_BY_STATUS, ErrorCode

APPS_DIR = pathlib.Path(__file__).resolve().parents[2]

# The codes each status may carry. A pair outside this map is either a wrong
# status or a wrong code, and the test says which pair to look at.
ALLOWED: dict[int, set[str]] = {
    400: {
        "BAD_REQUEST",
        "VALIDATION_ERROR",
        "INVALID_DATA",
        "DUPLICATE_NAME",
        "INVALID_BILLING_PLAN",
        # Business rules, not permissions. The request is well formed and the
        # caller is allowed here; this particular release just cannot be
        # changed. 409 would also read fine, so these are left alone.
        "RELEASE_MODIFICATION_NOT_ALLOWED",
        "RELEASE_DELETION_NOT_ALLOWED",
    },
    401: {"UNAUTHORIZED"},
    403: {
        "FORBIDDEN",
        "NO_CURRENT_TEAM",
        "TEAM_MISMATCH",
        "BILLING_LIMIT_EXCEEDED",
        "NO_BILLING_PLAN",
        "RELEASE_MODIFICATION_NOT_ALLOWED",
        "RELEASE_DELETION_NOT_ALLOWED",
    },
    404: {
        "NOT_FOUND",
        "TEAM_NOT_FOUND",
        "ITEM_NOT_FOUND",
        "PRODUCT_NOT_FOUND",
        "COMPONENT_NOT_FOUND",
        "RELEASE_NOT_FOUND",
        "COMPONENT_RELEASE_NOT_FOUND",
    },
    409: {"CONFLICT", "DUPLICATE_NAME", "DUPLICATE_ARTIFACT"},
    429: {"TOO_MANY_REQUESTS"},
    500: {"INTERNAL_ERROR", "UNKNOWN_ERROR"},
    503: {"SERVICE_UNAVAILABLE"},
}

# Pairs that contradict the map and stay anyway, because every way of fixing
# them is a break a client can see. Each needs a decision, not a patch, and
# the count is pinned so the shape cannot spread quietly.
#
#   403 + UNAUTHORIZED     anonymous caller on a private item. 401 is the
#                          correct status, and moving it is a contract change.
#                          Renaming the code is equally a contract change,
#                          because clients branch on the string.
#   403 + *_NOT_FOUND      answers a cross-workspace read as "not found" while
#                          the status admits the row exists. Hiding existence
#                          means 404; being honest means FORBIDDEN. The pair
#                          does neither.
#   400 + NOT_FOUND        the NDA-document branches. VALIDATION_ERROR reads
#                          better, but a v1 response is a contract down to its
#                          strings and codes, so the recode waits for v2.
TOLERATED: dict[tuple[int, str], int] = {
    (403, "UNAUTHORIZED"): 19,
    (403, "TEAM_NOT_FOUND"): 2,
    (403, "PRODUCT_NOT_FOUND"): 1,
    (400, "NOT_FOUND"): 2,
}


@lru_cache(maxsize=1)
def _literal_status_code_pairs() -> dict[tuple[int, str], list[str]]:
    """Every ``return <status>, {..., "error_code": ErrorCode.X}`` in the API layer.

    Codes built at runtime are skipped: ``_check_billing_limits`` hands back a
    code its caller cannot see, and both of its call sites are 403.

    Cached: three tests ask for this, and each call walks the AST of every
    api.py in the project. Callers must treat the result as read-only, since
    they all share it.
    """
    found: dict[tuple[int, str], list[str]] = collections.defaultdict(list)
    for path in sorted(APPS_DIR.rglob("api*.py")):
        if path.name not in ("apis.py", "api.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.Tuple)
                and len(node.value.elts) == 2
                and isinstance(node.value.elts[0], ast.Constant)
                and isinstance(node.value.elts[0].value, int)
                and isinstance(node.value.elts[1], ast.Dict)
            ):
                continue
            status = node.value.elts[0].value
            body = node.value.elts[1]
            for key, value in zip(body.keys, body.values):
                if isinstance(key, ast.Constant) and key.value == "error_code" and isinstance(value, ast.Attribute):
                    found[(status, value.attr)].append(f"{path.relative_to(APPS_DIR)}:{node.lineno}")
    return found


class TestStatusMatchesCode:
    def test_every_code_suits_its_status(self):
        offenders = []
        for (status, code), sites in sorted(_literal_status_code_pairs().items()):
            if (status, code) in TOLERATED or code in ALLOWED.get(status, set()):
                continue
            offenders.append(
                f"{status} + {code} at {sites[0]}" + (f" (+{len(sites) - 1} more)" if len(sites) > 1 else "")
            )

        assert not offenders, "error_code contradicts the HTTP status:\n  " + "\n  ".join(offenders)

    def test_the_tolerated_pairs_have_not_spread(self):
        """Each one is an open decision. New call sites should not join them."""
        found = _literal_status_code_pairs()
        for pair, expected in TOLERATED.items():
            actual = len(found.get(pair, []))
            assert actual <= expected, (
                f"{pair[0]} + {pair[1]} grew from {expected} to {actual} sites. "
                "Decide the status rather than adding another."
            )

    def test_no_unhandled_exception_answers_with_a_4xx(self):
        """An INTERNAL_ERROR body under a 4xx tells the caller their request was wrong."""
        misplaced = {
            (status, code): sites
            for (status, code), sites in _literal_status_code_pairs().items()
            if code == "INTERNAL_ERROR" and status < 500
        }
        assert not misplaced, f"INTERNAL_ERROR returned with a client-error status: {misplaced}"

    def test_every_allowed_code_exists(self):
        known = {member.value for member in ErrorCode}
        for status, codes in ALLOWED.items():
            unknown = codes - known
            assert not unknown, f"ALLOWED[{status}] names codes that are not in ErrorCode: {unknown}"


@lru_cache(maxsize=1)
def _undeclared_returned_statuses() -> list[str]:
    """Literal ``return <status>, {...}`` whose decorator does not declare it.

    ninja raises ``ConfigError: Schema for status N is not set in response``
    for an undeclared status, which reaches the caller as an unstructured 500.
    The status/code gate above cannot see this, because it reads the returns
    and never the decorator. Three views shipped that way.
    """
    offenders: list[str] = []
    for path in sorted(APPS_DIR.rglob("api*.py")):
        if path.name not in ("apis.py", "api.py"):
            continue
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            declared: set[int] | None = None
            for deco in fn.decorator_list:
                if isinstance(deco, ast.Call):
                    for kw in deco.keywords:
                        if kw.arg == "response" and isinstance(kw.value, ast.Dict):
                            declared = {
                                k.value
                                for k in kw.value.keys
                                if isinstance(k, ast.Constant) and isinstance(k.value, int)
                            }
            if declared is None:
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Tuple)
                    and len(node.value.elts) == 2
                    and isinstance(node.value.elts[0], ast.Constant)
                    and isinstance(node.value.elts[0].value, int)
                    and node.value.elts[0].value not in declared
                ):
                    offenders.append(
                        f"{path.relative_to(APPS_DIR)}:{node.lineno} returns "
                        f"{node.value.elts[0].value}, declared {sorted(declared)}"
                    )
    return offenders


class TestEveryReturnedStatusIsDeclared:
    def test_no_view_returns_a_status_its_decorator_does_not_declare(self):
        offenders = _undeclared_returned_statuses()
        assert not offenders, "undeclared statuses (ninja turns these into bare 500s):\n  " + "\n  ".join(offenders)


class TestRendererFillsTheGap:
    """The view keeps the last word; the renderer only covers silence."""

    @staticmethod
    def _render(status: int, payload: dict) -> dict:
        # A real request, because ninja's own signature says HttpRequest and
        # the renderer should not have to widen its type to suit the test.
        return json.loads(UTCZRenderer().render(HttpRequest(), payload, response_status=status))

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(400, "BAD_REQUEST"), (401, "UNAUTHORIZED"), (403, "FORBIDDEN"), (404, "NOT_FOUND"), (409, "CONFLICT")],
    )
    def test_a_bare_detail_gets_a_code(self, status, expected):
        assert self._render(status, {"detail": "x"})["error_code"] == expected

    def test_a_null_code_is_filled(self):
        """What a body serialised through ErrorResponse looks like when the view set nothing."""
        assert self._render(404, {"detail": "x", "error_code": None})["error_code"] == "NOT_FOUND"

    def test_an_explicit_code_survives(self):
        body = self._render(403, {"detail": "x", "error_code": "NO_CURRENT_TEAM"})
        assert body["error_code"] == "NO_CURRENT_TEAM"

    def test_the_throttle_body_is_coded(self):
        """_on_throttled builds its body by hand and names no code."""
        assert self._render(429, {"detail": "Too many requests."})["error_code"] == "TOO_MANY_REQUESTS"

    def test_ninjas_own_validation_error_is_coded(self):
        """422 comes from the framework, so no view can code it."""
        body = self._render(422, {"detail": [{"loc": ["body", "name"], "msg": "field required"}]})
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_success_is_left_alone(self):
        assert "error_code" not in self._render(200, {"detail": "not an error"})

    def test_an_unmapped_status_is_left_alone(self):
        assert "error_code" not in self._render(418, {"detail": "teapot"})

    def test_the_payload_is_not_mutated(self):
        payload = {"detail": "x"}
        self._render(404, payload)
        assert payload == {"detail": "x"}

    def test_every_default_is_a_real_code(self):
        known = {member.value for member in ErrorCode}
        assert {code.value for code in DEFAULT_ERROR_CODE_BY_STATUS.values()} <= known
