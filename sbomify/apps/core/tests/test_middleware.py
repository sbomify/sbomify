from django.http import HttpRequest

from sbomify.apps.core.middleware import RealIPMiddleware


def test_real_ip_middleware():
    """Test that RealIPMiddleware updates REMOTE_ADDR correctly."""
    middleware = RealIPMiddleware(get_response=lambda r: None)
    request = HttpRequest()
    
    # 1. X-Real-IP present (standard Caddy setup)
    request.META = {
        "HTTP_X_REAL_IP": "1.2.3.4",
        "REMOTE_ADDR": "10.0.0.1"
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "1.2.3.4"

    # 2. No X-Real-IP, should stay as REMOTE_ADDR
    request.META = {
        "REMOTE_ADDR": "10.0.0.1"
    }
    middleware.process_request(request)
    assert request.META["REMOTE_ADDR"] == "10.0.0.1"
