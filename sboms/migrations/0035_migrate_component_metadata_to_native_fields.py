# Generated by Django 5.2.3 on 2025-07-17 10:44

import core.utils
import django.db.models.deletion
from django.db import migrations, models, transaction


@transaction.atomic
def migrate_component_metadata_to_native_fields(apps, schema_editor):
    """
    Migrate component metadata from JSONField to native fields and related models.
    """
    Component = apps.get_model("sboms", "Component")
    ComponentAuthor = apps.get_model("sboms", "ComponentAuthor")
    ComponentSupplierContact = apps.get_model("sboms", "ComponentSupplierContact")
    ComponentLicense = apps.get_model("sboms", "ComponentLicense")

    for component in Component.objects.all():
        metadata = component.metadata or {}

        # Migrate supplier information
        supplier = metadata.get("supplier", {})
        if supplier:
            component.supplier_name = supplier.get("name")
            component.supplier_address = supplier.get("address")

            # Handle supplier URLs - convert string to list if needed
            urls = supplier.get("url", [])
            if isinstance(urls, str):
                urls = [urls]
            component.supplier_url = urls or []

            # Migrate supplier contacts
            contacts = supplier.get("contacts", [])
            for order, contact in enumerate(contacts):
                if isinstance(contact, dict) and contact.get("name"):
                    ComponentSupplierContact.objects.create(
                        component=component,
                        name=contact["name"],
                        email=contact.get("email") or None,
                        phone=contact.get("phone") or None,
                        bom_ref=contact.get("bom_ref") or None,  # Handle bom_ref field
                        order=order,
                    )

        # Migrate authors
        authors = metadata.get("authors", [])
        for order, author in enumerate(authors):
            if isinstance(author, dict) and author.get("name"):
                ComponentAuthor.objects.create(
                    component=component,
                    name=author["name"],
                    email=author.get("email") or None,
                    phone=author.get("phone") or None,
                    bom_ref=author.get("bom_ref") or None,  # Handle bom_ref field
                    order=order,
                )

        # Handle legacy 'author' field (singular) - found in production data
        if "author" in metadata and not authors:  # Only if no standard authors exist
            legacy_author = metadata["author"]
            if isinstance(legacy_author, dict) and legacy_author.get("name"):
                ComponentAuthor.objects.create(
                    component=component,
                    name=legacy_author["name"],
                    email=legacy_author.get("email") or None,
                    phone=legacy_author.get("phone") or None,
                    bom_ref=legacy_author.get("bom_ref") or None,
                    order=0,
                )

        # Handle legacy 'organization' field as supplier - found in production data
        if "organization" in metadata:
            org = metadata["organization"]
            if isinstance(org, dict):
                # Use organization name as supplier name if no supplier name is already set
                if not component.supplier_name and org.get("name"):
                    component.supplier_name = org["name"]

                # Handle organization contact as supplier contact (only if no standard supplier contacts exist)
                org_contact = org.get("contact", {})
                if isinstance(org_contact, dict) and org_contact.get("name"):
                    # Check if we already have supplier contacts from the standard format
                    existing_contacts = ComponentSupplierContact.objects.filter(component=component).count()
                    if existing_contacts == 0:
                        ComponentSupplierContact.objects.create(
                            component=component,
                            name=org_contact["name"],
                            email=org_contact.get("email") or None,
                            phone=org_contact.get("phone") or None,
                            bom_ref=org_contact.get("bom_ref") or None,
                            order=0,
                        )

        # Migrate lifecycle phase
        lifecycle_phase = metadata.get("lifecycle_phase")
        if lifecycle_phase:
            component.lifecycle_phase = lifecycle_phase

        # Migrate licenses
        licenses = metadata.get("licenses", [])
        for order, license_data in enumerate(licenses):
            if isinstance(license_data, str):
                # Check if it's a license expression (contains operators)
                license_operators = ["AND", "OR", "WITH"]
                is_expression = any(f" {op} " in license_data for op in license_operators)

                if is_expression:
                    ComponentLicense.objects.create(
                        component=component,
                        license_type="expression",
                        license_id=license_data,
                        order=order,
                    )
                else:
                    ComponentLicense.objects.create(
                        component=component,
                        license_type="spdx",
                        license_id=license_data,
                        order=order,
                    )
            elif isinstance(license_data, dict):
                # Handle custom licenses
                if "name" in license_data:
                    ComponentLicense.objects.create(
                        component=component,
                        license_type="custom",
                        license_name=license_data["name"],
                        license_url=license_data.get("url"),
                        license_text=license_data.get("text"),
                        bom_ref=license_data.get("bom_ref"),
                        order=order,
                    )
                elif "id" in license_data:
                    # Handle SPDX license objects
                    ComponentLicense.objects.create(
                        component=component,
                        license_type="spdx",
                        license_id=license_data["id"],
                        bom_ref=license_data.get("bom_ref"),
                        order=order,
                    )

        component.save()


