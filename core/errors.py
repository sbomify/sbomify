from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def error_response(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    return render(
        request=request,
        template_name="error.html",
        content_type="text/html",
        context={"exception": response},
        status=response.status_code,
    )
