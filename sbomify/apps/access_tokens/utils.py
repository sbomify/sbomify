from __future__ import annotations

import typing
from time import time
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from jwt.exceptions import DecodeError, InvalidTokenError

from sbomify import logging

if typing.TYPE_CHECKING:
    from .models import AccessToken

log = logging.getLogger(__name__)


def create_personal_access_token(user: AbstractBaseUser) -> str:
    "Create personal access token for user that can be used in APIs"

    salt = uuid4().hex[-4:] + str(time())[-4:]
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": str(user.id),
        "salt": salt,
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return token


def decode_personal_access_token(token: str) -> dict:
    "Decode personal access token"

    try:
        # First verify the signature only
        jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_signature": True,
                "verify_sub": False,  # Don't validate subject type yet
            },
        )

        # If signature is valid, decode without verification to get the payload
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        # Signature was verified above (lines 35-43); this decode extracts payload for type normalization
        unverified_payload = jwt.decode(token, options={"verify_signature": False})

        # Convert sub to string if it exists and isn't already a string
        if "sub" in unverified_payload and not isinstance(unverified_payload["sub"], str):
            unverified_payload["sub"] = str(unverified_payload["sub"])

        # Now verify with the modified payload
        return jwt.decode(
            jwt.encode(unverified_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM),
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_signature": True,
                "require": ["sub"],
            },
        )
    except InvalidTokenError as e:
        log.warning(f"Token validation failed: {str(e)}")
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


def get_user_and_token_record(token: str) -> tuple[AbstractBaseUser | None, AccessToken | None]:
    """Get user and AccessToken DB record from a personal access token.

    This function verifies the JWT signature AND checks that a matching
    AccessToken record exists in the database. This enables true revocation:
    deleting the DB record immediately invalidates the token.

    Returns:
        (user, access_token_record) on success, (None, None) on failure.
    """
    from .models import AccessToken

    try:
        payload = decode_personal_access_token(token)
    except DecodeError as e:
        log.warning(f"Failed to decode token: {str(e)}")
        return None, None

    try:
        user_id = str(payload["sub"])
        user = get_user_model().objects.get(id=user_id)
    except get_user_model().DoesNotExist as e:
        log.error(f"User not found for token: {str(e)}")
        return None, None

    access_token_record = AccessToken.objects.filter(user=user, encoded_token=token).select_related("team").first()
    if access_token_record is None:
        log.warning(f"No DB record found for token belonging to user {user_id}")
        return None, None

    return user, access_token_record
