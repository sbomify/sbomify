from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("<workspace_key>/audit-log/events", views.AuditLogView.as_view(), name="events"),
    path("<workspace_key>/audit-log/export", views.AuditLogExportView.as_view(), name="export"),
    path("<workspace_key>/audit-log/retention", views.AuditRetentionView.as_view(), name="retention"),
]
