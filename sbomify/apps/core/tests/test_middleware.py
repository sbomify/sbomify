from django.http import HttpRequest
from sbomify.apps.core.middleware import RealIPMiddleware

def test_real_ip_middleware_trusted_proxy():
    """
    Test that RealIPMiddleware updates REMOTE_ADDR correctly when
    behind a trusted proxy.
    """
    middleware = RealIPMiddleware(get_response=lambda r: None)
    request = HttpRequest()
    
    # 1. Behind Trusted Proxy (e.g. Caddy/LB)
    # Should resolve Cloudflare IP
    request.META = {
        "HTTP_CF_CONNECTING_IP": "1.1.1.1",
        "REMOTE_ADDR": "10.0.0.1" # Private/Trusted
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "1.1.1.1"

    # 2. Behind Trusted Proxy with X-Real-IP
    request.META = {
        "HTTP_X_REAL_IP": "2.2.2.2",
        "REMOTE_ADDR": "172.16.0.1" # Private/Trusted
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "2.2.2.2"

def test_real_ip_middleware_untrusted_source():
    """
    Test that RealIPMiddleware ignores headers from untrusted sources.
    """
    middleware = RealIPMiddleware(get_response=lambda r: None)
    request = HttpRequest()
    
    # Direct connection from public internet with spoofed headers
    request.META = {
        "HTTP_CF_CONNECTING_IP": "1.1.1.1",
        "HTTP_X_REAL_IP": "2.2.2.2",
        "HTTP_X_FORWARDED_FOR": "3.3.3.3",
        "REMOTE_ADDR": "8.8.8.8" # Public/Untrusted
    }
    middleware.process_request(request)
    
    # Should remain as the connecting IP
    assert request.META["REMOTE_ADDR"] == "8.8.8.8"
