from __future__ import annotations

import hashlib
import json
import typing
from datetime import timedelta
from time import time
from typing import Any
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Q
from django.utils import timezone
from jwt.exceptions import DecodeError, InvalidTokenError

from sbomify import logging

if typing.TYPE_CHECKING:
    from .models import AccessToken

log = logging.getLogger(__name__)

# Append-only forensic trail of PAT/OIDC authentication outcomes. Structured
# logging (not a table): retention is the log pipeline's job, and failure events
# are unbounded/attacker-driftable. last_used_at stays the queryable "last seen".
audit_log = logging.getLogger("audit.token_auth")  # -> "sbomify.audit.token_auth"


def _token_fingerprint(token: str) -> str:
    """Non-reversible short fingerprint, for attributing failures without the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def _emit_token_auth_event(
    outcome: str,
    *,
    token: str,
    reason: str | None = None,
    record: AccessToken | None = None,
    user_id: str | None = None,
    source_ip: str | None = None,
    attempted_action: str | None = None,
) -> None:
    """Emit one structured token-auth audit event. Never logs the raw token: every
    event carries a non-reversible fingerprint, and events with a resolved DB record
    (success, DB-row expiry) additionally carry the token id."""
    extra = {
        "event": "token_auth",
        "outcome": outcome,
        "reason": reason,
        "token_id": str(record.pk) if record is not None else None,
        "token_fingerprint": _token_fingerprint(token),
        "user_id": user_id,
        # Keep None (JSON null) for a team-less token rather than the string "None".
        "team_id": str(record.team_id) if record is not None and record.team_id is not None else None,
        "source_ip": source_ip,
        "attempted_action": attempted_action,
    }
    # The default console formatter renders only %(message)s and drops `extra`, so
    # serialize the fields into the message as JSON too — otherwise operators see no
    # detail in container logs. A structured handler can still consume `extra`.
    detail = json.dumps({k: v for k, v in extra.items() if k != "event"}, default=str)
    # Expected end-of-life (expired) and success are INFO; genuine rejections WARNING.
    if outcome == "success" or reason == "expired":
        audit_log.info("token_auth %s", detail, extra=extra)
    else:
        audit_log.warning("token_auth %s", detail, extra=extra)


# Token-type sentinels embedded in the JWT payload so the decoder can
# distinguish a long-lived PAT from a short-lived OIDC-issued token
# WITHOUT consulting the DB. Defense-in-depth for the credential-issuance
# flow: even if a row's ``expires_at`` is wiped by a DB tamper or
# migration bug, an OIDC token can still be rejected purely by inspecting
# its JWT claims (it'll fail the ``exp`` and ``aud`` checks).
TOKEN_TYPE_PAT = "pat"  # nosec B105 — token-type sentinel, not a credential
TOKEN_TYPE_OIDC = "oidc"  # nosec B105 — token-type sentinel, not a credential

# Forward clock-skew tolerance for last_used_at (#1044). A value up to this far
# ahead of our clock is treated as a concurrent worker's lead-clock write, not a
# stale value, so we never write an EARLIER time back over a newer one. Kept
# SEPARATE from the throttle window so even throttle=0 (write-every-request)
# still tolerates skew. Only a value beyond this is "broken clock / manual edit"
# and gets recovered. Matches the 60s OIDC clock-skew convention.
_LAST_USED_FORWARD_SKEW = timedelta(seconds=60)


def create_personal_access_token(
    user: AbstractBaseUser,
    *,
    expires_at: float | None = None,
    token_type: str = TOKEN_TYPE_PAT,
) -> str:
    """Mint a sbomify access-token JWT.

    For long-lived personal access tokens (the default), the JWT carries
    no ``exp`` and no ``aud`` — those PATs are revoked only via the DB
    row check in ``get_user_and_token_record``.

    For short-lived OIDC-issued tokens, the caller passes
    ``expires_at`` (unix timestamp) and ``token_type=TOKEN_TYPE_OIDC``.
    The JWT then carries:

    * ``exp`` — PyJWT rejects the token on decode once past it, even
      if the DB row's ``expires_at`` is missing / tampered with.
    * ``aud`` — pinned to ``settings.JWT_AUDIENCE`` so the same JWT
      can't be used against a sibling service that happens to share
      ``SECRET_KEY``.
    * ``token_type`` — lets the decoder tell PAT-shape from OIDC-shape
      tokens; future tightening can refuse OIDC tokens at endpoints
      that only accept PATs (or vice-versa).

    Invariant: ``expires_at`` and ``token_type=oidc`` MUST travel
    together. Without this, a caller could mint a token with
    ``expires_at`` set but ``token_type="pat"`` — the decoder would
    skip the JWT-level ``exp``/``aud`` checks (those only fire for
    ``token_type=oidc``) and the row's DB ``expires_at`` would be the
    only revocation mechanism, defeating the defense-in-depth the
    OIDC path is built on. Raise ``ValueError`` at mint time so this
    inconsistency can never reach a token.
    """
    if (expires_at is not None) != (token_type == TOKEN_TYPE_OIDC):
        raise ValueError(
            "expires_at and token_type=oidc must be set together "
            f"(got expires_at={expires_at!r}, token_type={token_type!r})"
        )

    salt = uuid4().hex[-4:] + str(time())[-4:]
    payload: dict[str, Any] = {
        "iss": settings.JWT_ISSUER,
        "sub": str(user.pk),
        "salt": salt,
        "token_type": token_type,
    }
    if expires_at is not None:
        payload["exp"] = int(expires_at)
        payload["aud"] = settings.JWT_AUDIENCE

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return token


def decode_personal_access_token(token: str) -> dict[str, Any]:
    """Decode + verify a sbomify access-token JWT.

    Two token shapes are accepted:

    * Long-lived PAT: no ``exp``, no ``aud``, ``token_type=`` either
      absent (legacy) or ``"pat"``.
    * Short-lived OIDC-issued: ``exp`` + ``aud`` REQUIRED,
      ``token_type="oidc"``. ``exp`` is enforced here (will reject the
      token if past) — defense-in-depth on top of the DB
      ``expires_at`` check in ``get_user_and_token_record``.

    The decode logic peeks at ``token_type`` to decide whether to
    require ``exp``/``aud`` — PyJWT's ``audience`` arg would otherwise
    reject PATs that legitimately have no ``aud`` claim.
    """
    try:
        # Verify the signature FIRST against our SECRET_KEY before
        # touching any claim — a token signed with the wrong key must
        # NEVER reach the re-encode path below (otherwise we'd be
        # re-encoding attacker-controlled content with our key and
        # validating that, defeating signature verification entirely).
        jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_signature": True,
                # We re-validate sub/exp/aud explicitly below depending
                # on token type; suppress them here so the peek doesn't
                # reject legitimate PATs (no exp/aud).
                "verify_sub": False,
                "verify_exp": False,
                "verify_aud": False,
            },
        )

        # Peek (signature already verified above) to decide which
        # validation profile applies. Suppress aud/exp checks during the
        # peek itself — for OIDC tokens the aud/exp claims are present
        # and PyJWT would otherwise raise InvalidAudienceError /
        # ExpiredSignatureError BEFORE we reach the typed re-decode
        # below, breaking valid OIDC authentication.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        # Signature was verified by the call above; this decode extracts
        # token_type so we know what to enforce in the final pass.
        unverified = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        token_type = unverified.get("token_type")

        decode_kwargs: dict[str, Any] = {
            "key": settings.SECRET_KEY,
            "algorithms": [settings.JWT_ALGORITHM],
        }
        if token_type == TOKEN_TYPE_OIDC:
            # OIDC-issued tokens must carry both exp and aud — minting
            # explicitly sets them. PyJWT will raise ExpiredSignatureError
            # / InvalidAudienceError on tamper.
            decode_kwargs["audience"] = settings.JWT_AUDIENCE
            decode_kwargs["options"] = {"require": ["sub", "exp", "aud", "token_type"]}
        else:
            # PAT (or legacy token with no token_type) — exp/aud absent
            # by design; revocation lives entirely in the DB row check.
            decode_kwargs["options"] = {
                "require": ["sub"],
                "verify_aud": False,
                "verify_exp": False,
            }

        # Normalise ``sub`` to a string first (legacy tokens may have
        # int subs). Re-encoding lets PyJWT validate the normalised
        # payload in one pass.
        if "sub" in unverified and not isinstance(unverified["sub"], str):
            unverified["sub"] = str(unverified["sub"])
        renormalised = jwt.encode(unverified, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        result: dict[str, Any] = jwt.decode(renormalised, **decode_kwargs)
        return result
    except jwt.ExpiredSignatureError as e:
        # Routine end-of-life for short-lived OIDC tokens — log at INFO
        # so it doesn't flood the WARNING channel as an "auth failure".
        log.info("Token expired: %s", e)
        raise DecodeError("Token expired") from e
    except InvalidTokenError as e:
        log.warning("Token validation failed: %s", e)
        raise DecodeError("Invalid token format") from e


def get_user_from_personal_access_token(token: str) -> AbstractBaseUser | None:
    "Get user from personal access token (deprecated: use get_user_and_token_record instead)"

    try:
        payload = decode_personal_access_token(token)
    except DecodeError as e:
        log.warning(f"Failed to decode token: {str(e)}")
        return None

    try:
        # Convert sub to string if needed
        user_id = str(payload["sub"])
        user = get_user_model().objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        return user
    except get_user_model().DoesNotExist:
        log.error("No active user found for token (user_id=%s)", user_id)
        return None


def get_user_and_token_record(
    token: str, *, source_ip: str | None = None, attempted_action: str | None = None
) -> tuple[AbstractBaseUser | None, AccessToken | None]:
    """Get user and AccessToken DB record from a personal access token.

    Rejection points, in evaluation order:

    1. ``decode_personal_access_token``: JWT signature (RS256/HS256
       against ``SECRET_KEY``) AND — for OIDC-issued tokens
       (``token_type="oidc"``) — JWT-level ``exp`` and ``aud`` claims.
       Long-lived PATs (no ``exp``/``aud``) only fail at the
       signature step.
    2. User liveness: the JWT's ``sub`` must resolve to a User row
       with ``is_active=True`` and ``deleted_at IS NULL``.
    3. AccessToken DB row exists for ``(user, encoded_token)``.
    4. Row-level expiry: ``AccessToken.expires_at`` (if set) must be
       in the future. Defense-in-depth on top of the JWT-level
       ``exp`` check — if a future code path stripped JWT claims but
       kept the DB row, this catches it.

    Tokens with ``expires_at IS NULL`` (never-expiring) skip step 4
    entirely; PATs with a chosen expiry and OIDC tokens both pass
    through it. A background sweep of expired rows is optional —
    step 4 is the source of truth.

    Returns:
        (user, access_token_record) on success, (None, None) on
        failure (at any of the four rejection points).
    """
    from .models import AccessToken

    def emit(
        outcome: str, *, reason: str | None = None, record: AccessToken | None = None, user_id: str | None = None
    ) -> None:
        _emit_token_auth_event(
            outcome,
            token=token,
            reason=reason,
            record=record,
            user_id=user_id,
            source_ip=source_ip,
            attempted_action=attempted_action,
        )

    try:
        payload = decode_personal_access_token(token)
    except DecodeError as e:
        # An OIDC JWT past its exp surfaces here as DecodeError raised from
        # jwt.ExpiredSignatureError — classify it as an expiry (INFO), not a
        # generic decode failure (WARNING), matching the DB-row expiry path.
        if isinstance(e.__cause__, jwt.ExpiredSignatureError):
            # decode_personal_access_token already logged the routine expiry; just
            # record the audit event (also INFO) without duplicating that line.
            emit("failure", reason="expired")
            return None, None
        log.warning(f"Failed to decode token: {str(e)}")
        emit("failure", reason="decode")
        return None, None

    user_id = str(payload.get("sub", ""))
    try:
        # Filter on liveness too: a soft-deleted or deactivated user must
        # NOT be able to authenticate via a still-DB-persisted token. This
        # matters most for OIDC bot users — deleting the bot has to revoke
        # in-flight credentials immediately, not at TTL expiry — and for any
        # admin-driven user deactivation flow.
        user = get_user_model().objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
    except (get_user_model().DoesNotExist, ValueError, TypeError) as e:
        # ValueError/TypeError: a missing or non-PK-shaped ``sub`` (e.g. ""/non-numeric
        # against an integer PK) — fail cleanly with an audit event, never a 500.
        log.warning("No live user found for token (user_id=%s): %s", user_id, str(e))
        emit("failure", reason="user_inactive_or_missing", user_id=user_id)
        return None, None

    access_token_record = AccessToken.objects.filter(user=user, encoded_token=token).select_related("team").first()
    if access_token_record is None:
        log.warning(f"No DB record found for token belonging to user {user_id}")
        emit("failure", reason="no_token_record", user_id=user_id)
        return None, None

    if access_token_record.is_expired:
        # Token is past its DB-row expires_at (an OIDC TTL or a PAT with
        # an expiry set). Log at INFO since this is expected end-of-life,
        # not an attack signal.
        log.info(
            "Rejecting expired access token (id=%s, expires_at=%s)",
            access_token_record.pk,
            access_token_record.expires_at,
        )
        emit("failure", reason="expired", record=access_token_record, user_id=user_id)
        return None, None

    # Stamp last-used for stale/leaked-token visibility (#1044). Only valid,
    # non-expired tokens reach here. The SELECT value short-circuits the common
    # case (no round-trip when it's genuinely fresh), but the throttle is ALSO
    # enforced in the UPDATE's WHERE so a concurrent worker that already refreshed
    # the row wins: the conditional update writes at most once per window and the
    # in-memory record is refreshed only when this request actually wrote it.
    now = timezone.now()
    throttle = settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS
    cutoff = now - timedelta(seconds=throttle)
    far_future = now + _LAST_USED_FORWARD_SKEW
    last_used = access_token_record.last_used_at
    # "Fresh" = within [cutoff, far_future]: recently stamped, OR stamped slightly
    # ahead by a concurrent worker whose clock leads ours (forward-skew tolerance,
    # so we never write an EARLIER time back over a newer one). The skew bound is
    # independent of the throttle window, so throttle=0 still tolerates skew.
    # Refresh on NULL, stale (< cutoff), or genuinely-far-future (> now + skew,
    # i.e. a broken clock / manual edit that would otherwise freeze the field).
    is_fresh = last_used is not None and cutoff <= last_used <= far_future
    if not is_fresh:
        updated = (
            AccessToken.objects.filter(pk=access_token_record.pk)
            .filter(Q(last_used_at__isnull=True) | Q(last_used_at__lt=cutoff) | Q(last_used_at__gt=far_future))
            .update(last_used_at=now)
        )
        if updated:
            access_token_record.last_used_at = now  # we wrote it; mirror in memory
        else:
            # updated == 0 means a concurrent worker refreshed the row between our
            # SELECT and this UPDATE. Mirror the persisted value so the returned
            # record isn't stale. This extra read only happens in that rare race,
            # never on the common (fresh or we-wrote-it) paths.
            access_token_record.refresh_from_db(fields=["last_used_at"])

    emit("success", record=access_token_record, user_id=user_id)
    return user, access_token_record
