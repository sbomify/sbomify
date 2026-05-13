"""Tests for the public Declaration of Conformity view.

Gating matrix the view enforces:

| product.is_public | assessment.status | DoC generated | is_stale | result |
| ----------------- | ----------------- | ------------- | -------- | ------ |
| True              | complete          | yes           | False    | 200    |
| False             | complete          | yes           | False    | 404    |
| True              | in_progress       | yes           | False    | 404    |
| True              | complete          | no            | -        | 404    |
| True              | complete          | yes           | True     | 404    |
| any               | (no assessment)   | -             | -        | 404    |

The DoC must only surface when every gate passes; partial / draft
assessments, missing documents, and stale documents must all 404 to
keep the trust-center declaration authoritative.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAGeneratedDocument,
    CRAScopeScreening,
    OSCALAssessmentResult,
    OSCALCatalog,
)
from sbomify.apps.core.models import Product

pytestmark = pytest.mark.django_db


_DOC_MARKDOWN = """\
# EU DECLARATION OF CONFORMITY

## 1. Product Identification

- **Name:** Lithium Python Stack
- **Unique Identifier:** 640053c0-8ca7-42a0-8401-fe4b6c7dbaaf
"""


@pytest.fixture
def public_product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="DoC Public Test Product", team=team, is_public=True)


@pytest.fixture
def private_product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="DoC Private Test Product", team=team, is_public=False)


def _make_assessment(product, *, status: str) -> CRAAssessment:
    """Build a minimal CRA assessment in the requested status.

    The DoC public view only inspects ``product``, ``status``, and the
    presence of a generated document — wizard step state is irrelevant
    here, so we keep the fixture chain tight.
    """
    team = product.team
    CRAScopeScreening.objects.create(
        product=product,
        team=team,
        has_data_connection=True,
    )
    catalog = OSCALCatalog.objects.create(
        name="BSI TR-03183-1",
        version="1.0",
        catalog_json={"metadata": {"title": "stub"}},
    )
    oscal_result = OSCALAssessmentResult.objects.create(
        catalog=catalog,
        team=team,
        title="DoC Test OSCAL Result",
    )
    return CRAAssessment.objects.create(
        team=team,
        product=product,
        oscal_assessment_result=oscal_result,
        status=status,
    )


def _attach_doc(assessment: CRAAssessment) -> CRAGeneratedDocument:
    return CRAGeneratedDocument.objects.create(
        assessment=assessment,
        document_kind=CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY,
        storage_key=f"compliance/{assessment.id}/declaration_of_conformity.md",
        content_hash="0" * 64,
    )


def _stub_s3_get_document(content: str = _DOC_MARKDOWN):
    """Patch ``S3Client.get_document_data`` so the view does not hit real S3."""
    return patch(
        "sbomify.apps.core.object_store.S3Client.get_document_data",
        return_value=content.encode("utf-8"),
    )


class TestProductDoCPublicView:
    def test_renders_when_public_complete_and_doc_present(self, public_product):
        assessment = _make_assessment(public_product, status=CRAAssessment.WizardStatus.COMPLETE)
        _attach_doc(assessment)

        with _stub_s3_get_document():
            response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "EU Declaration of Conformity" in body
        # Body of the rendered DoC ends up in the template's content area.
        assert "Lithium Python Stack" in body

    def test_404_when_product_is_private(self, private_product):
        assessment = _make_assessment(private_product, status=CRAAssessment.WizardStatus.COMPLETE)
        _attach_doc(assessment)

        with _stub_s3_get_document():
            response = Client().get(
                reverse("compliance:product_doc_public", kwargs={"product_id": private_product.id})
            )

        assert response.status_code == 404

    def test_404_when_assessment_not_complete(self, public_product):
        assessment = _make_assessment(public_product, status=CRAAssessment.WizardStatus.IN_PROGRESS)
        _attach_doc(assessment)

        with _stub_s3_get_document():
            response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 404

    def test_404_when_doc_not_generated(self, public_product):
        _make_assessment(public_product, status=CRAAssessment.WizardStatus.COMPLETE)
        # Deliberately NOT calling _attach_doc.

        response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 404

    def test_404_when_no_assessment_at_all(self, public_product):
        # Product has no CRA assessment.
        response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 404

    def test_404_when_unknown_product(self):
        response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": "nonexistent"}))

        assert response.status_code == 404

    def test_404_when_s3_returns_empty(self, public_product):
        assessment = _make_assessment(public_product, status=CRAAssessment.WizardStatus.COMPLETE)
        _attach_doc(assessment)

        with patch(
            "sbomify.apps.core.object_store.S3Client.get_document_data",
            return_value=None,
        ):
            response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 404

    def test_404_when_doc_is_stale(self, public_product):
        """A DoC marked stale by the staleness system is no longer
        authoritative — the public reader must not surface it even
        though the assessment is otherwise complete."""
        assessment = _make_assessment(public_product, status=CRAAssessment.WizardStatus.COMPLETE)
        doc = _attach_doc(assessment)
        doc.is_stale = True
        doc.save(update_fields=["is_stale"])

        with _stub_s3_get_document():
            response = Client().get(reverse("compliance:product_doc_public", kwargs={"product_id": public_product.id}))

        assert response.status_code == 404


class TestInlineMarkupEdgeCases:
    """Regression tests for ``inline_markup`` glitches surfaced by the DoC.

    The DoC has more Markdown metacharacters than the VDP did (glob
    patterns inside code spans, ``***`` thematic breaks), and they
    exposed pre-existing rendering bugs that this PR fixes.
    """

    def test_asterisk_inside_code_span_is_preserved(self):
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup("- `sboms/*.cdx.json` — Software Bill of Materials")

        # Whole code span survives; the italic regex must not eat the asterisk.
        assert "<code>sboms/*.cdx.json</code>" in out
        # And no stray closing tag.
        assert "<em>" not in out

    def test_italic_outside_code_span_still_renders(self):
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup("text (*Annex I Part II(1)*)")

        assert "<em>Annex I Part II(1)</em>" in out

    def test_thematic_break_with_stars(self):
        from sbomify.apps.compliance.views._public_helpers import markdown_to_html

        out = markdown_to_html("paragraph\n\n***\n\nnext paragraph")

        # *** must render as <hr>, not as literal text.
        assert "<hr>" in out
        assert "***" not in out

    def test_thematic_break_with_underscores(self):
        from sbomify.apps.compliance.views._public_helpers import markdown_to_html

        out = markdown_to_html("a\n\n___\n\nb")

        assert "<hr>" in out
        assert "___" not in out
