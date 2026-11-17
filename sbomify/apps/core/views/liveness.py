from django.http import HttpRequest, HttpResponse
from django.views import View


class LivenessView(View):
    """Whether this process can answer HTTP at all, for the reverse proxy.

    Deliberately checks nothing else. The database check at ``/UuPha8mu/`` is
    for monitoring: as the proxy's health check, one database blip marked every
    backend down and turned each request, cached Trust Center pages included,
    into a 503 at the proxy before the application could answer it.
    """

    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK", content_type="text/plain")


liveness = LivenessView.as_view()
