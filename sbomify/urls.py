"""
URL configuration for sbomify project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.urls import include, path

from core.admin import admin_site

from .apis import api

urlpatterns = [
    path("admin/", admin_site.urls),
    path("", include("core.urls")),
    path("", include("social_django.urls", namespace="social")),
    path("", include("teams.urls")),
    path("", include("sboms.urls")),
    path("", include("billing.urls", namespace="billing")),
    path("api/v1/", api.urls, name="api-1"),
    path(r"UuPha8mu/", include("health_check.urls")),  # Random string
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
