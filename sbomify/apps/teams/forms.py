from django import forms
from django.conf import settings
from django.forms import inlineformset_factory

from sbomify.apps.teams.models import AuthorContact, ContactEntity, ContactProfile, ContactProfileContact, Member, Team


class AddTeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name"]

    def save(self, *args, user=None, **kwargs):
        is_new = self.instance._state.adding
        super().save(*args, **kwargs)
        if is_new and user:
            is_default_team = not Member.objects.filter(user=user).exists()
            Member.objects.create(team=self.instance, user=user, is_default_team=is_default_team, role="owner")
        return self.instance


class UpdateTeamForm(forms.Form):
    key = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


class DeleteTeamForm(forms.Form):
    key = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


class InviteUserForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    role = forms.ChoiceField(
        required=True,
        choices=settings.TEAMS_SUPPORTED_ROLES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )


class TeamBrandingForm(forms.Form):
    brand_color = forms.CharField(required=False)
    accent_color = forms.CharField(required=False)
    branding_enabled = forms.BooleanField(required=False)
    icon_pending_deletion = forms.BooleanField(required=False)
    logo_pending_deletion = forms.BooleanField(required=False)
    icon = forms.FileField(required=False)
    logo = forms.FileField(required=False)


class TeamGeneralSettingsForm(forms.Form):
    """Form for updating workspace general settings (name)."""

    name = forms.CharField(
        max_length=255,
        min_length=1,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter workspace name",
            }
        ),
    )


class OnboardingProductForm(forms.Form):
    """Form for creating a product during onboarding."""

    name = forms.CharField(
        label="Product Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter product name",
                "autofocus": True,
            }
        ),
        help_text=(
            "A product is your top-level offering, which can be physical hardware, software, or a combination of both. "
            "For example, a smart device, an application suite, or an IoT platform."
        ),
    )


class OnboardingProjectForm(forms.Form):
    """Form for creating a project during onboarding."""

    name = forms.CharField(
        label="Project Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter project name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Projects are logical groupings within your product. For example, a smart device might have "
            "firmware, mobile app, and cloud backend projects."
        ),
    )


class OnboardingComponentForm(forms.Form):
    """Form for creating a component during onboarding."""

    name = forms.CharField(
        label="Component Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter component name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Components are the individual building blocks that make up your project. These can be libraries, "
            "microservices, firmware modules, or any other distinct piece of software."
        ),
    )


class OnboardingCompanyForm(forms.Form):
    """Single-step onboarding form for SBOM identity setup."""

    company_name = forms.CharField(
        label="Company / Organization Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "e.g., Acme Corporation",
                "autofocus": True,
            }
        ),
    )
    contact_name = forms.CharField(
        label="Contact Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "e.g., Jane Smith",
            }
        ),
    )
    email = forms.EmailField(
        label="Contact Email",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "security@example.com",
            }
        ),
    )
    website = forms.URLField(
        label="Website",
        required=False,
        widget=forms.URLInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "https://example.com",
            }
        ),
    )


class DeleteMemberForm(forms.Form):
    member_id = forms.IntegerField(
        required=True,
        widget=forms.HiddenInput(),
    )


class DeleteInvitationForm(forms.Form):
    invitation_id = forms.IntegerField(
        required=True,
        widget=forms.HiddenInput(),
    )


class ContactProfileForm(forms.Form):
    profile_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


class ContactProfileModelForm(forms.ModelForm):
    """Form for ContactProfile - only contains profile-level fields."""

    class Meta:
        model = ContactProfile
        fields = ["name", "is_default"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Profile name"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class DeleteAwareModelFormMixin:
    """Mixin for ModelForms to exclude deleted PKs from unique validation.

    When used with BaseDeleteAwareInlineFormSet, this mixin enables forms to
    skip database unique validation for records that are being deleted in the
    same formset submission.
    """

    def validate_unique(self):
        """Override to exclude PKs being deleted from unique validation query."""
        exclude_pks = getattr(self, "_exclude_pks_from_unique", set())
        if not exclude_pks:
            return super().validate_unique()

        # Manually perform unique validation, excluding the deleted PKs
        from django.core.exceptions import ValidationError

        model = self._meta.model
        # Unpack only unique_checks; date_checks are handled by Django's standard validation
        unique_checks, _ = self.instance._get_unique_checks(exclude=self._get_validation_exclusions())

        errors = []
        for model_class, unique_check in unique_checks:
            # Build lookup kwargs for this unique constraint
            lookup_kwargs = {}
            for field_name in unique_check:
                if field_name == model._meta.pk.name:
                    continue
                field = model._meta.get_field(field_name)
                lookup_value = getattr(self.instance, field.attname, None)
                if lookup_value is None:
                    # Null values don't trigger unique violations
                    break
                lookup_kwargs[field.name] = lookup_value
            else:
                if lookup_kwargs:
                    # Query for duplicates, excluding the current instance and deleted PKs
                    qs = model_class._default_manager.filter(**lookup_kwargs)
                    if self.instance.pk:
                        qs = qs.exclude(pk=self.instance.pk)
                    if exclude_pks:
                        qs = qs.exclude(pk__in=exclude_pks)

                    if qs.exists():
                        errors.append(self.unique_error_message(model_class, unique_check))

        if errors:
            raise ValidationError(errors)


class ContactEntityModelForm(DeleteAwareModelFormMixin, forms.ModelForm):
    """Form for ContactEntity - contains organization/company details.

    An entity can be a manufacturer, supplier, or both.
    At least one role must be selected.
    """

    id = forms.CharField(required=False, widget=forms.HiddenInput())

    is_manufacturer = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    is_supplier = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    website_urls_text = forms.CharField(
        label="Website URLs",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Enter one URL per line\nhttps://example.com",
            }
        ),
        help_text="Enter one URL per line",
    )

    class Meta:
        model = ContactEntity
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "address",
            "is_manufacturer",
            "is_supplier",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Entity name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "contact@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
            "address": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Street, City, Country"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.website_urls:
            self.fields["website_urls_text"].initial = "\n".join(self.instance.website_urls)

        if self.instance and self.instance.pk:
            # Set initial roles from instance
            self.fields["is_manufacturer"].initial = self.instance.is_manufacturer
            self.fields["is_supplier"].initial = self.instance.is_supplier

    def clean(self):
        cleaned_data = super().clean()
        is_manufacturer = cleaned_data.get("is_manufacturer", False)
        is_supplier = cleaned_data.get("is_supplier", False)

        if not is_manufacturer and not is_supplier:
            raise forms.ValidationError("At least one role (Manufacturer or Supplier) must be selected.")

        return cleaned_data

    def clean_website_urls_text(self):
        text = self.cleaned_data.get("website_urls_text")
        if not text:
            return []
        return [url.strip() for url in text.split("\n") if url.strip()]

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.website_urls = self.cleaned_data.get("website_urls_text", [])
        instance.is_manufacturer = self.cleaned_data.get("is_manufacturer", False)
        instance.is_supplier = self.cleaned_data.get("is_supplier", False)
        if commit:
            instance.save()
        return instance


