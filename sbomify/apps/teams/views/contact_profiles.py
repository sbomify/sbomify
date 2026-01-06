from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import (
    create_contact_profile,
    delete_contact_profile,
    get_contact_profile,
    get_team,
    list_contact_profiles,
    update_contact_profile,
)
from sbomify.apps.teams.forms import (
    ContactProfileContactFormSet,
    ContactProfileForm,
    ContactProfileModelForm,
)
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.schemas import (
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

        return render(
            request,
            "teams/contact_profiles/profile_list.html.j2",
            {
                "team": team,
                "profiles": profiles,
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

        return render(
            request,
            "teams/contact_profiles/profile_form.html.j2",
            {
                "team": team,
                "form": ContactProfileModelForm(instance=profile),
                "formset": ContactProfileContactFormSet(instance=profile),
                "profile": profile,
                "is_create": profile is None,
            },
        )

    def post(self, request: HttpRequest, team_key: str, profile_id: str | None = None) -> HttpResponse:
        if profile_id is None:
            return self._create_profile(request, team_key)
        return self._update_profile(request, team_key, profile_id)

    def _validate_form_and_formset(
        self, request: HttpRequest, profile=None
    ) -> tuple[dict, list[ContactProfileContactSchema]]:
        form = ContactProfileModelForm(request.POST, instance=profile)
        if not form.is_valid():
            raise ValidationError(form.errors.as_text())

        formset = ContactProfileContactFormSet(request.POST, instance=profile)
        contacts = []

        if not formset.is_valid():
            raise ValidationError(formset.errors.as_text())

        for contact_form in formset:
            cleaned_data = contact_form.cleaned_data
            if not cleaned_data:
                continue

            name = cleaned_data.get("name", "").strip()
            if not name:
                continue

            contacts.append(
                ContactProfileContactSchema(
                    name=name,
                    email=cleaned_data.get("email") or None,
                    phone=cleaned_data.get("phone") or None,
                )
            )

        if not contacts and not profile:
            raise ValidationError("Please fill at least one contact.")

        return form.cleaned_data, contacts

    def _create_profile(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            form_data, contacts = self._validate_form_and_formset(request)
        except ValidationError as e:
            return htmx_error_response(e.message)

        website_urls = form_data.pop("website_urls_text", [])
        payload = ContactProfileCreateSchema(
            **form_data,
            website_urls=website_urls,
            contacts=contacts,
        )

        status_code, result = create_contact_profile(request, team_key, payload)
        if status_code != 201:
            return htmx_error_response(result.get("detail", "Failed to create profile"))

        return htmx_success_response("Contact profile created successfully", triggers={"refreshProfileList": True})

    def _update_profile(self, request: HttpRequest, team_key: str, profile_id: str) -> HttpResponse:
        status_code, profile = get_contact_profile(request, team_key, profile_id, return_instance=True)
        if status_code != 200:
            return htmx_error_response(profile.get("detail", "Failed to load contact profile"))

        try:
            form_data, contacts = self._validate_form_and_formset(request, profile=profile)
        except ValidationError as e:
            return htmx_error_response(e.message)

        website_urls = form_data.pop("website_urls_text", None)
        payload_data = {}
        for k, v in form_data.items():
            if v is not None or k == "is_default":
                payload_data[k] = v

        if website_urls is not None:
            payload_data["website_urls"] = website_urls

        payload = ContactProfileUpdateSchema(
            **payload_data,
            contacts=contacts,
        )

        status_code, result = update_contact_profile(request, team_key, profile_id, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update profile"))

        return htmx_success_response("Contact profile updated successfully", triggers={"refreshProfileList": True})
