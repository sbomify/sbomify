import pytest

from sbomify.apps.core.services.querysets import (
    optimize_component_queryset,
    optimize_product_queryset,
)


@pytest.mark.django_db
def test_optimize_component_queryset_annotations(sample_team):
    from sbomify.apps.core.models import Component
    from sbomify.apps.sboms.models import SBOM

    component = Component.objects.create(name="Component A", team=sample_team)
    SBOM.objects.create(name="SBOM A", component=component, version="1.0.0")
    SBOM.objects.create(name="SBOM B", component=component, version="2.0.0")

    optimized = optimize_component_queryset(Component.objects.filter(id=component.id)).first()
    assert optimized is not None
    assert optimized.sbom_count == 2


@pytest.mark.django_db
def test_optimize_product_queryset_annotations(sample_team):
    from sbomify.apps.core.models import Component, Product

    product = Product.objects.create(name="Product A", team=sample_team)
    component = Component.objects.create(name="Component A", team=sample_team)
    product.components.add(component)

    optimized = optimize_product_queryset(Product.objects.filter(id=product.id)).first()
    assert optimized is not None
    assert optimized.component_count == 1


@pytest.mark.django_db
def test_optimize_product_queryset_prefetches(sample_team, django_assert_num_queries):
    from sbomify.apps.core.models import Component, Product
    from sbomify.apps.sboms.models import ProductIdentifier, ProductLink

    product = Product.objects.create(name="Product A", team=sample_team)
    component = Component.objects.create(name="Component A", team=sample_team)
    product.components.add(component)
    ProductIdentifier.objects.create(product=product, identifier_type="cpe", value="cpe:2.3:a:test:1")
    ProductLink.objects.create(product=product, link_type="website", title="Homepage", url="https://example.com")

    with django_assert_num_queries(4):
        products = list(optimize_product_queryset(Product.objects.filter(id=product.id)))
        for item in products:
            list(item.components.all())
            list(item.identifiers.all())
            list(item.links.all())
