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

Custom Domain Routing:
When a request comes through a custom domain (detected by CustomDomainContextMiddleware),
custom domain URL patterns are included to provide clean URLs without /public/ prefix.
The views check request.is_custom_domain to determine appropriate behavior.
"""

from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView

from sbomify.apis import api
from sbomify.apps.billing.views import public_enterprise_contact
from sbomify.apps.core.admin import admin_site
from sbomify.apps.teams.urls import domain_check

urlpatterns = [
    # Favicon redirect for browsers requesting /favicon.ico at root
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicons/favicon.ico", permanent=True)),
    path("admin/", admin_site.urls),
    # Redirect old accounts/login to our Keycloak login
    path("accounts/login/", RedirectView.as_view(url="/login/", permanent=True)),
    path("accounts/", include("allauth.urls")),
    path("enterprise-contact/", public_enterprise_contact, name="public_enterprise_contact"),
    path(".well-known/com.sbomify.domain-check", domain_check, name="domain_check"),
    # Standard URLs (includes /public/* patterns and private pages)
    path("", include("sbomify.apps.core.urls")),
    # Keep the legacy prefix but avoid clashing namespaces with the primary teams URLs
    path("workspace/", include(("sbomify.apps.teams.urls", "teams"), namespace="teams-legacy")),
    path("workspaces/", include("sbomify.apps.teams.urls")),
    path("", include("sbomify.apps.sboms.urls")),
    path("", include("sbomify.apps.documents.urls")),
    path("billing/", include("sbomify.apps.billing.urls")),
    path("plugins/", include("sbomify.apps.plugins.urls")),
    path("", include("sbomify.apps.vulnerability_scanning.urls")),
    path("api/v1/", api.urls, name="api-1"),
    path(r"UuPha8mu/", include("health_check.urls")),  # Random string
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()

    # Only add debug toolbar URLs if debug_toolbar is available
    try:
        import debug_toolbar  # noqa: F401

        urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
    except ImportError:
        # Debug toolbar not available (e.g., in production with DEBUG=True)
        pass
