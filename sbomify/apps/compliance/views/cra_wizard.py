"""CRA Wizard step views — one CBV per step URL."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.compliance.models import CRAAssessment, CRAScopeScreening
from sbomify.apps.compliance.permissions import check_cra_access
from sbomify.apps.core.utils import verify_item_access

_STEP_NAMES = {
    1: "Product Profile",
    2: "SBOM Compliance",
    3: "Security & Vulnerability",
    4: "User Information",
    5: "Review & Export",
}

_STEP_TEMPLATES = {
    1: "compliance/cra_step_1.html.j2",
    2: "compliance/cra_step_2.html.j2",
    3: "compliance/cra_step_3.html.j2",
    4: "compliance/cra_step_4.html.j2",
    5: "compliance/cra_step_5.html.j2",
}


def _get_assessment(request: HttpRequest, assessment_id: str) -> CRAAssessment | HttpResponse:
    """Fetch assessment with access checks. Returns assessment or error response."""
    from sbomify.apps.compliance.services.wizard_service import get_assessment_by_id

    result = get_assessment_by_id(assessment_id)
    if not result.ok:
        return HttpResponseNotFound("Not found")

    assessment = result.value
    assert assessment is not None

    if not verify_item_access(request, assessment, ["owner", "admin"]):
        return HttpResponseForbidden("Forbidden")

    if not check_cra_access(assessment.team):
        return HttpResponseForbidden("Forbidden")

    return assessment


class CRAWizardShellView(LoginRequiredMixin, View):
    """Redirects to the current step of the wizard."""

    def get(self, request: HttpRequest, assessment_id: str) -> HttpResponse:
        result = _get_assessment(request, assessment_id)
        if isinstance(result, HttpResponse):
            return result

        step = max(1, min(result.current_step or 1, 5))
        return HttpResponseRedirect(
            reverse("compliance:cra_step", kwargs={"assessment_id": assessment_id, "step": step})
        )


class CRAStepView(LoginRequiredMixin, View):
    """Render a single wizard step."""

    def get(self, request: HttpRequest, assessment_id: str, step: int) -> HttpResponse:
        if step not in _STEP_TEMPLATES:
            return HttpResponseNotFound("Not found")

        result = _get_assessment(request, assessment_id)
        if isinstance(result, HttpResponse):
            return result

        assessment = result

        from sbomify.apps.compliance.services.wizard_service import get_step_context

        ctx = get_step_context(assessment, step)
        if not ctx.ok:
            status = ctx.status_code or 500
            return HttpResponse(ctx.error or "Failed to load step data", status=status)

        # Build step URLs for template use (avoids hardcoded paths in Alpine)
        step_urls = {
            s: reverse("compliance:cra_step", kwargs={"assessment_id": assessment.id, "step": s}) for s in _STEP_NAMES
        }

        step_data = ctx.value or {}
        context = {
            "assessment": assessment,
            "assessment_id": assessment.id,
            "assessment_meta": {"id": assessment.id},
            "step": step,
            "step_name": _STEP_NAMES[step],
            "step_data_json": step_data,
            "step_names": _STEP_NAMES,
            "step_urls": step_urls,
            "completed_steps": assessment.completed_steps,
            "current_team": request.session.get("current_team", {}),
            # Step 3: security.txt status for CRA Annex I Part II §5
            "security_txt_enabled": step_data.get("security_txt_enabled", False),
            "team": {"key": assessment.product.team.key},
        }

        return render(request, _STEP_TEMPLATES[step], context)


class CRAScopeScreeningView(LoginRequiredMixin, View):
    """Pre-wizard scope determination: does CRA apply to this product?

    Based on FAQ Section 1 (CRA Art 2-3, Art 21).
    """

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        from sbomify.apps.core.models import Product

        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return HttpResponseNotFound("Not found")

        if not verify_item_access(request, product, ["owner", "admin"]):
            return HttpResponseForbidden("Forbidden")

        if not check_cra_access(product.team):
            return HttpResponseForbidden("Forbidden")

        # If screening already exists, load it so the user can review or update answers
        try:
            screening = CRAScopeScreening.objects.get(product=product)
            screening_data = {
                "has_data_connection": screening.has_data_connection,
                "is_own_use_only": screening.is_own_use_only,
                "is_testing_version": screening.is_testing_version,
                "is_covered_by_other_legislation": screening.is_covered_by_other_legislation,
                "exempted_legislation_name": screening.exempted_legislation_name,
                "is_dual_use": screening.is_dual_use,
                "screening_notes": screening.screening_notes,
                "cra_applies": screening.cra_applies,
            }
        except CRAScopeScreening.DoesNotExist:
            screening_data = {
                "has_data_connection": True,
                "is_own_use_only": False,
                "is_testing_version": False,
                "is_covered_by_other_legislation": False,
                "exempted_legislation_name": "",
                "is_dual_use": False,
                "screening_notes": "",
                "cra_applies": True,
            }

        context = {
            "product": product,
            "screening_data": screening_data,
            "current_team": request.session.get("current_team", {}),
        }
        return render(request, "compliance/cra_scope_screening.html.j2", context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        import json

        from sbomify.apps.core.models import Product, User

        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return HttpResponseNotFound("Not found")

        if not verify_item_access(request, product, ["owner", "admin"]):
            return HttpResponseForbidden("Forbidden")

        if not check_cra_access(product.team):
            return HttpResponseForbidden("Forbidden")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON", status=400)

        user: User = request.user  # type: ignore[assignment]

        def _parse_bool(val: object, default: bool = False) -> bool:
            """Parse a boolean from JSON, handling string representations safely."""
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            if isinstance(val, int):
                return bool(val)
            return default

        screening, created = CRAScopeScreening.objects.get_or_create(
            product=product,
            defaults={
                "team": product.team,
                "created_by": user,
            },
        )
        screening.team = product.team
        screening.has_data_connection = _parse_bool(data.get("has_data_connection"), default=True)
        screening.is_own_use_only = _parse_bool(data.get("is_own_use_only"))
        screening.is_testing_version = _parse_bool(data.get("is_testing_version"))
        screening.is_covered_by_other_legislation = _parse_bool(data.get("is_covered_by_other_legislation"))
        screening.exempted_legislation_name = str(data.get("exempted_legislation_name") or "").strip()
        screening.is_dual_use = _parse_bool(data.get("is_dual_use"))
        screening.screening_notes = str(data.get("screening_notes") or "").strip()
        screening.save()

        if screening.cra_applies:
            start_url = reverse("compliance:cra_start_assessment", kwargs={"product_id": product_id})
            return HttpResponse(
                json.dumps({"cra_applies": True, "redirect": start_url}),
                content_type="application/json",
            )
        else:
            return HttpResponse(
                json.dumps({"cra_applies": False, "reason": "Product is out of CRA scope based on screening answers."}),
                content_type="application/json",
            )


class CRAStartAssessmentView(LoginRequiredMixin, View):
    """Create a CRA assessment and redirect to step 1.

    Requires scope screening to be completed first (FAQ Section 1).
    """

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        from sbomify.apps.core.models import Product

        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return HttpResponseNotFound("Not found")

        if not verify_item_access(request, product, ["owner", "admin"]):
            return HttpResponseForbidden("Forbidden")

        if not check_cra_access(product.team):
            return HttpResponseForbidden("Forbidden")

        # Gate: scope screening must be completed and CRA must apply
        try:
            screening = CRAScopeScreening.objects.get(product=product)
            if not screening.cra_applies:
                return HttpResponse(
                    "CRA does not apply to this product based on scope screening. "
                    "Review the scope screening to update your answers.",
                    status=400,
                )
        except CRAScopeScreening.DoesNotExist:
            return HttpResponseRedirect(reverse("compliance:cra_scope_screening", kwargs={"product_id": product_id}))

        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.models import User

        user: User = request.user  # type: ignore[assignment]
        result = get_or_create_assessment(product_id, user, product.team)
        if not result.ok:
            return HttpResponse(result.error or "Failed to create assessment", status=result.status_code or 500)

        assert result.value is not None
        return HttpResponseRedirect(
            reverse("compliance:cra_step", kwargs={"assessment_id": result.value.id, "step": 1})
        )
