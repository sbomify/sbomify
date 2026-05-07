from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import Product


class Command(BaseCommand):
    help = "Inspect a product's relationships and document connections"

    def add_arguments(self, parser: Any) -> Any:
        parser.add_argument("product_id", type=str, help="Product ID to inspect")

    def handle(self, *args: Any, **options: Any) -> Any:
        product_id = options["product_id"]

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Product {product_id} not found"))
            return

        self.stdout.write(self.style.SUCCESS(f"=== Inspecting Product: {product.name} (ID: {product.id}) ==="))
        self.stdout.write(f"Team: {product.team.name} (ID: {product.team.id})")
        self.stdout.write(f"Is Public: {product.is_public}")
        self.stdout.write("")

        links = product.links.all()
        self.stdout.write(f"📎 Product Links: {links.count()}")
        for link in links:
            self.stdout.write(f"  - {link.get_link_type_display()}: {link.url}")
        self.stdout.write("")

        components = product.components.all().order_by("name")
        self.stdout.write(f"📦 Components: {components.count()}")
        for component in components:
            self.stdout.write(
                f"  - {component.name} (Type: {component.component_type}, Visibility: {component.visibility})"
            )
            if component.component_type == "document":
                documents = component.document_set.all()
                self.stdout.write(f"    📄 Documents: {documents.count()}")
                for doc in documents:
                    self.stdout.write(f"      - {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        team_doc_components = product.team.component_set.filter(
            component_type="document", visibility=Component.Visibility.PUBLIC
        )
        self.stdout.write(f"🔍 Public document components in team: {team_doc_components.count()}")
        for component in team_doc_components:
            self.stdout.write(f"  - {component.name} (ID: {component.id})")
            for doc in component.document_set.all():
                self.stdout.write(f"    📄 {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        product_doc_components = (
            Component.objects.filter(
                component_type="document",
                visibility=Component.Visibility.PUBLIC,
                products=product,
            )
            .order_by("id")
            .distinct()
        )
        self.stdout.write(f"🔍 Public document components attached to product: {product_doc_components.count()}")
        for component in product_doc_components:
            self.stdout.write(f"  - {component.name} (ID: {component.id})")
            for doc in component.document_set.all():
                self.stdout.write(f"    📄 {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        self.stdout.write("🔗 Testing External References Generation...")
        try:
            from sbomify.apps.sboms.utils import create_product_external_references

            external_refs = create_product_external_references(product, user=None)  # type: ignore[arg-type]
            self.stdout.write(f"Generated {len(external_refs)} external references:")

            for i, ref in enumerate(external_refs):
                ref_type = getattr(ref, "type", "unknown")
                ref_url = getattr(ref, "url", "unknown")
                ref_comment = getattr(ref, "comment", None)
                self.stdout.write(f"  {i + 1}. Type: {ref_type}, URL: {ref_url}")
                if ref_comment:
                    self.stdout.write(f"     Comment: {ref_comment}")

        except ImportError:
            self.stdout.write("❌ CycloneDX not available - cannot test external references")
        except Exception as e:
            self.stdout.write(f"❌ Error generating external references: {e}")

        self.stdout.write("")
        self.stdout.write("=== Analysis Complete ===")

        if product_doc_components.count() == 0 and team_doc_components.count() > 0:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  ISSUE FOUND: Document components exist in the team but are not attached to this product"
                )
            )
            self.stdout.write("💡 To fix this, attach the relevant document components to the product directly.")
