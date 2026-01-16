from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from sbomify.apps.core.domain.exceptions import DomainError


def error_response(request: HttpRequest, response: HttpResponse | DomainError) -> HttpResponse:
    if isinstance(response, DomainError):
        response = HttpResponse(response.detail, status=response.status_code)
    return render(
        request=request,
        template_name="error.html.j2",
        content_type="text/html",
        context={"exception": response},
        status=response.status_code,
    )
