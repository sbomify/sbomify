"""CRA Wizard step views — one CBV per step URL."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.compliance.models import CRAAssessment
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

        step = result.current_step or 1
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
            return HttpResponse(ctx.error or "Failed to load step data", status=500)

        context = {
            "assessment": assessment,
            "assessment_id": assessment.id,
            "assessment_meta": {"id": assessment.id},
            "step": step,
            "step_name": _STEP_NAMES[step],
            "step_data_json": ctx.value,
            "step_names": _STEP_NAMES,
            "completed_steps": assessment.completed_steps,
            "current_team": request.session.get("current_team", {}),
        }

        return render(request, _STEP_TEMPLATES[step], context)


class CRAStartAssessmentView(LoginRequiredMixin, View):
    """Create a CRA assessment and redirect to step 1."""

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

        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.models import User

        user: User = request.user  # type: ignore[assignment]
        result = get_or_create_assessment(product_id, user, product.team)
        if not result.ok:
            return HttpResponseNotFound("Not found")

        assert result.value is not None
        return HttpResponseRedirect(
            reverse("compliance:cra_step", kwargs={"assessment_id": result.value.id, "step": 1})
        )
