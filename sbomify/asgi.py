"""
ASGI config for sbomify project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")

# Get the Django ASGI application
django_application = get_asgi_application()


async def application(scope, receive, send):
    """
    ASGI application that handles lifespan events and delegates HTTP/WebSocket to Django.

    This wrapper is necessary because Django's ASGI application doesn't handle
    lifespan events, which are sent by ASGI servers like uvicorn.
    """
    if scope["type"] == "lifespan":
        # Handle lifespan events (startup/shutdown)
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # Acknowledge startup
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                # Acknowledge shutdown
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        # Delegate HTTP and WebSocket connections to Django
        await django_application(scope, receive, send)
