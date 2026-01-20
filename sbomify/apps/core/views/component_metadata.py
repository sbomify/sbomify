"""View for component metadata editing with FormSets.

This view provides the entity/contact FormSets for editing custom contact info
on components, using the same forms as contact profiles for true DRY.
"""

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.teams.forms import ContactEntityFormSet, ContactProfileContactFormSet
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact
from sbomify.apps.teams.schemas import ContactProfileContactSchema
from sbomify.apps.teams.views.contact_profiles import ValidationError, _format_formset_errors

logger = logging.getLogger(__name__)


class ComponentMetadataFormView(LoginRequiredMixin, View):
    """View for rendering and handling the component metadata FormSet-based form."""

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        """Render the entity/contact FormSets for editing custom contact info."""
        try:
            component = Component.objects.select_related("contact_profile", "team").get(pk=component_id)
        except Component.DoesNotExist:
            return htmx_error_response("Component not found")

        if not verify_item_access(request, component, ["owner", "admin"]):
            return htmx_error_response("Permission denied")

        # Get or create a component-private profile for editing
        profile = self._get_or_prepare_private_profile(component)

        entities_formset = ContactEntityFormSet(instance=profile, prefix="entities")

        # Attach nested contact formsets to each entity form
        for entity_form in entities_formset:
            entity_instance = entity_form.instance if entity_form.instance.pk is not None else None
            entity_form.contacts_formset = ContactProfileContactFormSet(
                instance=entity_instance, prefix=f"{entity_form.prefix}-contacts"
            )

        return render(
            request,
            "core/components/component_metadata_form.html.j2",
            {
                "component": component,
                "entities_formset": entities_formset,
                "profile": profile,
            },
        )

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        """Handle form submission to save custom contact info."""
        try:
            component = Component.objects.select_related("contact_profile", "team").get(pk=component_id)
        except Component.DoesNotExist:
            return htmx_error_response("Component not found")

        if not verify_item_access(request, component, ["owner", "admin"]):
            return htmx_error_response("Permission denied")

        try:
            self._save_component_profile(request, component)
        except ValidationError as e:
            return htmx_error_response(e.message)
        except Exception as e:
            logger.exception(f"Error saving component metadata: {e}")
            return htmx_error_response(f"Error saving: {str(e)}")

        # Return success with trigger to refresh the metadata display
        return htmx_success_response(
            "Contact information saved successfully",
            triggers={"metadataUpdated": {"componentId": component_id}},
        )

    def _get_or_prepare_private_profile(self, component: Component) -> ContactProfile | None:
        """Get existing private profile or prepare a new one for editing."""
        if component.contact_profile and component.contact_profile.is_component_private:
            return component.contact_profile
        # Return None to indicate a new profile will be created on save
        return None

    def _save_component_profile(self, request: HttpRequest, component: Component) -> ContactProfile:
        """Save the form data to a component-private ContactProfile."""
        from sbomify.apps.teams.apis import _get_team_owner_email

        # Get or create component-private profile
        profile = None
        if component.contact_profile and component.contact_profile.is_component_private:
            profile = component.contact_profile

        entities_formset = ContactEntityFormSet(request.POST, instance=profile, prefix="entities")

        if not entities_formset.is_valid():
            raise ValidationError(_format_formset_errors(entities_formset))

        # Get fallback email from team owner
        fallback_email = _get_team_owner_email(component.team)

        # Process entities and validate
        entities_data = self._process_entity_formset(request, entities_formset, fallback_email, profile)

        # If no entities with data, clean up any existing private profile
        if not entities_data:
            if profile:
                component.contact_profile = None
                component.save()
                profile.delete()
            return None

        # Create or update profile
        if profile is None:
            profile = ContactProfile.objects.create(
                team=component.team,
                name=f"[Private] {component.name}",
                is_default=False,
                is_component_private=True,
            )
            component.contact_profile = profile
            component.save()

        # Clear existing entities and recreate
        profile.entities.all().delete()

        # Create entities and contacts
        for entity_data in entities_data:
            entity = ContactEntity.objects.create(
                profile=profile,
                name=entity_data.get("name", ""),
                email=entity_data.get("email", ""),
                phone=entity_data.get("phone") or "",
                address=entity_data.get("address") or "",
                website_urls=entity_data.get("website_urls") or [],
                is_manufacturer=entity_data.get("is_manufacturer", False),
                is_supplier=entity_data.get("is_supplier", False),
                is_author=entity_data.get("is_author", False),
            )

            for idx, contact_data in enumerate(entity_data.get("contacts", [])):
                ContactProfileContact.objects.create(
                    entity=entity,
                    name=contact_data.name,
                    email=contact_data.email or fallback_email,
                    phone=contact_data.phone or "",
                    order=contact_data.order or idx,
                    is_author=contact_data.is_author,
                    is_security_contact=contact_data.is_security_contact,
                    is_technical_contact=contact_data.is_technical_contact,
                )

        return profile

    def _process_entity_formset(
        self,
        request: HttpRequest,
        formset: ContactEntityFormSet,
        fallback_email: str,
        profile: ContactProfile | None,
    ) -> list[dict]:
        """Process entity formset and return list of entity data dicts."""
        entities_data = []
        manufacturer_count = 0
        supplier_count = 0

        for entity_form in formset:
            if entity_form.cleaned_data.get("DELETE"):
                continue

            name = (entity_form.cleaned_data.get("name") or "").strip()
            email = (entity_form.cleaned_data.get("email") or "").strip()

            # Detect partially filled forms
            has_phone = bool((entity_form.cleaned_data.get("phone") or "").strip())
            has_address = bool((entity_form.cleaned_data.get("address") or "").strip())
            website_urls_value = entity_form.cleaned_data.get("website_urls_text") or []
            if not isinstance(website_urls_value, list):
                website_urls_value = []
            has_websites = bool(website_urls_value)

            contact_prefix = f"{entity_form.prefix}-contacts"
            entity_instance = entity_form.instance

            is_new_instance = (
                getattr(entity_instance._state, "adding", True) if hasattr(entity_instance, "_state") else True
            )

            formset_kwargs = {"prefix": contact_prefix}
            if not is_new_instance:
                formset_kwargs["instance"] = entity_instance
            else:
                formset_kwargs["queryset"] = ContactProfileContactFormSet.model.objects.none()

            contacts_formset = ContactProfileContactFormSet(request.POST, **formset_kwargs)
            contacts_formset.is_valid()

            # Check if any contact has data
            has_contacts = False
            for cf in contacts_formset:
                if not cf.has_changed():
                    continue
                if hasattr(cf, "cleaned_data") and cf.cleaned_data.get("DELETE"):
                    continue
                has_contacts = True
                break

            has_significant_data = has_phone or has_address or has_websites or has_contacts

            # Check for author-only mode
            is_manufacturer = entity_form.cleaned_data.get("is_manufacturer", False)
            is_supplier = entity_form.cleaned_data.get("is_supplier", False)
            is_author = entity_form.cleaned_data.get("is_author", False)
            is_author_only = is_author and not is_manufacturer and not is_supplier

            # Error if form has data but missing required name/email (unless author-only)
            if has_significant_data and not is_author_only and (not name or not email):
                missing = []
                if not name:
                    missing.append("name")
                if not email:
                    missing.append("email")
                raise ValidationError(
                    f"Entity has data but is missing required field(s): {', '.join(missing)}. "
                    "Please complete the entity or remove it."
                )

            # Skip empty forms (but keep if has significant data)
            if not name and not email and not has_significant_data:
                continue

            if not contacts_formset.is_valid():
                entity_name = entity_form.cleaned_data.get("name", "Unknown")
                raise ValidationError(
                    f"Error in contacts for '{entity_name}': {_format_formset_errors(contacts_formset)}"
                )

            contacts_data = []
            for contact_form in contacts_formset:
                contact_data = contact_form.cleaned_data
                if contact_data.get("DELETE") or not contact_data.get("name"):
                    continue

                contacts_data.append(
                    ContactProfileContactSchema(
                        name=contact_data["name"],
                        email=contact_data.get("email") or fallback_email,
                        phone=contact_data.get("phone") or None,
                        order=contact_data.get("order", 0),
                        is_author=contact_data.get("is_author", False),
                        is_security_contact=contact_data.get("is_security_contact", False),
                        is_technical_contact=contact_data.get("is_technical_contact", False),
                    )
                )

            # Validate at least one contact per entity
            entity_name = entity_form.cleaned_data.get("name", "Entity") or "Author Group"
            if not contacts_data:
                raise ValidationError(f"'{entity_name}' must have at least one contact.")

            # Validate single manufacturer/supplier constraint
            if is_manufacturer:
                manufacturer_count += 1
                if manufacturer_count > 1:
                    raise ValidationError("Only one manufacturer entity is allowed.")
            if is_supplier:
                supplier_count += 1
                if supplier_count > 1:
                    raise ValidationError("Only one supplier entity is allowed.")

            entities_data.append(
                {
                    "name": name,
                    "email": email or (fallback_email if not is_author_only else ""),
                    "phone": entity_form.cleaned_data.get("phone"),
                    "address": entity_form.cleaned_data.get("address"),
                    "website_urls": website_urls_value,
                    "is_manufacturer": is_manufacturer,
                    "is_supplier": is_supplier,
                    "is_author": is_author,
                    "contacts": contacts_data,
                }
            )

        return entities_data
