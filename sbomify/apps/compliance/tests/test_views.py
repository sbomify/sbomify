"""Tests for CRA wizard views."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.compliance.models import CRAScopeScreening
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _disable_billing(settings):
    settings.BILLING = False


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="View Test Product", team=team)


@pytest.fixture
def scope_screening(sample_team_with_owner_member, sample_user, product):
    """CRA scope screening that confirms CRA applies — required before starting assessment."""
    return CRAScopeScreening.objects.create(
        product=product,
        team=sample_team_with_owner_member.team,
        has_data_connection=True,
        is_own_use_only=False,
        is_testing_version=False,
        is_covered_by_other_legislation=False,
        created_by=sample_user,
    )


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product, scope_screening):
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.fixture
def web_client(sample_team_with_owner_member, sample_user):
    """Authenticated web client with session."""
    client = Client()
    client.force_login(sample_user)
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    return client


class TestCRAProductListView:
    def test_unauthenticated_redirects_to_login(self):
        client = Client()
        url = reverse("compliance:cra_product_list")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login" in response.url or "/accounts/login" in response.url

    def test_authenticated_returns_200(self, web_client):
        url = reverse("compliance:cra_product_list")
        response = web_client.get(url)
        assert response.status_code == 200

    def test_lists_assessments(self, web_client, assessment):
        url = reverse("compliance:cra_product_list")
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"View Test Product" in response.content

    def test_empty_state_when_no_assessments(self, web_client):
        url = reverse("compliance:cra_product_list")
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"No CRA Assessments" in response.content


class TestCRAWizardShellView:
    def test_redirects_to_current_step(self, web_client, assessment):
        url = reverse("compliance:cra_wizard_shell", kwargs={"assessment_id": assessment.id})
        response = web_client.get(url)
        assert response.status_code == 302
        assert f"/step/{assessment.current_step}/" in response.url

    def test_nonexistent_assessment_returns_404(self, web_client):
        url = reverse("compliance:cra_wizard_shell", kwargs={"assessment_id": "nonexistent99"})
        response = web_client.get(url)
        assert response.status_code == 404

    def test_unauthenticated_redirects(self):
        client = Client()
        url = reverse("compliance:cra_wizard_shell", kwargs={"assessment_id": "test123"})
        response = client.get(url)
        assert response.status_code == 302


class TestCRAStepView:
    def test_renders_step_1(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 1})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"Product Profile" in response.content

    def test_renders_step_2(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 2})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"SBOM Compliance" in response.content

    def test_renders_step_3(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 3})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"Security" in response.content

    def test_renders_step_4(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 4})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"User Information" in response.content

    def test_renders_step_5(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 5})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"Review" in response.content

    def test_invalid_step_returns_404(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 99})
        response = web_client.get(url)
        assert response.status_code == 404

    def test_nonexistent_assessment_returns_404(self, web_client):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": "nonexistent99", "step": 1})
        response = web_client.get(url)
        assert response.status_code == 404

    def test_unauthenticated_redirects(self):
        client = Client()
        url = reverse("compliance:cra_step", kwargs={"assessment_id": "test123", "step": 1})
        response = client.get(url)
        assert response.status_code == 302

    def test_step_context_contains_step_data(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 1})
        response = web_client.get(url)
        assert response.status_code == 200
        # json_script embeds data as a script tag with id "step-data"
        assert b'id="step-data"' in response.content
        assert b'id="assessment-meta"' in response.content

    def test_stepper_shows_in_template(self, web_client, assessment):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": 1})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"Wizard progress" in response.content


class TestCRAStartAssessmentView:
    def test_creates_assessment_and_redirects(self, web_client, product, scope_screening):
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = web_client.post(url)
        assert response.status_code == 302
        assert "/step/1/" in response.url
        # Verify assessment was created
        from sbomify.apps.compliance.models import CRAAssessment

        assert CRAAssessment.objects.filter(product=product).exists()

    def test_redirects_to_screening_when_no_screening(self, web_client, product):
        """Without scope screening, redirects to scope screening page."""
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = web_client.post(url)
        assert response.status_code == 302
        assert "/scope/" in response.url

    def test_returns_existing_assessment(self, web_client, assessment):
        """If assessment already exists, still redirects to step 1."""
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": assessment.product_id})
        response = web_client.post(url)
        assert response.status_code == 302
        assert "/step/1/" in response.url

    def test_nonexistent_product_returns_404(self, web_client):
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": "nonexistent99"})
        response = web_client.post(url)
        assert response.status_code == 404

    def test_get_method_not_allowed(self, web_client, product):
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = web_client.get(url)
        assert response.status_code == 405  # Method Not Allowed

    def test_unauthenticated_redirects(self):
        client = Client()
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": "test123"})
        response = client.post(url)
        assert response.status_code == 302


class TestCRAScopeScreeningView:
    def test_get_renders_screening_page(self, web_client, product):
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"CRA Scope Screening" in response.content

    def test_get_loads_existing_screening(self, web_client, product, scope_screening):
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b"screening-data" in response.content

    def test_post_creates_screening_cra_applies(self, web_client, product):
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.post(
            url,
            data='{"has_data_connection": true, "is_own_use_only": false, "is_testing_version": false, '
            '"is_covered_by_other_legislation": false, "is_dual_use": false, "screening_notes": ""}',
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cra_applies"] is True
        assert "redirect" in data
        assert CRAScopeScreening.objects.filter(product=product).exists()

    def test_post_creates_screening_cra_not_applies(self, web_client, product):
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.post(
            url,
            data='{"has_data_connection": false, "is_own_use_only": false, "is_testing_version": false, '
            '"is_covered_by_other_legislation": false, "is_dual_use": false, "screening_notes": ""}',
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cra_applies"] is False

    def test_post_nonexistent_product_returns_404(self, web_client):
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": "nonexistent99"})
        response = web_client.post(
            url,
            data='{"has_data_connection": true}',
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_post_rejects_oversized_screening_notes(self, web_client, product):
        """Length cap on ``screening_notes`` (P1, CWE-400). Without
        this cap, a 1 MB blob would bloat the regulated-data row and
        stall JSON serialisation on every subsequent GET."""
        import json as _json

        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.post(
            url,
            data=_json.dumps(
                {
                    "has_data_connection": True,
                    "is_own_use_only": False,
                    "is_testing_version": False,
                    "is_covered_by_other_legislation": False,
                    "is_dual_use": False,
                    "screening_notes": "x" * 10_000,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert b"screening_notes" in response.content or b"cap" in response.content

    def test_post_rejects_oversized_legislation_name(self, web_client, product):
        """``exempted_legislation_name`` is ``CharField(255)`` — reject
        before the DB layer so we get a clean 400 instead of a 500."""
        import json as _json

        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.post(
            url,
            data=_json.dumps(
                {
                    "has_data_connection": True,
                    "is_own_use_only": False,
                    "is_covered_by_other_legislation": True,
                    "exempted_legislation_name": "x" * 500,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_post_emits_audit_log(self, web_client, product):
        """Scope-screening writes flip the ``cra_applies`` premise of
        every subsequent DoC. CRA non-repudiation depends on recording
        who made the change. The audit logger records structured
        before/after deltas the moment the screening is saved."""
        import json as _json
        import logging as _logging

        records: list[_logging.LogRecord] = []

        class _ListHandler(_logging.Handler):
            def emit(self, record: _logging.LogRecord) -> None:
                records.append(record)

        handler = _ListHandler(level=_logging.INFO)
        audit_logger = _logging.getLogger("sbomify.compliance.audit")
        audit_logger.addHandler(handler)
        try:
            url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
            response = web_client.post(
                url,
                data=_json.dumps(
                    {
                        "has_data_connection": True,
                        "is_own_use_only": False,
                        "is_testing_version": False,
                        "is_covered_by_other_legislation": False,
                        "is_dual_use": False,
                        "screening_notes": "Initial scope determination",
                    }
                ),
                content_type="application/json",
            )
            assert response.status_code == 200
        finally:
            audit_logger.removeHandler(handler)

        assert records, "expected scope-screening audit record"
        event = records[-1]
        assert event.getMessage().startswith("cra.scope_screening.write")
        assert getattr(event, "product_id", None) == product.id
        delta = getattr(event, "delta", {})
        assert "has_data_connection" in delta or "screening_notes" in delta

    def test_post_caps_non_string_legislation_name(self, web_client, product):
        """A non-string ``exempted_legislation_name`` (list/dict/number)
        bypasses the ``isinstance(x, str)`` guard, but the subsequent
        ``str(...).strip()`` coercion can still materialise an
        arbitrarily large string in the DB. Check the coerced length so
        we reject those payloads at the edge too."""
        import json as _json

        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.post(
            url,
            data=_json.dumps(
                {
                    "has_data_connection": True,
                    "is_covered_by_other_legislation": True,
                    # 400+ items joined via ``str(...)`` produces a repr
                    # string well above the 255 cap without ever passing
                    # through ``isinstance(raw, str)``.
                    "exempted_legislation_name": ["x" * 80] * 10,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_get_passes_server_resolved_urls(self, web_client, product):
        """Scope-screening page must carry server-resolved save +
        start-assessment URLs in a ``screening-urls`` json_script so
        the JS doesn't fall back to ``window.location.href`` — which
        would inherit whatever Host header the request arrived with
        (P1 host-header open-redirect amplifier)."""
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        response = web_client.get(url)
        assert response.status_code == 200
        assert b'id="screening-urls"' in response.content
        expected_save_url = reverse("compliance:cra_scope_screening", kwargs={"product_id": product.id})
        assert expected_save_url.encode() in response.content

    def test_unauthenticated_redirects(self):
        client = Client()
        url = reverse("compliance:cra_scope_screening", kwargs={"product_id": "test123"})
        response = client.get(url)
        assert response.status_code == 302

    def test_start_assessment_returns_400_when_cra_not_applies(self, web_client, product, sample_user):
        """CRAStartAssessmentView returns 400 when screening exists but CRA doesn't apply."""
        CRAScopeScreening.objects.create(
            product=product,
            team=product.team,
            has_data_connection=False,
            is_own_use_only=False,
            is_testing_version=False,
            is_covered_by_other_legislation=False,
            created_by=sample_user,
        )
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = web_client.post(url)
        assert response.status_code == 400

    def test_start_assessment_redirects_to_scope_screening_when_missing(self, web_client, product):
        """The scope-screening gate (FAQ Section 1) must force the user
        through scope determination before an assessment can be created.
        Without this redirect, a direct POST to ``/start/`` could bypass
        the pre-wizard applicability check and land the team on an
        assessment whose CRA applicability was never evaluated."""
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = web_client.post(url)
        assert response.status_code == 302
        assert "/cra/scope/" in (response.get("Location") or "")