class ContactProfileContactForm(DeleteAwareModelFormMixin, forms.ModelForm):
    id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ContactProfileContact
        fields = ["id", "name", "email", "phone"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
        }


class BaseDeleteAwareInlineFormSet(forms.BaseInlineFormSet):
    """Base formset that excludes deleted forms from unique validation.

    Django's default validation has two issues when deleting and re-adding items:
    1. Formset-level: validate_unique() checks across ALL forms including deleted ones
    2. Form-level: Each ModelForm's validate_unique() checks the database, but deleted
       items haven't been removed yet during validation

    This class fixes both by:
    1. Overriding validate_unique() to exclude deleted forms
    2. Collecting deleted PKs and passing them to forms for database query exclusion
    """

    def full_clean(self):
        """Override to collect deleted PKs before form validation."""
        # Collect PKs of forms marked for deletion BEFORE validation
        # We need to do this early because forms need this info during their validate_unique
        # Note: self.forms is populated during formset construction, so it's available
        # before super().full_clean() is called. This is standard Django formset behavior.
        self._deleted_pks = set()

        # First pass: identify which forms are marked for deletion
        for form in self.forms:
            # Check if form has data indicating deletion
            # Django formsets use "on" for checked checkboxes, but we also check
            # string representations that might come from x-model bindings or other sources
            delete_key = f"{form.prefix}-DELETE"
            if self.data.get(delete_key) in ("on", "True", "true", "1"):
                # This form is being deleted - get its instance PK if it exists
                if form.instance and form.instance.pk:
                    self._deleted_pks.add(form.instance.pk)

        # Inject deleted PKs into each form so they can exclude them from unique checks
        # Note: self.forms is populated during formset construction, so it's available
        # before super().full_clean() is called. This is standard Django formset behavior.
        for form in self.forms:
            form._exclude_pks_from_unique = self._deleted_pks

        super().full_clean()

    def validate_unique(self):
        """Override to exclude deleted forms from formset-level unique validation."""
        original_forms = self.forms
        self.forms = [f for f in self.forms if not self._should_delete_form(f)]
        try:
            super().validate_unique()
        finally:
            self.forms = original_forms


# Formset for contacts linked to an entity (3-level hierarchy)
ContactProfileContactFormSet = inlineformset_factory(
    ContactEntity,
    ContactProfileContact,
    form=ContactProfileContactForm,
    formset=BaseDeleteAwareInlineFormSet,
    extra=0,
    can_delete=True,
)


# Formset for entities linked to a profile
ContactEntityFormSet = inlineformset_factory(
    ContactProfile,
    ContactEntity,
    form=ContactEntityModelForm,
    formset=BaseDeleteAwareInlineFormSet,
    extra=0,
    can_delete=True,
)


class AuthorContactForm(DeleteAwareModelFormMixin, forms.ModelForm):
    """Form for AuthorContact - individual author contacts (CycloneDX aligned).

    Authors are individuals, not organizations.
    """

    id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = AuthorContact
        fields = ["id", "name", "email", "phone"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Author name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
        }


# Formset for author contacts linked directly to a profile (CycloneDX aligned)
AuthorContactFormSet = inlineformset_factory(
    ContactProfile,
    AuthorContact,
    form=AuthorContactForm,
    formset=BaseDeleteAwareInlineFormSet,
    extra=0,
    can_delete=True,
)


class VulnerabilitySettingsForm(forms.Form):
    vulnerability_provider = forms.ChoiceField(
        required=True,
        choices=[("osv", "OSV"), ("dependency_track", "Dependency Track")],
    )
    custom_dt_server_id = forms.CharField(
        required=False,
    )
