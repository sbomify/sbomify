from social_core.exceptions import AuthFailed
from social_core.pipeline.partial import partial


@partial
def require_email(
    strategy, backend, details, user=None, is_new=False,
    response=None, pipeline_index=None, *args, **kwargs
):
    """Require email from Auth0 response and verify its status."""
    email = details.get("email")
    email_verified = response.get("email_verified", False) if response else False

    # Existing user with email, let them through
    if user and user.email and not is_new:
        if not email:
            details["email"] = user.email
        return {
            "details": details,
            "is_new": is_new,
            "email_verified": email_verified
        }

    if not email:
        if is_new:
            # For new users, we require email
            raise AuthFailed(
                backend,
                "Email is required to register. Please use a login method that provides email."
            )
        # For existing users, use their stored email
        if user and user.email:
            details["email"] = user.email
            return {
                "details": details,
                "is_new": is_new,
                "email_verified": email_verified
            }

        raise AuthFailed(
            backend,
            "Email is required. Please use a login method that provides email."
        )

    # For new users, require verified email
    if is_new and not email_verified:
        raise AuthFailed(
            backend,
            "Please verify your email address before proceeding. Check your inbox for a verification email."
        )

    return {
        "details": details,
        "is_new": is_new,
        "email_verified": email_verified
    }