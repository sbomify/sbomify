"""Access control for the ops dashboard.

The dashboard reports across every workspace, so it is staff-only and has no
workspace scoping. It answers 404 rather than 403 to anyone else: a signed-in
customer poking at ``/ops/`` should learn nothing, not even that the surface
exists.
"""

from __future__ import annotations

from typing import Any

from django.http import Http404, HttpRequest
from django.http.response import HttpResponseBase
from django.views import View


class StaffRequiredMixin(View):
    """Restrict a view to active staff users.

    ``is_staff`` is the same flag the Django admin uses, so this hands the
    dashboard to exactly the people who could already read the data through
    the model admin. If the two ever need to diverge, this is the one place
    to change.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        user = request.user
        if not (user.is_authenticated and user.is_active and user.is_staff):
            raise Http404
        return super().dispatch(request, *args, **kwargs)
