"""
Utility code used by multiple apps.
"""

import collections.abc
import string
import uuid
from dataclasses import dataclass
from secrets import token_urlsafe

from django.http import HttpRequest

TRANSLATION_STRING = "abcdefghij"


def number_to_random_token(value: int) -> str:
    """
    Convert an integer to a random token.
    """
    tok_prefix = token_urlsafe(6)
    tok_suffix = "".join(TRANSLATION_STRING[int(c)] for c in str(value))

    return f"{tok_prefix}{tok_suffix}"


def token_to_number(token: str) -> int:
    """
    Convert a random token to an integer.

    Args:
        token: The token string to convert

    Returns:
        The integer value encoded in the token

    Raises:
        ValueError: If token is too short or contains invalid characters
    """
    if len(token) < 9:
        raise ValueError("Token is too short")

    try:
        return int("".join(str(TRANSLATION_STRING.index(c)) for c in token[8:]))
    except ValueError:
        raise ValueError("Invalid token format")


def get_current_team_id(request: HttpRequest) -> int | None:
    """
    Get the team ID for the current team from the request.

    Request contains team keys which can be translated into team IDs.

    If no current team is found in the request session, return None.
    """
    team_key = request.session.get("current_team", {}).get("key")
    if team_key is None:
        return None

    return token_to_number(team_key)


def dict_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = dict_update(d.get(k, {}), v)
        else:
            d[k] = v

    return d


def set_values_if_not_empty(object_in, **kwargs):
    for attribute_name, attribute_value in kwargs.items():
        if attribute_value:
            setattr(object_in, attribute_name, attribute_value)


@dataclass
class ExtractSpec:
    field: str
    required: bool = True
    default: any = None
    error_message: str | None = None
    rename_to: str | None = None


def obj_extract(obj_in, fields: list[ExtractSpec]) -> dict:
    """
    Extract fields from an object.

    :param obj_in: The object to extract fields from.
    :param fields: A list of ExtractSpec objects.
    :return: A dictionary of extracted fields.
    """
    result = {}

    for field in fields:
        # if field.field contains a dot, it means we need to extract a nested field

        field_parts = field.field.split(".")
        value = obj_in

        for part in field_parts:
            value = getattr(value, part, None)

            if value is None:
                if field.required:
                    if field.error_message:
                        raise ValueError(field.error_message)
                    else:
                        raise ValueError(f"Field '{field.field}' is required.")

                elif field.default:
                    if field.rename_to:
                        result[field.rename_to] = field.default
                    else:
                        result[field.field] = field.default

                    break

                else:
                    break

        if value is not None:
            if field.rename_to:
                result[field.rename_to] = value
            else:
                result[field.field] = value

    return result


def generate_id() -> str:
    """Generate a globally unique ID that is 12 characters long.

    The ID will:
    - Contain only alphanumeric characters (0-9, a-z, A-Z)
    - Always start with a letter
    - Be 12 characters long
    - Have sufficient entropy to avoid collisions (72 bits)

    Returns:
        str: A unique alphanumeric ID, 12 characters long.
    """
    # Characters for base62 encoding (0-9, a-z, A-Z)
    CHARS = string.ascii_letters + string.digits  # Letters first to bias towards letters

    while True:
        # Generate 9 random bytes (72 bits) of entropy
        # This gives us ~4.7e21 possible values - more than enough for uniqueness
        random_int = int.from_bytes(uuid.uuid4().bytes[:9], "big")

        # Convert to base62
        base62 = ""
        temp_int = random_int
        while temp_int:
            temp_int, remainder = divmod(temp_int, 62)
            base62 = CHARS[remainder] + base62

        # Pad with 'a' if needed to reach exactly 12 chars
        base62 = base62.rjust(12, "a")

        # If longer than 12 chars, try again with new random value
        if len(base62) > 12:
            continue

        # Ensure first character is a letter by replacing it if it's not
        if not base62[0].isalpha():
            # Use last 6 bits of the random_int to select a letter (0-51)
            letter_idx = random_int % 52
            base62 = string.ascii_letters[letter_idx] + base62[1:]

        return base62
