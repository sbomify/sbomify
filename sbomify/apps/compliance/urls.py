"""URL configuration for the compliance app."""

from django.urls import path

from .views.cra_product_list import CRAProductListView
from .views.cra_wizard import CRAStartAssessmentView, CRAStepView, CRAWizardShellView

app_name = "compliance"

urlpatterns = [
    path("cra/", CRAProductListView.as_view(), name="cra_product_list"),
    path("cra/start/<str:product_id>/", CRAStartAssessmentView.as_view(), name="cra_start_assessment"),
    path("cra/<str:assessment_id>/", CRAWizardShellView.as_view(), name="cra_wizard_shell"),
    path("cra/<str:assessment_id>/step/<int:step>/", CRAStepView.as_view(), name="cra_step"),
]
