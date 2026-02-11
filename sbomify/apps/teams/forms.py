from django import forms
from django.conf import settings
from django.forms import inlineformset_factory

from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact, Member, Team


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
        choices=[(role, label) for role, label in settings.TEAMS_SUPPORTED_ROLES if role != "guest"],
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
    goal = forms.CharField(
        label="What are you trying to accomplish?",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control form-control-lg",
                "rows": 3,
                "maxlength": 1000,
                "placeholder": "e.g., Track open source dependencies, meet compliance requirements...",
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
    """Form for ContactProfile - only contains profile-level fields.

    Note: We explicitly set required=True on name field to ensure server-side
    validation works even if JavaScript is disabled. While Django ModelForm
    would normally infer this from the model (blank=False), being explicit
    ensures data integrity regardless of client-side validation state.
    """

    # Explicitly set required=True for server-side validation (works even if JavaScript is disabled)
    name = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Profile name"}),
    )

    class Meta:
        model = ContactProfile
        fields = ["name", "is_default"]
        widgets = {
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class DeleteAwareModelFormMixin:
    """Mixin for ModelForms to exclude deleted PKs from unique validation.

    When used with BaseDeleteAwareInlineFormSet, this mixin enables forms to
    skip database unique validation for records that are being deleted in the
    same formset submission.
    """

    def validate_unique(self):
        """Override to exclude PKs being deleted from unique validation query.

        Returns:
            None: If validation passes (no unique constraint violations).

        Raises:
            ValidationError: If a unique constraint violation is detected
                (excluding the PKs specified in _exclude_pks_from_unique).
        """
        exclude_pks = getattr(self, "_exclude_pks_from_unique", set())
        if not exclude_pks:
            return super().validate_unique()

        # Manually perform unique validation, excluding the deleted PKs
        from django.core.exceptions import ValidationError

        model = self._meta.model
        # Unpack only unique_checks; date_checks are intentionally omitted.
        # The models using this mixin (ContactEntity, ContactProfileContact, AuthorContact)
        # do not use date-based unique constraints (unique_for_date, unique_for_month, unique_for_year),
        # so date_checks will be empty.
        #
        # NOTE: If date-based unique constraints are added to any model using this mixin in the future,
        # the validate_unique method would need to be updated to handle date_checks, or tests should
        # verify that date validation still works correctly (e.g., by calling super().validate_unique()
        # for date validation only, or by implementing custom date validation logic).
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

    An entity can be a manufacturer, supplier, author, or a combination.
    At least one role must be selected.

    When is_author is the ONLY role selected:
        - name and email are optional (authors are individuals, not organizations)
        - Only contacts are required (the actual author individuals)
    """

    id = forms.CharField(required=False, widget=forms.HiddenInput())

    # Name and email are optional for author-only entities, but required otherwise
    # Validation happens in clean() method
    name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Entity name"}),
    )

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "contact@example.com"}),
    )

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

    is_author = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Group of individual authors (no organization info required if only this role)",
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
            "is_author",
        ]
        widgets = {
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
            self.fields["is_author"].initial = self.instance.is_author

    def clean(self):
        cleaned_data = super().clean()
        is_manufacturer = cleaned_data.get("is_manufacturer", False)
        is_supplier = cleaned_data.get("is_supplier", False)
        is_author = cleaned_data.get("is_author", False)

        # At least one role must be selected
        if not is_manufacturer and not is_supplier and not is_author:
            raise forms.ValidationError("At least one role (Manufacturer, Supplier, or Author) must be selected.")

        # If not author-only, name and email are required
        is_author_only = is_author and not is_manufacturer and not is_supplier
        if not is_author_only:
            name = cleaned_data.get("name", "").strip()
            email = cleaned_data.get("email", "").strip()
            if not name:
                self.add_error("name", "Entity name is required for Manufacturer/Supplier entities.")
            if not email:
                self.add_error("email", "Entity email is required for Manufacturer/Supplier entities.")

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
        instance.is_author = self.cleaned_data.get("is_author", False)
        if commit:
            instance.save()
        return instance


class ContactProfileContactForm(DeleteAwareModelFormMixin, forms.ModelForm):
    """Form for ContactProfileContact - individual contacts within an entity.

    A contact can have multiple roles indicated by checkboxes:
    - is_author: Person who authored the SBOM
    - is_security_contact: Security/vulnerability reporting contact (CRA requirement)
    - is_technical_contact: Technical point of contact

    Note: We explicitly set required=True on name and email fields to ensure
    server-side validation works even if JavaScript is disabled.
    """

    id = forms.CharField(required=False, widget=forms.HiddenInput())

    # Explicitly set required=True for server-side validation (works even if JavaScript is disabled)
    name = forms.CharField(
        required=True,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact name"}),
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"}),
    )

    # Role checkboxes - a contact can have multiple roles
    is_author = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Author",
        help_text="Person who authored the SBOM",
    )

    is_security_contact = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Security Contact",
        help_text="Security/vulnerability reporting contact (CRA requirement). Only one per profile.",
    )

    is_technical_contact = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Technical Contact",
        help_text="Technical point of contact",
    )

    class Meta:
        model = ContactProfileContact
        fields = ["id", "name", "email", "phone", "is_author", "is_security_contact", "is_technical_contact"]
        widgets = {
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
        """Override to collect deleted PKs before form validation.

        Collects primary keys of forms marked for deletion and injects them
        into each form's _exclude_pks_from_unique attribute so they can be
        excluded from unique validation checks.

        Returns:
            None: This method returns None, following Django's formset conventions.
                  Validation errors are stored in formset.errors and form.errors.

        Raises:
            ValidationError: If validation fails, this is raised by super().full_clean().
        """
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
        """Override to exclude deleted forms from formset-level unique validation.

        Returns:
            None: If validation passes (no unique constraint violations).

        Raises:
            ValidationError: If a unique constraint violation is detected
                (excluding forms marked for deletion).
        """
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


class VulnerabilitySettingsForm(forms.Form):
    vulnerability_provider = forms.ChoiceField(
        required=True,
        choices=[("osv", "OSV"), ("dependency_track", "Dependency Track")],
    )
    custom_dt_server_id = forms.CharField(
        required=False,
    )
