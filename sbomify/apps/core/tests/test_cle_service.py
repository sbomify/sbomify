"""Tests for the CLE service layer (sbomify.apps.core.services.cle)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from libtea.models import CLE, CLEDefinitions, CLEEventType

from sbomify.apps.core.models import Component, ComponentRelease, Release
from sbomify.apps.core.services.cle import (
    create_cle_event,
    create_component_cle_event,
    create_component_release_cle_event,
    create_component_release_support_definition,
    create_component_support_definition,
    create_release_cle_event,
    create_release_support_definition,
    create_support_definition,
    get_cle_document,
    get_component_cle_document,
    get_component_release_cle_document,
    get_release_cle_document,
    recompute_lifecycle_dates,
)
from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
class TestCreateCLEEvent:
    """Tests for create_cle_event()."""

    def test_create_released_event(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert result.ok
        event = result.value
        assert event is not None
        assert event.event_id == 1
        assert event.event_type == "released"
        assert event.version == "1.0.0"

    def test_auto_increment_event_id(self, sample_product: Product) -> None:
        r1 = create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert r1.ok
        assert r1.value is not None
        assert r1.value.event_id == 1

        r2 = create_cle_event(
            sample_product,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        assert r2.ok
        assert r2.value is not None
        assert r2.value.event_id == 2

    def test_invalid_event_type(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "invalid_type",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert result.status_code == 400
        assert "Invalid event type" in (result.error or "")

    def test_released_without_version_succeeds(self, sample_product: Product) -> None:
        """Version is recommended but not enforced (UI sets date without version)."""
        result = create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert result.ok

    def test_released_with_empty_version_succeeds(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="",
        )
        assert result.ok

    def test_end_of_support_requires_versions_and_support_id(self, sample_product: Product) -> None:
        # Missing versions
        result = create_cle_event(
            sample_product,
            "endOfSupport",
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            support_id="standard",
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()

        # support_id is optional — omitting it should succeed
        result = create_cle_event(
            sample_product,
            "endOfSupport",
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
        )
        assert result.ok

    def test_end_of_support_requires_existing_support_definition(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfSupport",
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
            support_id="nonexistent",
        )
        assert not result.ok
        assert "does not exist" in (result.error or "").lower()

    def test_end_of_support_with_valid_support_definition(self, sample_product: Product) -> None:
        create_support_definition(sample_product, "standard", "Standard support")
        result = create_cle_event(
            sample_product,
            "endOfSupport",
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
            support_id="standard",
        )
        assert result.ok

    def test_end_of_development_requires_versions_and_support_id(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfDevelopment",
            datetime(2025, 12, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()

    def test_end_of_life_requires_versions(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfLife",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()

    def test_end_of_life_succeeds_with_versions(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfLife",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
        )
        assert result.ok

    def test_end_of_distribution_requires_versions(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfDistribution",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()

    def test_end_of_marketing_requires_versions(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "endOfMarketing",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()

    def test_superseded_by_requires_version(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "supersededBy",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "superseded_by_version" in (result.error or "").lower()

    def test_superseded_by_succeeds(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "supersededBy",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            superseded_by_version="2.0.0",
        )
        assert result.ok

    def test_component_renamed_requires_identifiers(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "componentRenamed",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "identifiers" in (result.error or "").lower()

    def test_component_renamed_succeeds(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "componentRenamed",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            identifiers=[{"type": "PURL", "value": "pkg:pypi/new-name"}],
        )
        assert result.ok

    def test_withdrawn_requires_event_id(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "withdrawn_event_id" in (result.error or "").lower()

    def test_withdrawn_requires_existing_event(self, sample_product: Product) -> None:
        result = create_cle_event(
            sample_product,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=999,
        )
        assert not result.ok
        assert "does not exist" in (result.error or "").lower()

    def test_withdrawn_succeeds(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        result = create_cle_event(
            sample_product,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=1,
        )
        assert result.ok
        assert result.value is not None
        assert result.value.withdrawn_event_id == 1


@pytest.mark.django_db
class TestCreateSupportDefinition:
    """Tests for create_support_definition()."""

    def test_create_support_definition(self, sample_product: Product) -> None:
        result = create_support_definition(
            sample_product,
            "standard",
            "Standard support with bugfixes",
            url="https://example.com/support",
        )
        assert result.ok
        defn = result.value
        assert defn is not None
        assert defn.support_id == "standard"
        assert defn.description == "Standard support with bugfixes"
        assert defn.url == "https://example.com/support"

    def test_create_support_definition_without_url(self, sample_product: Product) -> None:
        result = create_support_definition(sample_product, "security", "Security-only fixes")
        assert result.ok
        assert result.value is not None
        assert result.value.url == ""

    def test_duplicate_support_definition_rejected(self, sample_product: Product) -> None:
        r1 = create_support_definition(sample_product, "standard", "First definition")
        assert r1.ok

        r2 = create_support_definition(sample_product, "standard", "Different description")
        assert not r2.ok
        assert r2.status_code == 409
        assert "already exists" in (r2.error or "").lower()


@pytest.mark.django_db
class TestRecomputeLifecycleDates:
    """Tests for recompute_lifecycle_dates()."""

    def test_released_sets_release_date(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 3, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        sample_product.refresh_from_db()
        assert sample_product.release_date is not None
        assert sample_product.release_date.isoformat() == "2025-03-15"

    def test_end_of_support_sets_end_of_support(self, sample_product: Product) -> None:
        create_support_definition(sample_product, "standard", "Standard support")
        create_cle_event(
            sample_product,
            "endOfSupport",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
            support_id="standard",
        )
        sample_product.refresh_from_db()
        assert sample_product.end_of_support is not None
        assert sample_product.end_of_support.isoformat() == "2026-03-15"

    def test_end_of_life_sets_end_of_life(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "endOfLife",
            datetime(2027, 6, 30, tzinfo=timezone.utc),
            versions=[{"version": "1.x"}],
        )
        sample_product.refresh_from_db()
        assert sample_product.end_of_life is not None
        assert sample_product.end_of_life.isoformat() == "2027-06-30"

    def test_withdrawn_event_excluded_from_dates(self, sample_product: Product) -> None:
        # Create a released event, then withdraw it
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        sample_product.refresh_from_db()
        assert sample_product.release_date is not None

        create_cle_event(
            sample_product,
            "withdrawn",
            datetime(2025, 2, 1, tzinfo=timezone.utc),
            withdrawn_event_id=1,
        )
        sample_product.refresh_from_db()
        assert sample_product.release_date is None

    def test_latest_event_wins(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        sample_product.refresh_from_db()
        assert sample_product.release_date is not None
        assert sample_product.release_date.isoformat() == "2025-06-01"

    def test_no_events_clears_dates(self, sample_product: Product) -> None:
        sample_product.release_date = None
        sample_product.save()
        recompute_lifecycle_dates(sample_product)
        sample_product.refresh_from_db()
        assert sample_product.release_date is None
        assert sample_product.end_of_support is None
        assert sample_product.end_of_life is None


@pytest.mark.django_db
class TestGetCLEDocument:
    """Tests for get_cle_document()."""

    def test_no_events_returns_failure(self, sample_product: Product) -> None:
        result = get_cle_document(sample_product)
        assert not result.ok
        assert result.status_code == 404
        assert "No CLE events" in (result.error or "")

    def test_returns_cle_with_events(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert isinstance(cle, CLE)
        assert len(cle.events) == 1
        assert cle.events[0].type == CLEEventType.RELEASED
        assert cle.events[0].id == 1
        assert cle.events[0].version == "1.0.0"

    def test_events_ordered_descending(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.events[0].id == 2
        assert cle.events[1].id == 1

    def test_includes_definitions(self, sample_product: Product) -> None:
        create_support_definition(
            sample_product,
            "standard",
            "Standard support",
            url="https://example.com/support",
        )
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.definitions is not None
        assert isinstance(cle.definitions, CLEDefinitions)
        assert cle.definitions.support is not None
        assert len(cle.definitions.support) == 1
        assert cle.definitions.support[0].id == "standard"

    def test_no_definitions_when_none_exist(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.definitions is None

    def test_versions_converted_to_specifiers(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "endOfLife",
            datetime(2027, 1, 1, tzinfo=timezone.utc),
            versions=[{"version": "1.0.0"}, {"range": "vers:pypi/>=1.0,<2.0"}],
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        event = cle.events[0]
        assert event.versions is not None
        assert len(event.versions) == 2
        assert event.versions[0].version == "1.0.0"
        assert event.versions[1].range == "vers:pypi/>=1.0,<2.0"

    def test_identifiers_converted(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "componentRenamed",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            identifiers=[{"type": "PURL", "value": "pkg:pypi/new-name"}],
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        event = cle.events[0]
        assert event.identifiers is not None
        assert len(event.identifiers) == 1
        assert event.identifiers[0].id_type == "PURL"
        assert event.identifiers[0].id_value == "pkg:pypi/new-name"

    def test_withdrawn_event_id_mapped(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        create_cle_event(
            sample_product,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=1,
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        withdrawn_event = cle.events[0]  # Highest event_id first
        assert withdrawn_event.type == CLEEventType.WITHDRAWN
        assert withdrawn_event.event_id == 1

    def test_references_converted(self, sample_product: Product) -> None:
        create_cle_event(
            sample_product,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
            references=["https://example.com/release-notes", "https://example.com/changelog"],
        )
        result = get_cle_document(sample_product)
        assert result.ok
        cle = result.value
        assert cle is not None
        event = cle.events[0]
        assert event.references is not None
        assert len(event.references) == 2


# ===========================================================================
# Component-level CLE tests
# ===========================================================================


@pytest.mark.django_db
class TestComponentCLEEventCreation:
    """Tests for create_component_cle_event()."""

    @pytest.fixture
    def sample_component(self, sample_team_with_owner_member: Member) -> Component:
        return Component.objects.create(name="Test Component", team=sample_team_with_owner_member.team)

    def test_create_released_event(self, sample_component: Component) -> None:
        result = create_component_cle_event(
            sample_component,
            "released",
            datetime(2025, 1, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert result.ok
        event = result.value
        assert event is not None
        assert event.event_id == 1
        assert event.event_type == "released"
        assert event.version == "1.0.0"

    def test_auto_increment_event_id(self, sample_component: Component) -> None:
        r1 = create_component_cle_event(
            sample_component,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert r1.ok and r1.value is not None
        assert r1.value.event_id == 1

        r2 = create_component_cle_event(
            sample_component,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        assert r2.ok and r2.value is not None
        assert r2.value.event_id == 2

    def test_invalid_event_type(self, sample_component: Component) -> None:
        result = create_component_cle_event(
            sample_component,
            "invalid_type",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert result.status_code == 400

    def test_withdrawn_requires_existing_event(self, sample_component: Component) -> None:
        result = create_component_cle_event(
            sample_component,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=999,
        )
        assert not result.ok
        assert "does not exist" in (result.error or "").lower()

    def test_withdrawn_succeeds(self, sample_component: Component) -> None:
        create_component_cle_event(
            sample_component,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        result = create_component_cle_event(
            sample_component,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=1,
        )
        assert result.ok
        assert result.value is not None
        assert result.value.withdrawn_event_id == 1


@pytest.mark.django_db
class TestComponentSupportDefinition:
    """Tests for create_component_support_definition()."""

    @pytest.fixture
    def sample_component(self, sample_team_with_owner_member: Member) -> Component:
        return Component.objects.create(name="Test Component", team=sample_team_with_owner_member.team)

    def test_create_support_definition(self, sample_component: Component) -> None:
        result = create_component_support_definition(
            sample_component,
            "standard",
            "Standard support with bugfixes",
            url="https://example.com/support",
        )
        assert result.ok
        defn = result.value
        assert defn is not None
        assert defn.support_id == "standard"
        assert defn.description == "Standard support with bugfixes"
        assert defn.url == "https://example.com/support"

    def test_create_without_url(self, sample_component: Component) -> None:
        result = create_component_support_definition(sample_component, "security", "Security-only fixes")
        assert result.ok
        assert result.value is not None
        assert result.value.url == ""

    def test_duplicate_rejected(self, sample_component: Component) -> None:
        r1 = create_component_support_definition(sample_component, "standard", "First definition")
        assert r1.ok

        r2 = create_component_support_definition(sample_component, "standard", "Different description")
        assert not r2.ok
        assert r2.status_code == 409
        assert "already exists" in (r2.error or "").lower()


# ===========================================================================
# Release-level CLE tests
# ===========================================================================


@pytest.mark.django_db
class TestReleaseCLEEventCreation:
    """Tests for create_release_cle_event()."""

    @pytest.fixture
    def sample_release(self, sample_product: Product) -> Release:
        return Release.objects.create(name="v1.0", product=sample_product)

    def test_create_released_event(self, sample_release: Release) -> None:
        result = create_release_cle_event(
            sample_release,
            "released",
            datetime(2025, 1, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert result.ok
        event = result.value
        assert event is not None
        assert event.event_id == 1
        assert event.event_type == "released"
        assert event.version == "1.0.0"

    def test_auto_increment_event_id(self, sample_release: Release) -> None:
        r1 = create_release_cle_event(
            sample_release,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert r1.ok and r1.value is not None
        assert r1.value.event_id == 1

        r2 = create_release_cle_event(
            sample_release,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        assert r2.ok and r2.value is not None
        assert r2.value.event_id == 2

    def test_invalid_event_type(self, sample_release: Release) -> None:
        result = create_release_cle_event(
            sample_release,
            "invalid_type",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert result.status_code == 400

    def test_end_of_life_requires_versions(self, sample_release: Release) -> None:
        result = create_release_cle_event(
            sample_release,
            "endOfLife",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert "versions" in (result.error or "").lower()


@pytest.mark.django_db
class TestReleaseSupportDefinition:
    """Tests for create_release_support_definition()."""

    @pytest.fixture
    def sample_release(self, sample_product: Product) -> Release:
        return Release.objects.create(name="v1.0", product=sample_product)

    def test_create_support_definition(self, sample_release: Release) -> None:
        result = create_release_support_definition(
            sample_release,
            "standard",
            "Standard support with bugfixes",
            url="https://example.com/support",
        )
        assert result.ok
        defn = result.value
        assert defn is not None
        assert defn.support_id == "standard"
        assert defn.description == "Standard support with bugfixes"

    def test_create_without_url(self, sample_release: Release) -> None:
        result = create_release_support_definition(sample_release, "security", "Security-only fixes")
        assert result.ok
        assert result.value is not None
        assert result.value.url == ""

    def test_duplicate_rejected(self, sample_release: Release) -> None:
        r1 = create_release_support_definition(sample_release, "standard", "First definition")
        assert r1.ok

        r2 = create_release_support_definition(sample_release, "standard", "Different description")
        assert not r2.ok
        assert r2.status_code == 409
        assert "already exists" in (r2.error or "").lower()


# ===========================================================================
# ComponentRelease-level CLE tests
# ===========================================================================


@pytest.mark.django_db
class TestComponentReleaseCLEEventCreation:
    """Tests for create_component_release_cle_event()."""

    @pytest.fixture
    def sample_component_release(self, sample_team_with_owner_member: Member) -> ComponentRelease:
        component = Component.objects.create(name="CR Component", team=sample_team_with_owner_member.team)
        return ComponentRelease.objects.create(component=component, version="1.0.0")

    def test_create_released_event(self, sample_component_release: ComponentRelease) -> None:
        result = create_component_release_cle_event(
            sample_component_release,
            "released",
            datetime(2025, 1, 15, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert result.ok
        event = result.value
        assert event is not None
        assert event.event_id == 1
        assert event.event_type == "released"
        assert event.version == "1.0.0"

    def test_auto_increment_event_id(self, sample_component_release: ComponentRelease) -> None:
        r1 = create_component_release_cle_event(
            sample_component_release,
            "released",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            version="1.0.0",
        )
        assert r1.ok and r1.value is not None
        assert r1.value.event_id == 1

        r2 = create_component_release_cle_event(
            sample_component_release,
            "released",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            version="2.0.0",
        )
        assert r2.ok and r2.value is not None
        assert r2.value.event_id == 2

    def test_invalid_event_type(self, sample_component_release: ComponentRelease) -> None:
        result = create_component_release_cle_event(
            sample_component_release,
            "invalid_type",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert not result.ok
        assert result.status_code == 400

    def test_withdrawn_requires_existing_event(self, sample_component_release: ComponentRelease) -> None:
        result = create_component_release_cle_event(
            sample_component_release,
            "withdrawn",
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            withdrawn_event_id=999,
        )
        assert not result.ok
        assert "does not exist" in (result.error or "").lower()


@pytest.mark.django_db
class TestComponentReleaseSupportDefinition:
    """Tests for create_component_release_support_definition()."""

    @pytest.fixture
    def sample_component_release(self, sample_team_with_owner_member: Member) -> ComponentRelease:
        component = Component.objects.create(name="CR Component", team=sample_team_with_owner_member.team)
        return ComponentRelease.objects.create(component=component, version="1.0.0")

    def test_create_support_definition(self, sample_component_release: ComponentRelease) -> None:
        result = create_component_release_support_definition(
            sample_component_release,
            "standard",
            "Standard support with bugfixes",
            url="https://example.com/support",
        )
        assert result.ok
        defn = result.value
        assert defn is not None
        assert defn.support_id == "standard"
        assert defn.description == "Standard support with bugfixes"

    def test_create_without_url(self, sample_component_release: ComponentRelease) -> None:
        result = create_component_release_support_definition(
            sample_component_release, "security", "Security-only fixes"
        )
        assert result.ok
        assert result.value is not None
        assert result.value.url == ""

    def test_duplicate_rejected(self, sample_component_release: ComponentRelease) -> None:
        r1 = create_component_release_support_definition(sample_component_release, "standard", "First definition")
        assert r1.ok

        r2 = create_component_release_support_definition(sample_component_release, "standard", "Different description")
        assert not r2.ok
        assert r2.status_code == 409
        assert "already exists" in (r2.error or "").lower()


# ===========================================================================
# CLE Document tests for Component, Release, ComponentRelease
# ===========================================================================


@pytest.mark.django_db
class TestGetComponentCLEDocument:
    """Tests for get_component_cle_document()."""

    @pytest.fixture
    def sample_component(self, sample_team_with_owner_member: Member) -> Component:
        return Component.objects.create(name="Doc Component", team=sample_team_with_owner_member.team)

    def test_no_events_returns_failure(self, sample_component: Component) -> None:
        result = get_component_cle_document(sample_component)
        assert not result.ok
        assert result.status_code == 404

    def test_returns_cle_with_events(self, sample_component: Component) -> None:
        create_component_cle_event(
            sample_component, "released", datetime(2025, 1, 15, tzinfo=timezone.utc), version="1.0.0"
        )
        result = get_component_cle_document(sample_component)
        assert result.ok
        cle = result.value
        assert isinstance(cle, CLE)
        assert len(cle.events) == 1
        assert cle.events[0].type == CLEEventType.RELEASED

    def test_includes_definitions(self, sample_component: Component) -> None:
        create_component_support_definition(sample_component, "standard", "Standard support")
        create_component_cle_event(
            sample_component, "released", datetime(2025, 1, 1, tzinfo=timezone.utc), version="1.0.0"
        )
        result = get_component_cle_document(sample_component)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.definitions is not None
        assert cle.definitions.support is not None
        assert len(cle.definitions.support) == 1


@pytest.mark.django_db
class TestGetReleaseCLEDocument:
    """Tests for get_release_cle_document()."""

    @pytest.fixture
    def sample_release(self, sample_product: Product) -> Release:
        return Release.objects.create(name="v1.0", product=sample_product)

    def test_no_events_returns_failure(self, sample_release: Release) -> None:
        result = get_release_cle_document(sample_release)
        assert not result.ok
        assert result.status_code == 404

    def test_returns_cle_with_events(self, sample_release: Release) -> None:
        create_release_cle_event(
            sample_release, "released", datetime(2025, 3, 1, tzinfo=timezone.utc), version="1.0.0"
        )
        result = get_release_cle_document(sample_release)
        assert result.ok
        cle = result.value
        assert isinstance(cle, CLE)
        assert len(cle.events) == 1
        assert cle.events[0].type == CLEEventType.RELEASED

    def test_includes_definitions(self, sample_release: Release) -> None:
        create_release_support_definition(sample_release, "extended", "Extended support")
        create_release_cle_event(
            sample_release, "released", datetime(2025, 3, 1, tzinfo=timezone.utc), version="1.0.0"
        )
        result = get_release_cle_document(sample_release)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.definitions is not None
        assert cle.definitions.support is not None
        assert len(cle.definitions.support) == 1


@pytest.mark.django_db
class TestGetComponentReleaseCLEDocument:
    """Tests for get_component_release_cle_document()."""

    @pytest.fixture
    def sample_component_release(self, sample_team_with_owner_member: Member) -> ComponentRelease:
        component = Component.objects.create(name="CR Doc Component", team=sample_team_with_owner_member.team)
        return ComponentRelease.objects.create(component=component, version="2.0.0")

    def test_no_events_returns_failure(self, sample_component_release: ComponentRelease) -> None:
        result = get_component_release_cle_document(sample_component_release)
        assert not result.ok
        assert result.status_code == 404

    def test_returns_cle_with_events(self, sample_component_release: ComponentRelease) -> None:
        create_component_release_cle_event(
            sample_component_release, "released", datetime(2025, 5, 1, tzinfo=timezone.utc), version="2.0.0"
        )
        result = get_component_release_cle_document(sample_component_release)
        assert result.ok
        cle = result.value
        assert isinstance(cle, CLE)
        assert len(cle.events) == 1
        assert cle.events[0].type == CLEEventType.RELEASED

    def test_includes_definitions(self, sample_component_release: ComponentRelease) -> None:
        create_component_release_support_definition(sample_component_release, "premium", "Premium support")
        create_component_release_cle_event(
            sample_component_release, "released", datetime(2025, 5, 1, tzinfo=timezone.utc), version="2.0.0"
        )
        result = get_component_release_cle_document(sample_component_release)
        assert result.ok
        cle = result.value
        assert cle is not None
        assert cle.definitions is not None
        assert cle.definitions.support is not None
        assert len(cle.definitions.support) == 1
