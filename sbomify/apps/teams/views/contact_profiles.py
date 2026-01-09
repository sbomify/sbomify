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
    ContactEntityFormSet,
    ContactProfileContactFormSet,
    ContactProfileForm,
    ContactProfileModelForm,
)
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.schemas import (
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
            profile["entity_count"] = len(entities)
            # Calculate total contact count across all entities
            total_contacts = sum(len(entity.get("contacts", [])) for entity in entities)
            profile["contact_count"] = total_contacts
            # Get first entity for quick access
            profile["first_entity"] = entities[0] if entities else None
            profiles_list.append(profile)

        return render(
            request,
            "teams/contact_profiles/profile_list.html.j2",
            {
                "team": team,
                "profiles": profiles_list,  # Original list for template iteration
                "profiles_json": json.dumps(profiles_list),  # JSON string for JavaScript
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

        # Attach nested contact formsets to each entity form
        for entity_form in entities_formset:
            # If the entity form corresponds to an existing instance, use it
            # Check _state.adding to ensure the instance is actually persisted in DB
            entity_instance = (
                entity_form.instance if entity_form.instance.pk and not entity_form.instance._state.adding else None
            )
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
    ) -> tuple[dict, list[ContactEntityCreateSchema | ContactEntityUpdateSchema]]:
        form = ContactProfileModelForm(request.POST, instance=profile)
        if not form.is_valid():
            raise ValidationError(form.errors.as_text())

        team, _, error = _get_team_and_membership_role(request, team_key)
        if error or not team:
            raise ValidationError("Failed to get team information")
        fallback_email = _get_team_owner_email(team)

        entities_formset = ContactEntityFormSet(request.POST, instance=profile, prefix="entities")

        if not entities_formset.is_valid():
            errors = f"{entities_formset.non_form_errors().as_text()}\n{entities_formset.errors}"
            raise ValidationError(errors)

        entities_data = []
        is_update = profile is not None

        for entity_form in entities_formset:
            if entity_form.cleaned_data.get("DELETE"):
                continue

            # If empty form in create mode (no name), skip
            if not entity_form.cleaned_data.get("name"):
                continue

            # Handle nested logic validation
            contact_prefix = f"{entity_form.prefix}-contacts"
            # Note: We need to pass the instance if it exists to properly update
            # Check _state.adding to ensure the instance is actually persisted in DB
            # (not just a new instance with a generated pk from default=generate_id)
            entity_instance = (
                entity_form.instance if entity_form.instance.pk and not entity_form.instance._state.adding else None
            )
            contacts_formset = ContactProfileContactFormSet(
                request.POST, instance=entity_instance, prefix=contact_prefix
            )

            if not contacts_formset.is_valid():
                errors = f"{contacts_formset.non_form_errors().as_text()}\n{contacts_formset.errors}"
                raise ValidationError(f"Contacts error for entity '{entity_form.cleaned_data.get('name')}': {errors}")

            contacts_data = []
            for contact_form in contacts_formset:
                c_data = contact_form.cleaned_data
                if c_data.get("DELETE") or not c_data.get("name"):
                    continue

                contacts_data.append(
                    ContactProfileContactSchema(
                        name=c_data["name"],
                        email=c_data.get("email") or fallback_email,  # Use fallback instead of None
                        phone=c_data.get("phone") or None,
                        order=c_data.get("order", 0),
                    )
                )

            # Prepare entity schema
            e_data = entity_form.cleaned_data
            website_urls = e_data.get("website_urls_text", [])

            schema_cls = ContactEntityUpdateSchema if is_update and entity_instance else ContactEntityCreateSchema

            entity_payload = {
                "name": e_data["name"],
                "email": e_data.get("email") or fallback_email,
                "phone": e_data.get("phone"),
                "address": e_data.get("address"),
                "website_urls": website_urls,
                "is_manufacturer": e_data.get("is_manufacturer", False),
                "is_supplier": e_data.get("is_supplier", False),
                "is_author": e_data.get("is_author", False),
                "contacts": contacts_data,
            }

            if is_update and entity_instance:
                entity_payload["id"] = entity_instance.id

            entities_data.append(schema_cls(**entity_payload))

        if not entities_data:
            raise ValidationError("At least one entity is required.")

        return form.cleaned_data, entities_data

    def _create_profile(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            form_data, entities = self._validate_form_and_formsets(request, team_key)
        except ValidationError as e:
            return htmx_error_response(e.message)

        payload = ContactProfileCreateSchema(
            name=form_data["name"],
            is_default=form_data.get("is_default", False),
            entities=entities,
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
            form_data, entities = self._validate_form_and_formsets(request, team_key, profile=profile)
        except ValidationError as e:
            return htmx_error_response(e.message)

        payload = ContactProfileUpdateSchema(
            name=form_data["name"], is_default=form_data.get("is_default", False), entities=entities
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
            profile["entity_count"] = len(entities)
            total_contacts = sum(len(entity.get("contacts", [])) for entity in entities)
            profile["contact_count"] = total_contacts
            profile["first_entity"] = entities[0] if entities else None
            profiles_list.append(profile)

        response = render(
            request,
            "teams/contact_profiles/profile_list.html.j2",
            {
                "team": team,
                "profiles": profiles_list,
                "profiles_json": json.dumps(profiles_list),
                "form": ContactProfileForm(),
            },
        )

        # Add success trigger
        trigger_data = {"messages": [{"type": "success", "message": message}]}
        response["HX-Trigger"] = json.dumps(trigger_data)

        return response
