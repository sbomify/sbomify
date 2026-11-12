"""Tests for the installation id and the installation usage report."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from django.core.cache import cache
from django.test import override_settings
from pytest_mock import MockerFixture

from sbomify.apps.core import posthog_service
from sbomify.apps.core.analytics import events
from sbomify.apps.core.models import Installation
from sbomify.apps.core.tasks import USAGE_REPORT_PENDING_KEY, report_installation_usage


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    posthog_service._client = None
    posthog_service._initialized = False
    cache.delete(USAGE_REPORT_PENDING_KEY)
    yield
    posthog_service._client = None
    posthog_service._initialized = False
    cache.delete(USAGE_REPORT_PENDING_KEY)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    posthog_service._client = client
    posthog_service._initialized = True
    return client


@pytest.mark.django_db
class TestInstallation:
    def test_get_creates_one_row(self) -> None:
        first = Installation.get()
        second = Installation.get()

        assert first.installation_id == second.installation_id
        assert isinstance(first.installation_id, uuid.UUID)
        assert Installation.objects.count() == 1

    def test_installation_id_is_cached(self, django_assert_num_queries) -> None:
        installation_id = posthog_service.get_installation_id()

        with django_assert_num_queries(0):
            assert posthog_service.get_installation_id() == installation_id
        assert installation_id == str(Installation.get().installation_id)

    def test_installation_id_is_empty_when_unreadable(self, mocker: MockerFixture) -> None:
        mocker.patch.object(Installation, "get", side_effect=RuntimeError("database down"))

        assert posthog_service.get_installation_id() == ""


@pytest.mark.django_db
class TestInstallationIdOnEveryCall:
    @pytest.fixture(autouse=True)
    def _posthog_enabled(self, settings) -> None:
        settings.POSTHOG_API_KEY = "phc_test_key"

    def test_capture(self, mock_client: MagicMock) -> None:
        posthog_service.capture("ws_key", "sbom:uploaded", {"sbom_id": "abc"})

        properties = mock_client.capture.call_args.kwargs["properties"]
        assert properties == {"sbom_id": "abc", "installation_id": str(Installation.get().installation_id)}

    def test_identify(self, mock_client: MagicMock) -> None:
        posthog_service.identify("42", {"email_hash": "x"})

        properties = mock_client.identify.call_args.kwargs["properties"]
        assert properties["installation_id"] == str(Installation.get().installation_id)

    def test_group_identify(self, mock_client: MagicMock) -> None:
        posthog_service.group_identify("workspace", "ws_key", {"billing_plan": "business"})

        properties = mock_client.group_identify.call_args.kwargs["properties"]
        assert properties["installation_id"] == str(Installation.get().installation_id)

    def test_caller_properties_are_not_mutated(self, mock_client: MagicMock) -> None:
        properties = {"sbom_id": "abc"}

        posthog_service.capture("ws_key", "sbom:uploaded", properties)

        assert properties == {"sbom_id": "abc"}

    def test_frontend_receives_installation_id(self, rf) -> None:
        from django.contrib.auth.models import AnonymousUser

        from sbomify.apps.core.context_processors import posthog_context

        request = rf.get("/")
        request.user = AnonymousUser()
        request.session = {}

        context = posthog_context(request)

        assert context["posthog_installation_id"] == str(Installation.get().installation_id)


@pytest.mark.django_db
class TestReportInstallationUsage:
    @override_settings(POSTHOG_API_KEY="phc_test_key")
    def test_reports_counts(self, mock_client: MagicMock, sample_component) -> None:
        from sbomify.apps.sboms.models import Component, Product
        from sbomify.apps.teams.models import Workspace

        report_installation_usage()

        installation_id = str(Installation.get().installation_id)
        mock_client.capture.assert_called_once()
        call = mock_client.capture.call_args
        assert call.args == (installation_id, events.INSTALLATION_USAGE_REPORTED)
        assert call.kwargs["groups"] == {"installation": installation_id}
        properties = call.kwargs["properties"]
        assert properties["workspace_count"] == Workspace.objects.count() >= 1
        assert properties["product_count"] == Product.objects.count() >= 1
        assert properties["component_count"] == Component.objects.count() >= 1
        assert properties["installation_id"] == installation_id
        assert events.validate_payload(
            events.INSTALLATION_USAGE_REPORTED,
            {k: v for k, v in properties.items() if k != "installation_id"},
        ) == []

    def test_noop_when_disabled(self, mock_client: MagicMock) -> None:
        report_installation_usage()

        mock_client.capture.assert_not_called()

    @override_settings(POSTHOG_API_KEY="phc_test_key")
    def test_clears_pending_marker(self, mock_client: MagicMock) -> None:
        cache.set(USAGE_REPORT_PENDING_KEY, True)

        report_installation_usage()

        assert cache.get(USAGE_REPORT_PENDING_KEY) is None


@pytest.mark.django_db(transaction=True)
class TestUsageReportScheduling:
    @pytest.fixture
    def posthog_enabled(self, settings) -> None:
        settings.POSTHOG_API_KEY = "phc_test_key"

    @pytest.fixture
    def mock_send(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("sbomify.apps.core.tasks.report_installation_usage.send_with_options")

    def test_creating_entities_queues_one_report(
        self, posthog_enabled: None, mock_send: MagicMock, sample_component
    ) -> None:
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["delay"] > 0

    def test_deleting_queues_a_report_after_the_last_one_ran(
        self, posthog_enabled: None, mock_send: MagicMock, sample_product
    ) -> None:
        from sbomify.apps.core.models import Component

        component = Component.objects.create(name="extra", team_id=sample_product.team_id)
        mock_send.reset_mock()
        cache.delete(USAGE_REPORT_PENDING_KEY)

        component.delete()

        mock_send.assert_called_once()

    def test_nothing_queued_when_disabled(self, mock_send: MagicMock, sample_component) -> None:
        mock_send.assert_not_called()
