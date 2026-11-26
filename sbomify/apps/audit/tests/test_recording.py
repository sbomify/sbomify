"""What lands in the audit log, attributed to whom."""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from sbomify.apps.audit.context import AuditContext, audit_context
from sbomify.apps.audit.models import ActorType, AuditEvent, Channel, Outcome
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.sboms.models import ProductComponent
from sbomify.apps.teams.models import Member

from .conftest import events

pytestmark = pytest.mark.django_db


def test_session_api_write_is_recorded_with_actor_and_request(
    owner_client, enterprise, sample_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = owner_client.post(
            "/api/v1/products",
            json.dumps({"name": "Rocket"}),
            content_type="application/json",
            HTTP_USER_AGENT="pytest-agent",
        )
    assert response.status_code == 201

    [event] = events(enterprise, action="product.created")
    assert event.actor_user_id == sample_user.pk
    assert event.actor_label == sample_user.email
    assert event.actor_role == "owner"
    assert event.actor_type == ActorType.USER
    assert event.channel == Channel.API
    assert event.credential_kind == "session"
    assert event.target_type == "product"
    assert event.target_label == "Rocket"
    assert event.user_agent == "pytest-agent"
    assert event.http_method == "POST"
    assert event.path == "/api/v1/products"
    assert event.metadata["fields"]["name"] == "Rocket"
    # A semantic event was recorded, so no generic request event duplicates it.
    assert not events(enterprise, action="request.post")


def test_nothing_is_recorded_below_enterprise(client, team_with_business_plan, sample_user, django_capture_on_commit_callbacks):
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/api/v1/products", json.dumps({"name": "Rocket"}), content_type="application/json")
    assert not AuditEvent.objects.filter(workspace_id=team_with_business_plan.pk).exists()


def test_updates_record_what_changed(enterprise, sample_user, django_capture_on_commit_callbacks):
    product = Product.objects.create(team=enterprise, name="Before")
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        product.name = "After"
        product.description = "secret plans"
        product.save()
        # A save that touches nothing watched is not an event.
        product.save(update_fields=["custom_metadata"])

    [event] = events(enterprise, action="product.updated")
    assert event.metadata["changes"] == {"name": {"from": "Before", "to": "After"}}
    # The description's value is not copied into the log, only that it changed.
    assert event.metadata["changed"] == ["description"]


def test_changes_outside_any_context_are_not_user_activity(enterprise, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        Product.objects.create(team=enterprise, name="From a background task")
    assert not events(enterprise)


def test_cascaded_deletes_are_covered_by_the_parent_event(enterprise, sample_user, django_capture_on_commit_callbacks):
    product = Product.objects.create(team=enterprise, name="Doomed")
    component = Component.objects.create(team=enterprise, name="Part")
    ProductComponent.objects.create(product=product, component=component)

    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        product.delete()

    assert [e.action for e in events(enterprise)] == ["product.deleted"]
    assert events(enterprise)[0].target_label == "Doomed"


def test_membership_role_change_is_recorded(enterprise, sample_user, member_user, django_capture_on_commit_callbacks):
    membership = Member.objects.get(team=enterprise, user=member_user)
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        membership.role = "admin"
        membership.save()

    [event] = events(enterprise, action="member.updated")
    assert event.target_label == member_user.email
    assert event.metadata["changes"]["role"] == {"from": "member", "to": "admin"}


def test_unrecognised_write_falls_back_to_a_request_event(owner_client, enterprise, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        owner_client.post(
            reverse("workspaces:team_settings_tab", kwargs={"workspace_key": enterprise.key, "tab": "general"}),
            {"unknown_action": "update", "secret_value": "do-not-log"},
        )

    [event] = events(enterprise, action="request.post")
    assert event.outcome == Outcome.SUCCESS
    assert event.metadata["route"] == "workspaces:team_settings_tab"
    assert event.metadata["form"] == {"unknown_action": "update"}
    assert "do-not-log" not in json.dumps(event.metadata)


def test_refused_write_is_recorded_as_denied(client, enterprise, member_user):
    setup_authenticated_client_session(client, enterprise, member_user)
    response = client.post(reverse("audit:retention", kwargs={"workspace_key": enterprise.key}), {"retention_days": 30})
    assert response.status_code == 403

    [event] = events(enterprise, action="request.post")
    assert event.outcome == Outcome.DENIED
    assert event.status_code == 403
    assert event.actor_user_id == member_user.pk
    assert event.actor_role == "member"


def test_reads_are_not_recorded(owner_client, enterprise, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        owner_client.get("/api/v1/products")
    assert not events(enterprise)


@pytest.mark.parametrize(
    ("scopes", "actor_type", "channel"),
    [
        (None, ActorType.USER, Channel.API),
        (SCOPE_PRESETS["agent"], ActorType.AGENT, Channel.API),
    ],
)
def test_token_requests_name_the_token_and_agent_tokens_are_agents(
    client, enterprise, make_token, scopes, actor_type, channel, django_capture_on_commit_callbacks
):
    token = make_token(scopes)
    with django_capture_on_commit_callbacks(execute=True):
        client.put(
            reverse("api-2:set_audit_retention", kwargs={"workspace_key": enterprise.key}),
            json.dumps({"retention_days": 120}),
            content_type="application/json",
            **get_api_headers(token),
        )

    [event] = events(enterprise)
    assert event.actor_type == actor_type
    assert event.channel == channel
    assert event.credential_kind == "pat"
    assert event.credential_id == str(token.pk)


def test_sign_in_is_recorded_in_each_internal_workspace(client, enterprise, sample_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.force_login(sample_user)
    [event] = events(enterprise, action="auth.signed_in")
    assert event.actor_user_id == sample_user.pk


def test_an_outsider_cannot_write_into_another_workspaces_log(client, enterprise, guest_user):
    client.force_login(guest_user)
    response = client.post(
        reverse("workspaces:team_settings_tab", kwargs={"workspace_key": enterprise.key, "tab": "general"}),
        {"x_action": "flood"},
    )
    assert response.status_code == 403
    assert not events(enterprise)


def test_a_request_with_no_workspace_in_its_url_is_not_filed_under_the_session(
    owner_client, enterprise, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        owner_client.patch("/api/v1/components/doesnotexist", "{}", content_type="application/json")
    assert not events(enterprise, action="request.patch")


def test_partial_save_records_only_persisted_values(enterprise, sample_user, django_capture_on_commit_callbacks):
    product = Product.objects.create(team=enterprise, name="Persisted")
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        product.name = "Unsaved name"
        product.description = "Unsaved description"
        product.is_public = True
        product.save(update_fields=["is_public"])

    product.refresh_from_db()
    assert product.name == "Persisted"
    [event] = events(enterprise, action="product.updated")
    assert event.target_label == "Persisted"
    assert event.metadata == {"changes": {"is_public": {"from": False, "to": True}}}


@pytest.mark.parametrize("reverse", [False, True])
def test_many_to_many_link_additions_are_recorded(
    enterprise, sample_user, django_capture_on_commit_callbacks, reverse
):
    product = Product.objects.create(team=enterprise, name="Product")
    component = Component.objects.create(team=enterprise, name="Component")
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        if reverse:
            product.components.add(component)
            product.components.add(component)
        else:
            component.products.add(product)
            component.products.add(product)

    [event] = events(enterprise, action="product_component.created")
    assert event.target_id == str(ProductComponent.objects.get(product=product, component=component).pk)
    assert event.metadata["fields"] == {"product_id": product.pk, "component_id": component.pk}


@pytest.mark.parametrize("delete", [False, True])
def test_own_membership_change_keeps_the_actors_original_role(
    enterprise, sample_user, django_capture_on_commit_callbacks, delete
):
    membership = Member.objects.get(team=enterprise, user=sample_user)
    assert membership.role == "owner"
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        if delete:
            membership.delete()
        else:
            membership.role = "admin"
            membership.save(update_fields=["role"])

    [event] = events(enterprise, action="member.deleted" if delete else "member.updated")
    assert event.actor_role == "owner"


@pytest.mark.parametrize("field", ["user", "user_id"])
def test_partial_foreign_key_save_is_recorded(
    enterprise, sample_user, member_user, guest_user, django_capture_on_commit_callbacks, field
):
    membership = Member.objects.get(team=enterprise, user=member_user)
    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        membership.user = guest_user
        membership.save(update_fields=[field])

    [event] = events(enterprise, action="member.updated")
    assert event.metadata["changes"] == {"user_id": {"from": member_user.pk, "to": guest_user.pk}}


def test_expression_update_records_its_result(enterprise, sample_user, django_capture_on_commit_callbacks):
    from django.db.models import F

    with audit_context(AuditContext(user=sample_user)), django_capture_on_commit_callbacks(execute=True):
        enterprise.audit_log_retention_days = F("audit_log_retention_days") + 30
        enterprise.save(update_fields=["audit_log_retention_days"])

    [event] = events(enterprise, action="workspace.updated")
    assert event.metadata["changes"] == {"audit_log_retention_days": {"from": 365, "to": 395}}
