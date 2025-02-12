import logging

import jwt
from social_core.exceptions import AuthFailed
from social_core.pipeline.partial import partial

logger = logging.getLogger(__name__)


# def debug_pipeline(strategy, backend, *args, **kwargs):
#     """Debug pipeline to log all incoming data from Auth0"""
#     logger.info("==== Debug Pipeline Start ====")
#     logger.info(f"Strategy: {strategy}")
#     logger.info(f"Backend: {backend}")
#     logger.info(f"Args: {args}")
#     # Log each kwarg separately to avoid potential sensitive data in one line
#     logger.info("Kwargs:")
#     for key, value in kwargs.items():
#         if key in ["response", "details", "user"]:
#             logger.info(f"{key}: {value}")
#     logger.info("==== Debug Pipeline End ====")
#     return {"debug_pipeline": "completed"}


def get_auth0_user_id(strategy, backend, response, details, *args, **kwargs):
    """Extract user ID from Auth0's response and add it to details"""
    logger.info("Extracting Auth0 user ID")

    if not response:
        logger.error("No response from Auth0")
        raise AuthFailed(backend, "No response from Auth0")

    # Try to get sub from id_token first (preferred method for social logins)
    id_token = response.get("id_token")
    if id_token:
        try:
            # Decode without verification as we just need the claims
            decoded = jwt.decode(id_token, options={"verify_signature": False})
            sub = decoded.get("sub")
            if sub:
                logger.info(f"Found user ID from id_token sub: {sub}")
                details["user_id"] = sub
                return {"details": details}
        except Exception as e:
            logger.warning(f"Failed to decode id_token: {e}")

    # Fallback to user_id from Auth0 user info
    user_id = response.get("user_id")
    if user_id:
        logger.info(f"Found user ID from response: {user_id}")
        details["user_id"] = user_id
        return {"details": details}

    # If we still don't have a user_id, try sub directly from response
    sub = response.get("sub")
    if sub:
        logger.info(f"Found user ID from response sub: {sub}")
        details["user_id"] = sub
        return {"details": details}

    logger.error("Could not find user ID in Auth0 response")
    raise AuthFailed(backend, "Could not find user ID in Auth0 response")


@partial
def require_email(
    strategy, backend, details, user=None, is_new=False, response=None, pipeline_index=None, *args, **kwargs
):
    """Require email from Auth0 response and verify its status."""
    logger.info("Starting require_email pipeline")
    logger.info(f"Details received: {details}")
    logger.info(f"Response received: {response}")
    logger.info(f"User: {user}, is_new: {is_new}")

    email = details.get("email")
    email_verified = response.get("email_verified", False) if response else False

    logger.info(f"Email: {email}, verified: {email_verified}")

    # Existing user with email, let them through
    if user and user.email and not is_new:
        logger.info("Existing user with email found")
        if not email:
            details["email"] = user.email
        return {"details": details, "is_new": is_new, "email_verified": email_verified}

    if not email:
        logger.warning("No email found in response")
        if is_new:
            # For new users, we require email
            logger.error("New user registration attempted without email")
            raise AuthFailed(backend, "Email is required to register. Please use a login method that provides email.")
        # For existing users, use their stored email
        if user and user.email:
            logger.info(f"Using stored email for existing user: {user.email}")
            details["email"] = user.email
            return {"details": details, "is_new": is_new, "email_verified": email_verified}

        logger.error("No email available for user")
        raise AuthFailed(backend, "Email is required. Please use a login method that provides email.")

    # For new users, require verified email
    if is_new and not email_verified:
        logger.error(f"New user with unverified email: {email}")
        raise AuthFailed(
            backend, "Please verify your email address before proceeding. Check your inbox for a verification email."
        )

    logger.info("Email requirements satisfied, continuing pipeline")
    return {"details": details, "is_new": is_new, "email_verified": email_verified}