class TestBillingGateViews:
    """Test that billing gate blocks access when BILLING is enabled."""

    @pytest.fixture(autouse=True)
    def _enable_billing(self, settings):
        """Override the module-level _disable_billing for this class."""
        settings.BILLING = True

    def test_product_list_accessible_with_business_plan(self, sample_user, team_with_business_plan):
        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team_with_business_plan, sample_user)
        url = reverse("compliance:cra_product_list")
        response = client.get(url)
        assert response.status_code == 200

    def test_start_assessment_blocked_on_community_plan(self, sample_user, team_with_community_plan):
        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team_with_community_plan, sample_user)
        product = Product.objects.create(name="Billing Test Product", team=team_with_community_plan)
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product.id})
        response = client.post(url)
        assert response.status_code == 403

    def test_step_view_blocked_on_community_plan(self, sample_user, team_with_community_plan, settings):
        from django.test import override_settings

        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment

        product = Product.objects.create(name="Billing Gate Product", team=team_with_community_plan)
        # Create assessment with billing disabled using override_settings
        with override_settings(BILLING=False):
            result = get_or_create_assessment(product.id, sample_user, team_with_community_plan)
        assert result.ok
        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team_with_community_plan, sample_user)
        url = reverse("compliance:cra_step", kwargs={"assessment_id": result.value.id, "step": 1})
        response = client.get(url)
        assert response.status_code == 403
