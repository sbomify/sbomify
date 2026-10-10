from __future__ import annotations

from django.urls import path

from . import views

app_name = "ops"
urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
]
