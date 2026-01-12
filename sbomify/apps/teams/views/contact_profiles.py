import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import (
    _get_team_and_membership_role,
    _get_team_owner_email,
    create_contact_profile,
    delete_contact_profile,
    get_contact_profile,
    get_team,
    list_contact_profiles,
    update_contact_profile,
)
from sbomify.apps.teams.forms import (
    AuthorContactFormSet,
    ContactEntityFormSet,
    ContactProfileContactFormSet,
    ContactProfileForm,
    ContactProfileModelForm,
)
from sbomify.apps.teams.models import ContactProfile
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.schemas import (
    AuthorContactSchema,
    ContactEntityCreateSchema,
    ContactEntityUpdateSchema,
    ContactProfileContactSchema,
    ContactProfileCreateSchema,
    ContactProfileUpdateSchema,
)


class ValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _format_formset_errors(formset) -> str:
    """Format formset errors into user-friendly messages."""
    messages = []
    for error in formset.non_form_errors():
        messages.append(str(error))

    for i, form_errors in enumerate(formset.errors):
        if not form_errors:
            continue
        for field, field_errors in form_errors.items():
            # Get error objects with codes if available
            error_list = field_errors.as_data() if hasattr(field_errors, "as_data") else []
            for idx, error in enumerate(field_errors):
                if field == "__all__":
                    # Check for unique constraint violation using error code (more robust than string matching)
                    error_code = error_list[idx].code if idx < len(error_list) else None
                    if error_code in ("unique", "unique_together"):
                        messages.append(
                            "Duplicate entity name. Each entity must have a unique name within the profile."
                        )
                    else:
                        messages.append(str(error))
                else:
                    messages.append(f"{field}: {error}")

    return " ".join(messages) if messages else "Validation failed"


class ContactProfileView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Failed to load team"))

        status_code, profiles = list_contact_profiles(request, team_key)
        if status_code != 200:
            return htmx_error_response(profiles.get("detail", "Failed to load contact profiles"))

        profiles_list = []
        for profile_schema in profiles:
            # Convert Pydantic model to dict to allow .get() and modification
            profile = profile_schema.model_dump()

            entities = profile.get("entities", [])
            authors = profile.get("authors", [])
            profile["entity_count"] = len(entities)
            profile["author_count"] = len(authors)
            # Calculate total contact count across all entities
            total_contacts = sum(len(entity.get("contacts", [])) for entity in entities)
            profile["contact_count"] = total_contacts
            # Get manufacturer and supplier entities
            profile["manufacturer"] = next((e for e in entities if e.get("is_manufacturer")), None)
            profile["supplier"] = next((e for e in entities if e.get("is_supplier")), None)
            profiles_list.append(profile)

        return render(
            request,
            "teams/contact_profiles/profile_list.html.j2",
            {
                "team": team,
                "profiles": profiles_list,
                "form": ContactProfileForm(),
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request, team_key)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request, team_key)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest, team_key: str) -> HttpResponse:
        form = ContactProfileForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        status_code, result = delete_contact_profile(request, team_key, form.cleaned_data["profile_id"])
        if status_code != 204:
            return htmx_error_response(result.get("detail", "Failed to delete profile"))

        return htmx_success_response("Contact profile deleted successfully", triggers={"refreshProfileList": True})

    def _patch(self, request: HttpRequest, team_key: str) -> HttpResponse:
        form = ContactProfileForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        status_code, profile = get_contact_profile(request, team_key, form.cleaned_data["profile_id"])
        if status_code != 200:
            return htmx_error_response(profile.get("detail", "Failed to load contact profile"))

        if not profile.is_default:
            payload = ContactProfileUpdateSchema(is_default=True)

            status_code, result = update_contact_profile(request, team_key, profile.id, payload)
            if status_code != 200:
                return htmx_error_response(result.get("detail", "Failed to set default profile"))

        return htmx_success_response(f"'{profile.name}' set as default profile", triggers={"refreshProfileList": True})


