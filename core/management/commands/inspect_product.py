from django.core.management.base import BaseCommand

from core.models import Component
from sboms.models import Product


class Command(BaseCommand):
    help = "Inspect a product's relationships and document connections"

    def add_arguments(self, parser):
        parser.add_argument("product_id", type=str, help="Product ID to inspect")

    def handle(self, *args, **options):
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

        # Check product links
        links = product.links.all()
        self.stdout.write(f"📎 Product Links: {links.count()}")
        for link in links:
            self.stdout.write(f"  - {link.get_link_type_display()}: {link.url}")
        self.stdout.write("")

        # Check projects associated with this product
        projects = product.projects.all()
        self.stdout.write(f"📂 Projects: {projects.count()}")
        for project in projects:
            self.stdout.write(f"  - {project.name} (ID: {project.id}, Public: {project.is_public})")

            # Check components in this project
            components = project.components.all()
            self.stdout.write(f"    📦 Components: {components.count()}")

            for component in components:
                self.stdout.write(
                    f"      - {component.name} (Type: {component.component_type}, Public: {component.is_public})"
                )

                # If it's a document component, check its documents
                if component.component_type == "document":
                    documents = component.document_set.all()
                    self.stdout.write(f"        📄 Documents: {documents.count()}")
                    for doc in documents:
                        self.stdout.write(f"          - {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        # Check document components using the old method (all team document components)
        old_method_docs = product.team.component_set.filter(component_type="document", is_public=True)
        self.stdout.write(f"🔍 Old Method - Document Components in Team: {old_method_docs.count()}")
        for component in old_method_docs:
            self.stdout.write(f"  - {component.name} (ID: {component.id})")
            documents = component.document_set.all()
            for doc in documents:
                self.stdout.write(f"    📄 {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        # Check document components using the new method (through product-project relationship)
        new_method_docs = Component.objects.filter(
            component_type="document", is_public=True, projects__products=product
        ).distinct()
        self.stdout.write(f"🔍 New Method - Document Components via Product-Project: {new_method_docs.count()}")
        for component in new_method_docs:
            self.stdout.write(f"  - {component.name} (ID: {component.id})")
            documents = component.document_set.all()
            for doc in documents:
                self.stdout.write(f"    📄 {doc.name} (Type: {doc.document_type})")
        self.stdout.write("")

        # Test external references generation
        self.stdout.write("🔗 Testing External References Generation...")
        try:
            from sboms.utils import create_product_external_references

            external_refs = create_product_external_references(product, user=None)
            self.stdout.write(f"Generated {len(external_refs)} external references:")

            for i, ref in enumerate(external_refs):
                ref_type = getattr(ref, "type", "unknown")
                ref_url = getattr(ref, "url", "unknown")
                ref_comment = getattr(ref, "comment", None)
                self.stdout.write(f"  {i+1}. Type: {ref_type}, URL: {ref_url}")
                if ref_comment:
                    self.stdout.write(f"     Comment: {ref_comment}")

        except ImportError:
            self.stdout.write("❌ CycloneDX not available - cannot test external references")
        except Exception as e:
            self.stdout.write(f"❌ Error generating external references: {e}")

        self.stdout.write("")
        self.stdout.write("=== Analysis Complete ===")

        # Provide recommendations
        if new_method_docs.count() == 0 and old_method_docs.count() > 0:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  ISSUE FOUND: Document components exist in the team but are not "
                    "connected to the product via projects"
                )
            )
            self.stdout.write("💡 To fix this, you need to:")
            self.stdout.write("   1. Create a project for this product (if none exists)")
            self.stdout.write("   2. Associate document components with that project")
            self.stdout.write("   3. Ensure the project is associated with the product")