@transaction.atomic
def reverse_migrate_component_metadata_to_native_fields(apps, schema_editor):
    """
    Reverse migration - move data back to JSONField from native fields.
    """
    Component = apps.get_model("sboms", "Component")

    for component in Component.objects.all():
        metadata = component.metadata or {}

        # Restore supplier information
        supplier = metadata.get("supplier", {})
        if component.supplier_name or component.supplier_address or component.supplier_url:
            supplier["name"] = component.supplier_name
            supplier["address"] = component.supplier_address
            supplier["url"] = component.supplier_url

            # Restore supplier contacts
            contacts = []
            for contact in component.supplier_contacts.all():
                contact_data = {"name": contact.name}
                if contact.email:
                    contact_data["email"] = contact.email
                if contact.phone:
                    contact_data["phone"] = contact.phone
                if contact.bom_ref:
                    contact_data["bom_ref"] = contact.bom_ref
                contacts.append(contact_data)
            supplier["contacts"] = contacts

            metadata["supplier"] = supplier

        # Restore authors
        authors = []
        for author in component.authors.all():
            author_data = {"name": author.name}
            if author.email:
                author_data["email"] = author.email
            if author.phone:
                author_data["phone"] = author.phone
            if author.bom_ref:
                author_data["bom_ref"] = author.bom_ref
            authors.append(author_data)
        if authors:
            metadata["authors"] = authors

        # Restore lifecycle phase
        if component.lifecycle_phase:
            metadata["lifecycle_phase"] = component.lifecycle_phase

        # Restore licenses
        licenses = []
        for license_obj in component.licenses.all():
            if license_obj.license_type == "spdx":
                licenses.append(license_obj.license_id)
            elif license_obj.license_type == "expression":
                licenses.append(license_obj.license_id)
            elif license_obj.license_type == "custom":
                license_data = {"name": license_obj.license_name}
                if license_obj.license_url:
                    license_data["url"] = license_obj.license_url
                if license_obj.license_text:
                    license_data["text"] = license_obj.license_text
                if license_obj.bom_ref:
                    license_data["bom_ref"] = license_obj.bom_ref
                licenses.append(license_data)
        if licenses:
            metadata["licenses"] = licenses

        # Note: Legacy 'author' and 'organization' fields are not restored in reverse migration
        # as they would be converted to the standard format during forward migration

        component.metadata = metadata
        component.save()


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0034_add_product_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="component",
            name="lifecycle_phase",
            field=models.CharField(
                blank=True,
                choices=[
                    ("design", "Design"),
                    ("pre-build", "Pre-Build"),
                    ("build", "Build"),
                    ("post-build", "Post-Build"),
                    ("operations", "Operations"),
                    ("discovery", "Discovery"),
                    ("decommission", "Decommission"),
                ],
                help_text="The lifecycle phase of the component",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="supplier_address",
            field=models.TextField(
                blank=True, help_text="The address of the supplier", null=True
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="supplier_name",
            field=models.CharField(
                blank=True,
                help_text="The name of the supplier",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="supplier_url",
            field=models.JSONField(default=list, help_text="List of supplier URLs"),
        ),
        migrations.CreateModel(
            name="ComponentAuthor",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=core.utils.generate_id,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="The name of the author", max_length=255
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        help_text="The email address of the author",
                        max_length=254,
                        null=True,
                    ),
                ),
                (
                    "phone",
                    models.CharField(
                        blank=True,
                        help_text="The phone number of the author",
                        max_length=50,
                        null=True,
                    ),
                ),
                (
                    "bom_ref",
                    models.CharField(
                        blank=True,
                        help_text="BOM reference identifier for CycloneDX",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0, help_text="Order of the author in the list"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authors",
                        to="sboms.component",
                    ),
                ),
            ],
            options={
                "db_table": "sboms_component_authors",
                "ordering": ["order", "name"],
                "unique_together": {("component", "name", "email")},
            },
        ),
        migrations.CreateModel(
            name="ComponentSupplierContact",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=core.utils.generate_id,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="The name of the contact", max_length=255
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        help_text="The email address of the contact",
                        max_length=254,
                        null=True,
                    ),
                ),
                (
                    "phone",
                    models.CharField(
                        blank=True,
                        help_text="The phone number of the contact",
                        max_length=50,
                        null=True,
                    ),
                ),
                (
                    "bom_ref",
                    models.CharField(
                        blank=True,
                        help_text="BOM reference identifier for CycloneDX",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0, help_text="Order of the contact in the list"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="supplier_contacts",
                        to="sboms.component",
                    ),
                ),
            ],
            options={
                "db_table": "sboms_component_supplier_contacts",
                "ordering": ["order", "name"],
                "unique_together": {("component", "name", "email")},
            },
        ),
        migrations.CreateModel(
            name="ComponentLicense",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=core.utils.generate_id,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "license_type",
                    models.CharField(
                        choices=[
                            ("spdx", "SPDX License"),
                            ("custom", "Custom License"),
                            ("expression", "License Expression"),
                        ],
                        help_text="Type of license",
                        max_length=10,
                    ),
                ),
                (
                    "license_id",
                    models.CharField(
                        blank=True,
                        help_text="SPDX license ID or expression",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "license_name",
                    models.CharField(
                        blank=True,
                        help_text="Custom license name",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "license_url",
                    models.URLField(
                        blank=True,
                        help_text="Custom license URL",
                        null=True,
                    ),
                ),
                (
                    "license_text",
                    models.TextField(
                        blank=True,
                        help_text="Custom license text",
                        null=True,
                    ),
                ),
                (
                    "bom_ref",
                    models.CharField(
                        blank=True,
                        help_text="BOM reference identifier for CycloneDX",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0, help_text="Order of the license in the list"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="licenses",
                        to="sboms.component",
                    ),
                ),
            ],
            options={
                "db_table": "sboms_component_licenses",
                "ordering": ["order", "license_id"],
            },
        ),
        migrations.RunPython(
            migrate_component_metadata_to_native_fields,
            reverse_migrate_component_metadata_to_native_fields,
        ),
    ]
