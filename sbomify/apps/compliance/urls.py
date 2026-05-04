"""URL configuration for the compliance app."""

from django.urls import path

from .views.cra_product_list import CRAProductListView
from .views.cra_wizard import CRAScopeScreeningView, CRAStartAssessmentView, CRAStepView, CRAWizardShellView
from .views.doc_public import ProductDoCPublicView
from .views.vdp_public import ProductVDPPublicView

app_name = "compliance"

urlpatterns = [
    path("cra/", CRAProductListView.as_view(), name="cra_product_list"),
    path("cra/scope/<str:product_id>/", CRAScopeScreeningView.as_view(), name="cra_scope_screening"),
    path("cra/start/<str:product_id>/", CRAStartAssessmentView.as_view(), name="cra_start_assessment"),
    path("cra/<str:assessment_id>/", CRAWizardShellView.as_view(), name="cra_wizard_shell"),
    path("cra/<str:assessment_id>/step/<int:step>/", CRAStepView.as_view(), name="cra_step"),
    path(
        "public/product/<str:product_id>/vdp/",
        ProductVDPPublicView.as_view(),
        name="product_vdp_public",
    ),
    path(
        "public/product/<str:product_id>/declaration-of-conformity/",
        ProductDoCPublicView.as_view(),
        name="product_doc_public",
    ),
]
