"""The EU-representation block, from the review of the PR that added it.

Four things it did not do: the wizard had no inputs for the fields, an
unanswered determination published cleanly, the Art. 22 gate refused every
later Step 1 save once "not established" was recorded, and the changes never
reached the audit trail these fields exist to feed.
"""

from __future__ import annotations

import datetime

import pytest

from sbomify.apps.compliance.services.wizard_service import (
    get_or_create_assessment,
    get_step_context,
    save_step_data,
)
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user):
    """A fresh assessment with a real manufacturer configured.

    Step 1 refuses to complete against a placeholder manufacturer name, so the
    entity has to exist before any of these saves.
    """
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    ContactEntity.objects.create(
        profile=profile,
        name="Acme Labs GmbH",
        email="legal@acmelabs.example",
        is_manufacturer=True,
    )
    product = Product.objects.create(name="CRA Review Product", team=team)
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.mark.django_db
class TestTheStepCarriesTheFields:
    """Blocker 1: the fields were reachable only by calling the API directly."""

    def test_step_1_data_includes_the_block(self, assessment):
        result = get_step_context(assessment, 1)

        assert result.ok
        for field in (
            "is_eu_established",
            "authorized_rep_name",
            "authorized_rep_address",
            "authorized_rep_email",
            "authorized_rep_mandate_date",
            "authorized_rep_mandate_reference",
        ):
            assert field in result.value, field

    def test_an_unanswered_determination_stays_null(self, assessment):
        """Not coerced to False. "Not asked" and "answered no" carry different
        obligations, and only the second one requires a representative."""
        result = get_step_context(assessment, 1)

        assert result.value["is_eu_established"] is None


@pytest.mark.django_db
class TestTheGateOnlyFiresOnItsOwnFields:
    """Finding 3: the gate read the whole assessment on every Step 1 save.

    Once "not established" was recorded without a representative, editing any
    other Step 1 field was refused with an Art. 22 error about fields the
    payload never mentioned — and the block could not be edited back into a
    valid state through the wizard.
    """

    def test_an_unrelated_save_is_not_refused(self, assessment, sample_user):
        assessment.is_eu_established = False
        assessment.save(update_fields=["is_eu_established"])

        result = save_step_data(assessment, 1, {"intended_use": "Industrial gateway"}, sample_user)

        assert result.ok, result.error
        assessment.refresh_from_db()
        assert assessment.intended_use == "Industrial gateway"

    def test_touching_the_block_is_still_refused_when_incomplete(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"is_eu_established": False}, sample_user)

        assert not result.ok
        assert "Authorized Representative" in (result.error or "")

    def test_a_complete_block_saves(self, assessment, sample_user):
        result = save_step_data(
            assessment,
            1,
            {
                "is_eu_established": False,
                "authorized_rep_name": "EU Rep GmbH",
                "authorized_rep_address": "Musterstrasse 1, Berlin",
                "authorized_rep_email": "rep@example.eu",
                "authorized_rep_mandate_date": "2026-01-15",
            },
            sample_user,
        )

        assert result.ok, result.error
        assessment.refresh_from_db()
        assert assessment.authorized_rep_name == "EU Rep GmbH"
        assert assessment.authorized_rep_mandate_date == datetime.date(2026, 1, 15)


@pytest.mark.django_db
class TestTheEmailIsValidated:
    """Nit: EmailField only validates under full_clean(), which this path skips,
    so a malformed address reached the database and the signed declaration."""

    def test_a_malformed_address_is_refused(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"authorized_rep_email": "not-an-email"}, sample_user)

        assert not result.ok
        assert "valid email" in (result.error or "")

    def test_an_empty_address_is_allowed(self, assessment, sample_user):
        """Clearing the field is not the same as filling it in badly."""
        result = save_step_data(assessment, 1, {"authorized_rep_email": ""}, sample_user)

        assert result.ok, result.error


@pytest.mark.django_db
class TestTheChangesAreAudited:
    """Finding 4: these fields exist to be legal evidence, so a change to them
    is the thing most worth having in the diff."""

    def test_the_block_appears_in_the_audit_snapshot(self):
        from sbomify.apps.compliance.services.wizard_service import _AUDITED_STEP_FIELDS

        audited = set(_AUDITED_STEP_FIELDS[1])

        assert {
            "is_eu_established",
            "authorized_rep_name",
            "authorized_rep_address",
            "authorized_rep_email",
            "authorized_rep_mandate_date",
            "authorized_rep_mandate_reference",
        } <= audited


@pytest.mark.django_db
class TestTheDeclarationSaysWhenItCannotSay:
    """Blocker 2, document half: the template branch required
    ``authorized_rep_required``, which needs ``is_eu_established is False``.
    An unanswered determination rendered no section 2a at all, which reads as
    though no representative was needed."""

    def test_the_context_distinguishes_unanswered_from_not_required(self, assessment):
        from sbomify.apps.compliance.services.document_generation_service import _build_common_context

        assessment.is_eu_established = None
        context = _build_common_context(assessment)
        assert context["eu_establishment_unanswered"] is True
        assert context["authorized_rep_required"] is False

        assessment.is_eu_established = True
        context = _build_common_context(assessment)
        assert context["eu_establishment_unanswered"] is False
        assert context["authorized_rep_required"] is False
