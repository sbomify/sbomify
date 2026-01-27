from time import time
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from jwt.exceptions import DecodeError, InvalidTokenError

from sbomify import logging

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


def get_user_from_personal_access_token(token: str) -> AbstractBaseUser:
    "Get user from personal access token"

    try:
        payload = decode_personal_access_token(token)
    except DecodeError as e:
        log.warning(f"Failed to decode token: {str(e)}")
        return None

    try:
        # Convert sub to string if needed
        user_id = str(payload["sub"])
        user = get_user_model().objects.get(id=user_id)
        return user
    except get_user_model().DoesNotExist as e:
        log.error(f"User not found for token: {str(e)}")
        return None
