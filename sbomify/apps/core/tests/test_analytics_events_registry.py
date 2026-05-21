"""Tests for the PostHog event registry.

These exercise the registry itself (invariants, validation helper) plus
two layers of drift detection:

* ``TestCoverageOfShippedEvents`` asserts the ``SHIPPED_EVENTS`` set
  matches the registered set bidirectionally. A new ``capture()`` call
  site that ships an unregistered event NAME — or a registered event
  that no production code fires — surfaces as a test failure when the
  engineer updates this list (which they must, to make their work
  visible to analytics consumers).
* Property-level drift (unexpected property names per event) is caught
  at production runtime: ``posthog_service.capture`` calls
  ``validate_payload`` and logs warnings on mismatch. CI doesn't
  currently grep every call site for property names — that would
  require parsing the codebase. The runtime log is the property-drift
  surface.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.analytics import events


class TestRegistryInvariants:
    def test_every_event_name_is_namespaced(self) -> None:
        """All event names must follow the ``namespace:action`` convention."""
        for spec in events.all_events():
            assert ":" in spec.name, f"event {spec.name!r} is missing a namespace"
            namespace, action = spec.name.split(":", 1)
            assert namespace and action, f"event {spec.name!r} has empty namespace or action"

    def test_every_event_has_a_description(self) -> None:
        for spec in events.all_events():
            assert spec.description, f"event {spec.name!r} has no description"

    def test_every_property_has_a_description(self) -> None:
        for spec in events.all_events():
            for prop_name, prop_desc in spec.properties.items():
                assert prop_desc, f"event {spec.name!r} property {prop_name!r} has no description"

    def test_distinct_id_kind_is_valid(self) -> None:
        valid_kinds = {"workspace", "user", "system"}
        for spec in events.all_events():
            assert spec.distinct_id_kind in valid_kinds, (
                f"event {spec.name!r} has invalid distinct_id_kind {spec.distinct_id_kind!r}"
            )

    def test_no_duplicate_registration(self) -> None:
        """Registering the same name twice must fail loudly."""
        with pytest.raises(ValueError, match="Duplicate event registration"):
            events._register(
                events.EventSpec(
                    name="team:member_invited",  # already registered
                    description="dup",
                    distinct_id_kind="workspace",
                )
            )


class TestGetSpec:
    def test_known_event_returns_spec(self) -> None:
        spec = events.get_spec("team:member_invited")
        assert spec is not None
        assert spec.name == "team:member_invited"
        assert spec.distinct_id_kind == "workspace"
        assert "role" in spec.properties

    def test_unknown_event_returns_none(self) -> None:
        assert events.get_spec("definitely:not_real") is None


class TestValidatePayload:
    def test_known_event_with_no_properties(self) -> None:
        warnings = events.validate_payload("team:branding_updated", None)
        assert warnings == []

    def test_known_event_with_expected_properties(self) -> None:
        warnings = events.validate_payload(
            "team:member_invited",
            {"role": "admin", "invited_email_domain": "example.com"},
        )
        assert warnings == []

    def test_known_event_with_subset_of_properties_is_fine(self) -> None:
        """Omitted properties are intentionally not flagged."""
        warnings = events.validate_payload("team:member_invited", {"role": "admin"})
        assert warnings == []

    def test_known_event_with_unexpected_property_warns(self) -> None:
        warnings = events.validate_payload(
            "team:member_invited",
            {"role": "admin", "secret_pii": "oops"},
        )
        assert len(warnings) == 1
        assert "secret_pii" in warnings[0]
        assert "team:member_invited" in warnings[0]

    def test_unknown_event_warns(self) -> None:
        warnings = events.validate_payload("never:registered", {})
        assert len(warnings) == 1
        assert "not in the registry" in warnings[0]

    def test_empty_properties_dict_is_fine(self) -> None:
        warnings = events.validate_payload("team:branding_updated", {})
        assert warnings == []


class TestCoverageOfShippedEvents:
    """Every event name fired in production code must be in the registry.

    The list below is the canonical set; if a new ``capture(...)`` call
    site ships a name not here, register it in events.py and add it to
    this list. This is the drift-detection that justifies the registry's
    existence.
    """

    SHIPPED_EVENTS = {
        # team:*
        "team:member_invited",
        "team:member_invitation_accepted",
        "team:member_removed",
        "team:role_changed",
        "team:branding_updated",
        "team:custom_domain_added",
        # api_token:*
        "api_token:created",
        "api_token:deleted",
        # product/component/release/item:*
        "product:created",
        "component:created",
        "component:first_created",
        "release:created",
        "item:visibility_toggled",
        # sbom/document:*
        "sbom:uploaded",
        "sbom:downloaded",
        "document:uploaded",
        "bom_artifact:first_uploaded",
        # trust-center:*
        "document:access_requested",
        "document:access_approved",
        "document:access_denied",
        "nda:signed",
        # search:*
        "search:performed",
        # user:*
        "user:signed_up",
        "user:account_deleted",
        # onboarding:*
        "onboarding:wizard_completed",
        # billing:*
        "billing:trial_expired",
        "billing:subscription_updated",
        "billing:subscription_canceled",
        "billing:payment_failed",
        "billing:payment_succeeded",
        "billing:checkout_completed",
        "billing:enterprise_contact_submitted",
        # vulnerability_scanning:*
        "vulnerability_scan:initiated",
        "vulnerability_scan:completed",
    }

    def test_every_shipped_event_is_registered(self) -> None:
        unregistered = sorted(name for name in self.SHIPPED_EVENTS if events.get_spec(name) is None)
        assert unregistered == [], (
            f"These events are fired in production but missing from the registry: {unregistered}. "
            "Register them in sbomify/apps/core/analytics/events.py."
        )

    def test_no_registered_events_outside_shipped_list(self) -> None:
        """Catches the inverse: a registered event that no code actually fires.

        Either remove the registration or add the call site. This stops
        the registry from becoming a graveyard of speculative events.
        """
        registered = {spec.name for spec in events.all_events()}
        extra = sorted(registered - self.SHIPPED_EVENTS)
        assert extra == [], (
            f"These events are registered but not in SHIPPED_EVENTS: {extra}. "
            "Either remove them from events.py or add a call site + update this test."
        )
