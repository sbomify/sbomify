"Authentication middleware and related code."

from ninja.security import HttpBearer, django_auth

from .utils import get_user_from_personal_access_token


class PersonalAccessTokenAuth(HttpBearer):
    def authenticate(self, request, token):
        user = get_user_from_personal_access_token(token)
        if user is None:
            return None

        setattr(request, "user", user)

        return user, token


class OptionalAuthBase(HttpBearer):
    def authenticate(self, request, token=None):
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


def optional_auth(func):
    auth_instance = OptionalAuthBase()

    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        auth_instance.authenticate(request, token)
        return func(request, *args, **kwargs)

    return wrapper


def optional_token_auth(func):
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            PersonalAccessTokenAuth().authenticate(request, token)
        return func(request, *args, **kwargs)

    return wrapper