class ContactProfileFormView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str, profile_id: str | None = None) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Failed to load team"))

        profile = None
        if profile_id:
            status_code, profile = get_contact_profile(request, team_key, profile_id, return_instance=True)
            if status_code != 200:
                return htmx_error_response(profile.get("detail", "Failed to load contact profile"))

        entities_formset = ContactEntityFormSet(instance=profile, prefix="entities")
        authors_formset = AuthorContactFormSet(instance=profile, prefix="authors")

        # Attach nested contact formsets to each entity form
        for entity_form in entities_formset:
            # If the entity form corresponds to an existing instance, use it
            entity_instance = entity_form.instance if entity_form.instance.pk is not None else None
            entity_form.contacts_formset = ContactProfileContactFormSet(
                instance=entity_instance, prefix=f"{entity_form.prefix}-contacts"
            )

        return render(
            request,
            "teams/contact_profiles/profile_form.html.j2",
            {
                "team": team,
                "form": ContactProfileModelForm(instance=profile),
                "entities_formset": entities_formset,
                "authors_formset": authors_formset,
                "profile": profile,
                "is_create": profile is None,
            },
        )

    def post(self, request: HttpRequest, team_key: str, profile_id: str | None = None) -> HttpResponse:
        if profile_id is None:
            return self._create_profile(request, team_key)
        return self._update_profile(request, team_key, profile_id)

    def _validate_form_and_formsets(
        self, request: HttpRequest, team_key: str, profile=None
    ) -> tuple[dict, list[ContactEntityCreateSchema | ContactEntityUpdateSchema], list[AuthorContactSchema]]:
        form = ContactProfileModelForm(request.POST, instance=profile)
        if not form.is_valid():
            raise ValidationError(form.errors.as_text())

        team, _, error = _get_team_and_membership_role(request, team_key)
        if error or not team:
            raise ValidationError("Failed to get team information")
        fallback_email = _get_team_owner_email(team)

        entities_formset = ContactEntityFormSet(request.POST, instance=profile, prefix="entities")
        authors_formset = AuthorContactFormSet(request.POST, instance=profile, prefix="authors")

        if not entities_formset.is_valid():
            raise ValidationError(_format_formset_errors(entities_formset))

        if not authors_formset.is_valid():
            raise ValidationError(_format_formset_errors(authors_formset))

        entities_data = self._process_entity_formset(request, entities_formset, fallback_email, profile)
        authors_data = self._process_author_formset(authors_formset, fallback_email)

        return form.cleaned_data, entities_data, authors_data

    def _process_entity_formset(
        self,
        request: HttpRequest,
        formset: ContactEntityFormSet,
        fallback_email: str,
        profile: ContactProfile | None,
    ) -> list[ContactEntityCreateSchema | ContactEntityUpdateSchema]:
        entities_data = []
        is_update = profile is not None
        manufacturer_count = 0
        supplier_count = 0

        for entity_form in formset:
            if entity_form.cleaned_data.get("DELETE"):
                continue

            name = (entity_form.cleaned_data.get("name") or "").strip()
            email = (entity_form.cleaned_data.get("email") or "").strip()

            # Detect partially filled forms to prevent silent data loss
            # Note: Role flags (is_manufacturer, is_supplier) are excluded because they have default=True
            has_phone = bool((entity_form.cleaned_data.get("phone") or "").strip())
            has_address = bool((entity_form.cleaned_data.get("address") or "").strip())
            has_websites = bool((entity_form.cleaned_data.get("website_urls_text") or "").strip())

            contact_prefix = f"{entity_form.prefix}-contacts"
            entity_instance = entity_form.instance

            # Special handling for models with UUID primary keys:
            # Unlike AutoField, UUID PKs are set before save(), so pk is not None for new instances.
            # We need to distinguish between new (unsaved) and existing (saved) instances to prevent
            # Django formset from filtering by FK relationships on unsaved instances (raises ValueError).
            #
            # Note: _state.adding is semi-private but is the standard Django way to detect this.
            # Django's own formsets use this internally. There's no public API alternative for this.
            # See: django.forms.models.BaseInlineFormSet._construct_form()
            is_new_instance = (
                getattr(entity_instance._state, "adding", True) if hasattr(entity_instance, "_state") else True
            )

            formset_kwargs = {"prefix": contact_prefix}

            if not is_new_instance:
                # Existing instance: formset can filter related objects by FK
                formset_kwargs["instance"] = entity_instance
            else:
                # New instance: prevent FK filtering by using empty queryset
                formset_kwargs["queryset"] = ContactProfileContactFormSet.model.objects.none()

            contacts_formset_check = ContactProfileContactFormSet(request.POST, **formset_kwargs)
            # Must call is_valid() before accessing cleaned_data
            contacts_formset_check.is_valid()

            # Check if any contact has data to detect partially filled contacts
            has_contacts = False
            for cf in contacts_formset_check:
                if not cf.has_changed():
                    continue
                if hasattr(cf, "cleaned_data") and cf.cleaned_data.get("DELETE"):
                    continue
                has_contacts = True
                break

            has_significant_data = has_phone or has_address or has_websites or has_contacts

            # Error if form has data but missing required name/email
            if has_significant_data and (not name or not email):
                missing = []
                if not name:
                    missing.append("name")
                if not email:
                    missing.append("email")
                raise ValidationError(
                    f"Entity has data but is missing required field(s): {', '.join(missing)}. "
                    "Please complete the entity or remove it."
                )

            # Skip empty forms
            if not name or not email:
                continue

            # Reuse the contacts formset we already created for the check
            contacts_formset = contacts_formset_check

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
                    )
                )

            # Validate at least one contact per entity (CycloneDX requirement)
            entity_name = entity_form.cleaned_data.get("name", "Entity")
            if not contacts_data:
                raise ValidationError(f"'{entity_name}' must have at least one contact.")

            # Prepare entity schema
            entity_cleaned_data = entity_form.cleaned_data
            website_urls = entity_cleaned_data.get("website_urls_text", [])

            is_manufacturer = entity_cleaned_data.get("is_manufacturer", False)
            is_supplier = entity_cleaned_data.get("is_supplier", False)

            # Validate single manufacturer/supplier constraint (CycloneDX aligned)
            if is_manufacturer:
                manufacturer_count += 1
                if manufacturer_count > 1:
                    raise ValidationError("A profile can have only one manufacturer entity (CycloneDX requirement).")
            if is_supplier:
                supplier_count += 1
                if supplier_count > 1:
                    raise ValidationError("A profile can have only one supplier entity (CycloneDX requirement).")

            schema_cls = ContactEntityUpdateSchema if is_update and entity_instance else ContactEntityCreateSchema

            entity_payload = {
                "name": entity_cleaned_data["name"],
                "email": entity_cleaned_data.get("email") or fallback_email,
                "phone": entity_cleaned_data.get("phone"),
                "address": entity_cleaned_data.get("address"),
                "website_urls": website_urls,
                "is_manufacturer": is_manufacturer,
                "is_supplier": is_supplier,
                "contacts": contacts_data,
            }

            if is_update and entity_instance:
                entity_payload["id"] = entity_instance.id

            entities_data.append(schema_cls(**entity_payload))

        return entities_data

    def _process_author_formset(
        self,
        formset: AuthorContactFormSet,
        fallback_email: str,
    ) -> list[AuthorContactSchema]:
        authors_data = []
        for author_form in formset:
            author_data = author_form.cleaned_data
            if author_data.get("DELETE") or not author_data.get("name"):
                continue

            authors_data.append(
                AuthorContactSchema(
                    name=author_data["name"],
                    email=author_data.get("email") or fallback_email,
                    phone=author_data.get("phone") or None,
                    order=author_data.get("order", 0),
                )
            )
        return authors_data

    def _create_profile(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            form_data, entities, authors = self._validate_form_and_formsets(request, team_key)
        except ValidationError as e:
            return htmx_error_response(e.message)

        payload = ContactProfileCreateSchema(
            name=form_data["name"],
            is_default=form_data.get("is_default", False),
            entities=entities,
            authors=authors,
        )

        status_code, result = create_contact_profile(request, team_key, payload)
        if status_code != 201:
            return htmx_error_response(result.get("detail", "Failed to create profile"))

        return self._render_profile_list_response(request, team_key, "Contact profile created successfully")

    def _update_profile(self, request: HttpRequest, team_key: str, profile_id: str) -> HttpResponse:
        status_code, profile = get_contact_profile(request, team_key, profile_id, return_instance=True)
        if status_code != 200:
            return htmx_error_response(profile.get("detail", "Failed to load contact profile"))

        try:
            form_data, entities, authors = self._validate_form_and_formsets(request, team_key, profile=profile)
        except ValidationError as e:
            return htmx_error_response(e.message)

        payload = ContactProfileUpdateSchema(
            name=form_data["name"],
            is_default=form_data.get("is_default", False),
            entities=entities,
            authors=authors,
        )

        status_code, result = update_contact_profile(request, team_key, profile_id, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update profile"))

        return self._render_profile_list_response(request, team_key, "Contact profile updated successfully")

    def _render_profile_list_response(self, request: HttpRequest, team_key: str, message: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response("Failed to load team")

        status_code, profiles = list_contact_profiles(request, team_key)
        if status_code != 200:
            return htmx_error_response("Failed to load contact profiles")

        profiles_list = []
        for profile_schema in profiles:
            # Convert Pydantic model to dict
            profile = profile_schema.model_dump()
            entities = profile.get("entities", [])
            authors = profile.get("authors", [])
            profile["entity_count"] = len(entities)
            profile["author_count"] = len(authors)
            total_contacts = sum(len(entity.get("contacts", [])) for entity in entities)
            profile["contact_count"] = total_contacts
            # Get manufacturer and supplier entities
            profile["manufacturer"] = next((e for e in entities if e.get("is_manufacturer")), None)
            profile["supplier"] = next((e for e in entities if e.get("is_supplier")), None)
            profiles_list.append(profile)

        response = render(
            request,
            "teams/contact_profiles/profile_list.html.j2",
            {
                "team": team,
                "profiles": profiles_list,
                "form": ContactProfileForm(),
            },
        )

        # Add success trigger
        trigger_data = {"messages": [{"type": "success", "message": message}]}
        response["HX-Trigger"] = json.dumps(trigger_data)

        return response
