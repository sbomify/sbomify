import logging

from django.utils.deprecation import MiddlewareMixin

from sbomify.apps.core.utils import get_client_ip

logger = logging.getLogger(__name__)


class RealIPMiddleware(MiddlewareMixin):
    """
    Middleware to correct the REMOTE_ADDR using CF-Connecting-IP and X-Real-IP
    headers when behind a trusted proxy.

    This ensures that logging, Sentry, and views see the correct client IP.
    """

    def process_request(self, request):
        client_ip = get_client_ip(request)
        if client_ip:
            request.META["REMOTE_ADDR"] = client_ip
