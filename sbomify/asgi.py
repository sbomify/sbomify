"""
ASGI config for sbomify project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")

# Get the Django ASGI application - must be called before importing channels
django_application = get_asgi_application()

# Import channels after Django is initialized
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from sbomify.apps.core.routing import websocket_urlpatterns  # noqa: E402


class LifespanApp:
    """
    Handles ASGI lifespan events (startup/shutdown).

    This is necessary because Django's ASGI application doesn't handle
    lifespan events, which are sent by ASGI servers like uvicorn.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await self.app(scope, receive, send)


# Main ASGI application with protocol routing
application = LifespanApp(
    ProtocolTypeRouter(
        {
            "http": django_application,
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )
)
