# from __future__ import annotations

# from urllib.parse import quote

import jwt
import pytest
from django.conf import settings
# from django.http import HttpResponse
# from django.test import Client
# from django.urls import reverse
# from django.contrib.messages import get_messages
# from django.conf import settings
# from rest_framework.test import APIClient

from core.fixtures import sample_user  # noqa: F401
from .utils import (
    create_personal_access_token,
    decode_personal_access_token,
    get_user_from_personal_access_token,
)


@pytest.mark.django_db
def test_access_token_encode_decode(sample_user):  # noqa: F811
    token_str = create_personal_access_token(sample_user)
    assert isinstance(token_str, str)
    assert token_str

    decoded_token = decode_personal_access_token(token_str)
    assert isinstance(decoded_token, dict)
    assert decoded_token['sub'] == str(sample_user.id)
    assert decoded_token['iss'] == 'sbomify'
    assert 'salt' in decoded_token

    user = get_user_from_personal_access_token(token_str)
    assert user == sample_user


@pytest.mark.django_db
def test_token_with_minimal_payload(sample_user):  # noqa: F811
    # Create a token with just the required fields
    minimal_payload = {
        "sub": str(sample_user.id),
    }
    minimal_token = jwt.encode(minimal_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # Should be able to decode and use the token
    decoded_token = decode_personal_access_token(minimal_token)
    assert isinstance(decoded_token, dict)
    assert decoded_token['sub'] == str(sample_user.id)

    user = get_user_from_personal_access_token(minimal_token)
    assert user == sample_user


@pytest.mark.django_db
def test_token_with_integer_subject(sample_user):  # noqa: F811
    # Create a token with integer subject ID
    payload = {
        "sub": int(sample_user.id),  # Force integer type
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # Should be able to decode and use the token
    decoded_token = decode_personal_access_token(token)
    assert isinstance(decoded_token, dict)
    assert decoded_token['sub'] == str(sample_user.id)  # Should be converted to string

    user = get_user_from_personal_access_token(token)
    assert user == sample_user


@pytest.mark.django_db
def test_invalid_token_handling(sample_user):  # noqa: F811
    # Test with invalid signature
    invalid_token = jwt.encode(
        {"sub": str(sample_user.id)},
        "wrong_secret",
        algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(jwt.exceptions.DecodeError):
        decode_personal_access_token(invalid_token)

    assert get_user_from_personal_access_token(invalid_token) is None

    # Test with malformed token
    malformed_token = "not.a.token"
    with pytest.raises(jwt.exceptions.DecodeError):
        decode_personal_access_token(malformed_token)

    assert get_user_from_personal_access_token(malformed_token) is None

    # Test with non-existent user
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": "99999",  # Non-existent user ID
        "salt": "test",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert get_user_from_personal_access_token(token) is None

# @pytest.mark.django_db
# def test_projects_dashboard_only_accessible_when_logged_in(sample_team_with_owner_member):  # noqa: F811
#     client = Client()

#     uri = reverse("sboms:projects_dashboard")
#     response: HttpResponse = client.get(uri)

#     assert response.status_code == 302
#     assert response.url.startswith(settings.LOGIN_URL)

#     assert client.login(
#         username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
#     )

#     response: HttpResponse = client.get(uri)

#     assert response.status_code == 200
#     assert quote(response.request["PATH_INFO"]) == uri