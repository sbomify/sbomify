from django.urls import path

from . import views

app_name = "onboarding"
urlpatterns = [
    path("select-plan/", views.OnboardingPlanSelectionView.as_view(), name="select_plan"),
]
