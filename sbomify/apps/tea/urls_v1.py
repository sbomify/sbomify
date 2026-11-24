"""URL patterns for TEA 1.0.0. The API is built in ``urls.py``, next to the 0.4.0 one."""

from django.urls import path

from sbomify.apps.tea.urls import tea_v1_api

urlpatterns = [
    path("", tea_v1_api.urls),
]
