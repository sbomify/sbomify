"""Public aggregates must embed only PUBLIC documents (no per-user signed URLs leaked via the
shared cache), and the cache fingerprint must react to document changes."""

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import (
    compute_release_aggregate_fingerprint,
    create_product_external_references,
)


def _doc_component(team, product, visibility):
    comp = Component.objects.create(
        name=f"doc-{visibility}", team=team, visibility=visibility, component_type="document"
    )
    comp.products.add(product)
    return comp


@pytest.mark.django_db
def test_public_product_aggregate_excludes_nonpublic_documents(team_with_business_plan):
    """A public product's aggregate embeds only PUBLIC documents; a private product (authenticated,
    per-user download) embeds all of them."""
    from sbomify.apps.sboms.utils import _get_cyclonedx_model

    if _get_cyclonedx_model() is None:
        pytest.skip("CycloneDX schema unavailable; create_product_external_references returns []")
    team = team_with_business_plan
    product = Product.objects.create(name="P", team=team, is_public=True)
    Document.objects.create(name="pub", component=_doc_component(team, product, Component.Visibility.PUBLIC))
    Document.objects.create(name="priv", component=_doc_component(team, product, Component.Visibility.PRIVATE))

    public_refs = create_product_external_references(product, user=None)
    assert len(public_refs) == 1  # only the PUBLIC document (no links on this product)

    product.is_public = False
    product.save()
    private_refs = create_product_external_references(product, user=None)
    assert len(private_refs) == 2  # both documents for an authenticated private download


@pytest.mark.django_db
def test_fingerprint_reacts_to_public_document_changes(team_with_business_plan):
    """Adding a public document, and changing its content, both bust the aggregate cache key."""
    team = team_with_business_plan
    product = Product.objects.create(name="P2", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1")
    member = Component.objects.create(
        name="m", team=team, visibility=Component.Visibility.PUBLIC, component_type=Component.ComponentType.BOM
    )
    sbom = SBOM.objects.create(name="m", component=member, format="cyclonedx", version="1", sbom_filename="m.json")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)

    fp_before = compute_release_aggregate_fingerprint(release)

    comp = _doc_component(team, product, Component.Visibility.PUBLIC)
    doc = Document.objects.create(name="d", component=comp, content_hash="hash-1")
    fp_after_add = compute_release_aggregate_fingerprint(release)
    assert fp_after_add != fp_before  # adding a public document busts the key

    doc.content_hash = "hash-2"
    doc.save()
    fp_after_change = compute_release_aggregate_fingerprint(release)
    assert fp_after_change != fp_after_add  # a content change busts the key

    # A PRIVATE document must NOT affect the public aggregate's fingerprint.
    priv = _doc_component(team, product, Component.Visibility.PRIVATE)
    Document.objects.create(name="p", component=priv, content_hash="hash-priv")
    assert compute_release_aggregate_fingerprint(release) == fp_after_change


@pytest.mark.django_db
def test_public_product_spdx_aggregate_excludes_nonpublic_documents(team_with_business_plan):
    """The SPDX external-reference builder scopes documents the same way as the CycloneDX one."""
    from sbomify.apps.sboms.utils import create_product_spdx_external_references

    team = team_with_business_plan
    product = Product.objects.create(name="Pspdx", team=team, is_public=True)
    Document.objects.create(name="pub", component=_doc_component(team, product, Component.Visibility.PUBLIC))
    Document.objects.create(name="priv", component=_doc_component(team, product, Component.Visibility.PRIVATE))

    public_refs = create_product_spdx_external_references(product, user=None)
    assert len(public_refs) == 1  # only the PUBLIC document

    product.is_public = False
    product.save()
    assert len(create_product_spdx_external_references(product, user=None)) == 2
