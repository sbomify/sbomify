from django.http import HttpRequest
from sbomify.apps.core.middleware import RealIPMiddleware

def test_real_ip_middleware():
    """Test that RealIPMiddleware updates REMOTE_ADDR correctly."""
    middleware = RealIPMiddleware(get_response=lambda r: None)
    request = HttpRequest()
    
    # 1. Cloudflare IP
    request.META = {
        "HTTP_CF_CONNECTING_IP": "1.1.1.1",
        "HTTP_X_FORWARDED_FOR": "2.2.2.2",
        "REMOTE_ADDR": "4.4.4.4"
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "1.1.1.1"

    # 2. X-Forwarded-For IP
    request.META = {
        "HTTP_X_FORWARDED_FOR": "2.2.2.2, 3.3.3.3",
        "REMOTE_ADDR": "4.4.4.4"
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "2.2.2.2"

    # 3. No headers - should stay as REMOTE_ADDR
    request.META = {
        "REMOTE_ADDR": "4.4.4.4"
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "4.4.4.4"

